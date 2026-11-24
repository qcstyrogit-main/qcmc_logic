frappe.ui.form.on("Sales Order", {
	onload(frm) {
		set_shipping_address_query(frm);
		set_customer_account_manager(frm, false);
	},

	refresh(frm) {
		set_shipping_address_query(frm);
		set_customer_account_manager(frm, false);
		refresh_delivery_schedule_buttons(frm);
	},
	items_add(frm) { refresh_delivery_schedule_buttons(frm); },
	items_remove(frm) { refresh_delivery_schedule_buttons(frm); },
	items_move(frm) { refresh_delivery_schedule_buttons(frm); },

	customer(frm) {
		set_shipping_address_query(frm);
		set_customer_account_manager(frm, true);
	},
});

function refresh_delivery_schedule_buttons(frm) {
	const group = __("Delivery Schedule");
	(frm._qcmc_schedule_button_labels || []).forEach(label => frm.remove_custom_button(label, group));
	frm._qcmc_schedule_button_labels = [];
	if (!frappe.user.has_role("Sales Coordinator") || frm.doc.docstatus > 1 || !(frm.doc.items || []).length) return;
	const label = __("Schedule Deliveries");
	frm.add_custom_button(label, () => {
		prepare_delivery_schedule_editor(frm).catch(() => {});
	}, group);
	frm._qcmc_schedule_button_labels.push(label);
}

async function prepare_delivery_schedule_editor(frm) {
	if (frm.is_new()) {
		await frm.save();
		if (frm.is_new()) return;
	}
	const initialize = async () => {
		const response = await frappe.call({
			method: "qcmc_logic.api.delivery_schedule_service.initialize_sales_order_delivery_schedules",
			args: {sales_order: frm.doc.name},
			freeze: true,
			freeze_message: __("Initializing delivery schedule commitments..."),
		});
		if (response.exc || !response.message) return;

		await frm.reload_doc();
		await open_delivery_schedule_editor(frm);
	};
	return initialize();
}

function set_shipping_address_query(frm) {
	frm.set_query("shipping_address_name", () => ({
		query: "frappe.contacts.doctype.address.address.address_query",
		filters: {
			link_doctype: "Customer",
			link_name: frm.doc.customer,
			address_type: "Shipping",
		},
	}));
}

function set_customer_account_manager(frm, force) {
	if (!frm.doc.customer) {
		if (force) {
			frm.set_value("custom_account_manager", "");
		}
		return;
	}

	if (!force && frm.doc.custom_account_manager) {
		return;
	}

	frappe.call({
		method: "qcmc_logic.customs.sales_order.get_customer_account_manager",
		args: {
			customer: frm.doc.customer,
		},
		callback(r) {
			frm.set_value("custom_account_manager", r.message || "");
		},
	});
}

async function open_delivery_schedule_editor(frm) {
	const esc = value => frappe.utils.escape_html(value == null ? "" : String(value));
	let grid = null;
	let items = [];
	let initial = [];
	try {
		const response = await frappe.call({
			method: "qcmc_logic.api.delivery_schedule_service.get_sales_order_schedule_grid",
			args: {sales_order: frm.doc.name},
		});
		if (response.exc || !response.message) return;
		grid = response.message;
		items = grid.items || [];
		initial = (grid.rows || []).map(row => ({...row, item_locked: true}));
	} catch (error) {
		return;
	}
	if (!items.length) return frappe.msgprint(__("Add Sales Order Items before planning deliveries."));
	let dialog;
	let saved = false;
	const item_key = row => row.sales_order_item || (row.item_idx ? `@${row.item_idx}` : "");
	const item_options = selected => `<option value="">${__("Select Item")}</option>${items.map(item => {
		const value = item.sales_order_item || `@${item.idx}`;
		return `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(item.item_code)} · ${esc(item.item_name || "")}</option>`;
	}).join("")}`;
	const is_fully_committed = row => Number(row.dn_committed_qty || 0) > 0
		&& Number(row.planned_qty || 0) <= Number(row.dn_committed_qty || 0);
	const render_row = row => {
		const allocated = Number(row.dn_committed_qty || 0);
		const free = Math.max(0, Number(row.planned_qty || 0) - allocated);
		const fully = is_fully_committed(row);
		const lapsed = Boolean(row.schedule_name && row.delivery_date < frappe.datetime.get_today());
		// New unsaved rows have no history_status yet; only persisted schedules
		// with unreconciled history must be read-only.
		const reconciliation_required = Boolean(row.schedule_name) && row.history_status !== "Verified";
		const precision = Number(row.precision || 3);
		const min_qty = Math.max(allocated, Math.pow(10, -precision));
		const remove_disabled = allocated > 0 || row.has_dn_history || reconciliation_required || lapsed;
		const lock_note = lapsed ? __("Past schedule. Use Delivery Schedule Workbench to move it.") : reconciliation_required ? __("Existing schedule data needs backend correction.")
			: fully ? __("Quantity committed to a Delivery Note.")
			: row.date_locked ? __("Delivery date locked by Delivery Note history.") : "";
		const static_item = row.item_locked || row.schedule_name;
		const chosen = row.sales_order_item || (row.item_idx ? `@${row.item_idx}` : "");
		const blank_new = !row.schedule_name && (row.planned_qty === "" || Number(row.planned_qty) === 0);
		return `<tr class="qcmc-so-grid-row${fully ? " is-committed" : ""}" data-lapsed="${lapsed ? 1 : 0}" data-remove-locked="${remove_disabled ? 1 : 0}" data-schedule-name="${esc(row.schedule_name || "")}" data-sales-order-item="${esc(row.sales_order_item || "")}" data-item-idx="${esc(row.idx || row.item_idx || "")}" data-item-locked="${static_item ? 1 : 0}" data-ordered="${esc(row.ordered_qty || 0)}" data-delivered="${esc(row.delivered_qty || 0)}" data-uom="${esc(row.uom || "")}" data-precision="${precision}" data-original-date="${esc(row.delivery_date || "")}" data-original-planned="${esc(row.planned_qty || 0)}" data-original-remarks="${esc(row.remarks || "")}" data-allocated="${esc(allocated)}" data-history="${row.has_dn_history ? 1 : 0}" data-date-locked="${row.date_locked ? 1 : 0}">
			<td class="qcmc-so-grid-item">${static_item
				? `<strong>${esc(row.item_code || "")}</strong><small>${esc(row.item_name || "")}</small>`
				: `<select class="form-control qcmc-so-grid-item-select" aria-label="${__("Sales Order Item")}">${item_options(chosen)}</select><div class="qcmc-so-grid-error" data-error-for="item" role="alert"></div>`}</td>
			<td class="qcmc-so-grid-ordered">${esc(format_schedule_qty(row.ordered_qty || 0))} ${esc(row.uom || "")}</td>
			<td><input class="form-control qcmc-so-grid-date" type="date" value="${esc(row.delivery_date || "")}" aria-label="${__("Delivery Date")}" ${row.date_locked || fully || reconciliation_required || lapsed ? "disabled" : ""}>${lock_note ? `<small class="text-muted">${esc(lock_note)}</small>` : ""}<div class="qcmc-so-grid-error" data-error-for="date" role="alert"></div></td>
			<td><input class="form-control qcmc-so-grid-qty" type="number" min="${esc(min_qty)}" step="${esc(Math.pow(10, -precision))}" value="${blank_new ? "" : esc(row.planned_qty ?? "")}" aria-label="${__("Planned Quantity")}" ${fully || reconciliation_required || lapsed ? "disabled" : ""}><div class="qcmc-so-grid-error" data-error-for="qty" role="alert"></div></td>
			<td class="qcmc-so-grid-scheduled">${esc(format_schedule_qty(row.total_scheduled_qty || 0))} ${esc(row.uom || "")}</td>
			<td class="qcmc-so-grid-committed">${esc(format_schedule_qty(allocated))} ${esc(row.uom || "")}</td>
			<td class="qcmc-so-grid-unscheduled">${esc(format_schedule_qty(row.unscheduled_qty || 0))} ${esc(row.uom || "")}</td>
			<td><textarea class="form-control qcmc-so-grid-remarks" rows="1" aria-label="${__("Reason / Remarks")}" ${fully || reconciliation_required || lapsed ? "disabled" : ""}>${esc(row.remarks || "")}</textarea><div class="qcmc-so-grid-error" data-error-for="remarks" role="alert"></div></td>
			<td class="qcmc-so-grid-remove"><button type="button" class="btn btn-default qcmc-so-grid-add-date" title="${__("Add another date for this item")}">+</button><button class="btn btn-default qcmc-so-grid-remove-row" type="button" aria-label="${__("Remove schedule row")}" title="${allocated || row.has_dn_history ? __("Rows linked to Delivery Notes are retained") : __("Remove row")}" ${remove_disabled ? "disabled" : ""}>×</button></td>
		</tr>`;
	};
	const table_html = () => `<div class="qcmc-so-schedule-grid">
		<div class="qcmc-so-grid-intro">${__("Sales Order")}: <strong>${esc(frm.doc.name || __("New Sales Order"))}</strong><span class="text-muted"> · ${__("Add one row for each planned delivery. Quantity totals and balances are shown on every row.")}</span></div>
		<div class="qcmc-so-grid-scroll"><table class="table table-bordered table-condensed qcmc-so-grid-table"><thead><tr>
			<th>${__("Item")}</th><th>${__("Ordered Qty")}</th><th>${__("Delivery Date")}</th><th>${__("Planned Qty")}</th>
			<th>${__("Total Scheduled")}</th><th>${__("Committed to DN")}</th><th>${__("Unscheduled Balance")}</th>
			<th>${__("Reason / Remarks")}</th><th class="qcmc-so-grid-remove-head">${__("Actions")}</th>
		</tr></thead><tbody class="qcmc-so-grid-rows">${initial.length ? initial.map(render_row).join("") : `<tr class="qcmc-so-grid-empty"><td colspan="9" class="text-muted">${__("No delivery schedules yet. Use Add Row to select an item if you need to stagger its delivery.")}</td></tr>`}</tbody></table></div>
		<button type="button" class="btn btn-default qcmc-so-grid-add">${__("Add Row")}</button>
		<div class="qcmc-so-grid-over text-danger" style="display:none">${__("Scheduled quantity exceeds the outstanding quantity for one or more items.")}</div>
		<p class="text-muted small qcmc-so-grid-help">${__("Removing a schedule returns its uncommitted quantity to the unscheduled balance. Quantities committed to Delivery Notes are retained.")}</p>
	</div>`;
	const read_rows = () => [...dialog.fields_dict.schedule_grid.$wrapper[0].querySelectorAll(".qcmc-so-grid-row")].map(el => {
		const select = el.querySelector(".qcmc-so-grid-item-select");
		const selected = select?.value || "";
		const qty = el.querySelector(".qcmc-so-grid-qty").value;
		return {
			schedule_name: el.dataset.scheduleName || null,
			sales_order_item: selected.startsWith("@") ? null : selected || el.dataset.salesOrderItem || null,
			item_idx: selected.startsWith("@") ? Number(selected.slice(1)) : Number(el.dataset.itemIdx || 0),
			delivery_date: el.querySelector(".qcmc-so-grid-date").value,
			planned_qty: qty === "" ? 0 : Number(qty),
			planned_qty_raw: qty,
			original_planned_qty: Number(el.dataset.originalPlanned || 0),
			original_remarks: el.dataset.originalRemarks || "",
			dn_committed_qty: Number(el.dataset.allocated || 0),
			remarks: el.querySelector(".qcmc-so-grid-remarks").value,
			has_dn_history: el.dataset.history === "1",
			item_locked: el.dataset.itemLocked === "1",
		};
	});
	const over_message = __("Scheduled total exceeds this item's outstanding quantity.");
	const update_metrics = () => {
		const rows = [...dialog.fields_dict.schedule_grid.$wrapper[0].querySelectorAll(".qcmc-so-grid-row")];
		const plans = read_rows();
		const totals = new Map();
		for (const row of rows) {
			const value = row.querySelector(".qcmc-so-grid-item-select")?.value || row.dataset.salesOrderItem || (row.dataset.itemIdx ? `@${row.dataset.itemIdx}` : "");
			if (!value) continue;
			const key = value;
			const ordered = Number(row.dataset.ordered || 0), delivered = Number(row.dataset.delivered || 0);
			const total = plans.filter(entry => item_key(entry) === key).reduce((sum, entry) => sum + (Number.isFinite(entry.planned_qty) ? entry.planned_qty : 0), 0);
			const prior = totals.get(key);
			if (!prior) totals.set(key, {ordered, delivered, total});
		}

		let over = false;
		for (const row of rows) {
			const value = row.querySelector(".qcmc-so-grid-item-select")?.value || row.dataset.salesOrderItem || (row.dataset.itemIdx ? `@${row.dataset.itemIdx}` : "");
			if (!value) continue;
			const metric = totals.get(value);
			const entry = plans[rows.indexOf(row)];
			const allocated = Number(row.dataset.allocated || 0);
			const available = Math.max(0, Number(entry?.planned_qty || 0) - allocated);
			const uom = row.dataset.uom || "";
			row.querySelector(".qcmc-so-grid-scheduled").textContent = `${format_schedule_qty(metric.total)} ${uom}`;
			row.querySelector(".qcmc-so-grid-committed").textContent = `${format_schedule_qty(allocated)} ${uom}`;
			row.querySelector(".qcmc-so-grid-unscheduled").textContent = `${format_schedule_qty(Math.max(0, metric.ordered - metric.delivered - metric.total))} ${uom}`;
			const complete = metric.total >= metric.ordered - metric.delivered;
			row.querySelector(".qcmc-so-grid-add-date").disabled = complete || row.dataset.lapsed === "1";
			row.querySelector(".qcmc-so-grid-remove-row").disabled = complete || row.dataset.removeLocked === "1";
			const item_over = metric.total > Math.max(0, metric.ordered - metric.delivered) + Math.pow(10, -Number(row.dataset.precision || 3)) / 2;
			if (item_over) {
				over = true;
				set_field_error(rows.indexOf(row), "qty", over_message);
			} else {
				const feedback = row.querySelector('[data-error-for="qty"]');
				if (feedback?.textContent === over_message) set_field_error(rows.indexOf(row), "qty", "");
			}
		}
		const allScheduled = items.every(item => {
			const key = item.sales_order_item || `@${item.idx}`;
			return (totals.get(key)?.total || 0) >= Number(item.ordered_qty) - Number(item.delivered_qty || 0);
		});
		dialog.fields_dict.schedule_grid.$wrapper.find(".qcmc-so-grid-add").prop("disabled", allScheduled);
		dialog.fields_dict.schedule_grid.$wrapper.find(".qcmc-so-grid-over").toggle(over);
		dialog.get_primary_btn().prop("disabled", over);
	};
	let validation_attempted = false;
	const set_field_error = (row_index, field, message) => {
		const row = dialog.fields_dict.schedule_grid.$wrapper[0].querySelectorAll(".qcmc-so-grid-row")[row_index];
		const control = row?.querySelector(`.qcmc-so-grid-${field === "item" ? "item-select" : field}`);
		const feedback = row?.querySelector(`[data-error-for="${field}"]`);
		if (!control || !feedback) return;
		control.classList.toggle("is-invalid", Boolean(message));
		control.setAttribute("aria-invalid", message ? "true" : "false");
		feedback.textContent = message || "";
		feedback.classList.toggle("is-visible", Boolean(message));
	};
	const clear_field_errors = row_index => ["item", "date", "qty", "remarks"].forEach(field => set_field_error(row_index, field, ""));
	const collect_and_validate = () => {
		const rows = read_rows();
		const entries = [];
		const totals = new Map();
		const indexes_by_item = new Map();
		const seen_dates = new Map();
		let invalid = false;
		rows.forEach((row, index) => {
			clear_field_errors(index);
			const has_values = Boolean(row.delivery_date || row.planned_qty_raw !== "" || row.remarks.trim());
			const new_item_selected = !row.item_locked && Boolean(row.sales_order_item || row.item_idx);
			const untouched_new_row = !row.schedule_name && !has_values && !new_item_selected;
			if (untouched_new_row) return;
			if (row.planned_qty === 0 && row.schedule_name && row.original_planned_qty === 0
				&& row.has_dn_history && row.remarks === row.original_remarks) return;

			let row_invalid = false;
			const field_error = (field, message) => {
				set_field_error(index, field, message);
				row_invalid = true;
			};
			if (!row.sales_order_item && !row.item_idx) field_error("item", __("Choose a Sales Order Item."));
			if (!row.delivery_date) field_error("date", __("Enter a delivery date."));
			else if (frm.doc.transaction_date && row.delivery_date < frm.doc.transaction_date) {
				field_error("date", __("Delivery date cannot be earlier than the Sales Order date."));
			}
			if (row.planned_qty_raw === "" || !Number.isFinite(row.planned_qty) || row.planned_qty <= 0) {
				field_error("qty", __("Enter a quantity greater than zero. Remove an uncommitted row to delete it."));
			} else if (row.planned_qty < row.dn_committed_qty) {
				field_error("qty", __("Quantity cannot be less than the draft Delivery Note commitment."));
			}
			if (!row.remarks.trim()) field_error("remarks", __("Enter Reason / Remarks."));

			const key = row.sales_order_item || (row.item_idx ? `@${row.item_idx}` : "");
			if (key && row.planned_qty > 0 && Number.isFinite(row.planned_qty)) {
				totals.set(key, (totals.get(key) || 0) + row.planned_qty);
				if (!indexes_by_item.has(key)) indexes_by_item.set(key, []);
				indexes_by_item.get(key).push(index);
			}
			if (key && row.delivery_date) {
				const date_key = `${key}|${row.delivery_date}`;
				if (seen_dates.has(date_key)) {
					field_error("date", __("Use one row per item and delivery date."));
					set_field_error(seen_dates.get(date_key), "date", __("Use one row per item and delivery date."));
					invalid = true;
				} else {
					seen_dates.set(date_key, index);
				}
			}
			if (!row_invalid) entries.push(row);
			else invalid = true;
		});

		for (const [key, total] of totals) {
			const item = items.find(x => (x.sales_order_item || `@${x.idx}`) === key);
			if (item && total > Number(item.remaining_qty) + Math.pow(10, -Number(item.precision || 3)) / 2) {
				for (const index of indexes_by_item.get(key) || []) {
					set_field_error(index, "qty", over_message);
				}
				invalid = true;
			}
		}
		return invalid ? null : entries;
	};
	const refresh_validation = () => {
		if (validation_attempted) collect_and_validate();
	};
	const persist_grid = async entries => {
		if (frm.is_new()) {
			if (!entries.length) throw new Error(__("Add at least one schedule before saving."));
			await frm.save();
			entries = entries.map(row => {
				const saved = frm.doc.items.find(item => item.idx === row.item_idx);
				if (!saved) throw new Error(__("Could not match a scheduled item after saving the Sales Order."));
				return {...row, sales_order_item: saved.name, item_idx: saved.idx};
			});
			const current = await frappe.call({method: "qcmc_logic.api.delivery_schedule_service.get_sales_order_schedule_grid", args: {sales_order: frm.doc.name}});
			if (current.exc) throw new Error(__("Could not refresh the Sales Order schedule grid."));
			grid = current.message;
		}
		const response = await frappe.call({
			method: "qcmc_logic.api.delivery_schedule_service.save_sales_order_schedule_grid",
			type: "POST",
			args: {sales_order: frm.doc.name, entries, expected_state: grid.state},
			freeze: true, freeze_message: __("Saving Sales Order delivery schedules..."),
		});
		if (response.exc) throw new Error(__("One or more schedule rows were not saved."));
		frappe.show_alert({message: __("Sales Order delivery schedules saved."), indicator: "green"});
		return response.message;
	};
	dialog = new frappe.ui.Dialog({
		title: __("Delivery Schedule — {0}", [frm.doc.name || __("New Sales Order")]),
		fields: [{fieldname: "schedule_grid", fieldtype: "HTML", options: table_html()}],
		primary_action_label: __("Save Schedules"),
		primary_action: async () => {
			validation_attempted = true;
			const entries = collect_and_validate();
			if (!entries) return;
			if (frm.is_new() && !entries.length) {
				frappe.msgprint(__("Add a schedule row before saving this new Sales Order."));
				return;
			}
			dialog.disable_primary_action();
			try {
				await persist_grid(entries);
				saved = true;
				dialog.hide();
				await frm.reload_doc();
			} catch (error) {
				// Frappe displays server-side permission, stale-state, and validation errors.
			} finally {
				if (dialog.$wrapper.is(":visible")) dialog.enable_primary_action();
			}
		},
	});
	const apply_styles = () => {
		const style_id = "qcmc-so-schedule-grid-styles";
		if (!document.getElementById(style_id)) {
			const style = document.createElement("style");
			style.id = style_id;
			style.textContent = `
				.qcmc-so-grid-table .is-invalid { border-color:#dc3545!important; box-shadow:0 0 0 .15rem rgba(220,53,69,.18)!important; }
				.qcmc-so-grid-error { display:none; color:#c92a2a; font-size:11px; line-height:1.25; margin-top:4px; max-width:220px; white-space:normal; }
				.qcmc-so-grid-error.is-visible { display:block; }
				.qcmc-so-grid-scroll { max-width:100%; overflow-x:auto; -webkit-overflow-scrolling:touch; }
				.qcmc-so-grid-table { min-width:1360px; margin-bottom:8px; }
				.qcmc-so-grid-table input[type=number] {text-align:right;}
				.qcmc-so-grid-table th { white-space:nowrap; vertical-align:middle!important; }
				.qcmc-so-grid-table td { vertical-align:middle!important; }
				.qcmc-so-grid-table input,.qcmc-so-grid-table select { min-width:112px; height:36px; }
				.qcmc-so-grid-table textarea { min-width:190px; min-height:36px; height:36px; resize:vertical; overflow-y:hidden; }
				.qcmc-so-grid-item { min-width:145px; }
				.qcmc-so-grid-item small { display:block; color:var(--text-muted,#687178); }
				.qcmc-so-grid-ordered,.qcmc-so-grid-scheduled,.qcmc-so-grid-committed,.qcmc-so-grid-unscheduled { white-space:nowrap; text-align:right; }
				.qcmc-so-grid-remove-head,.qcmc-so-grid-remove { width:58px; min-width:58px; text-align:center; }
				.qcmc-so-grid-remove .btn { width:38px;height:36px;font-size:20px;line-height:1; }
				.qcmc-so-grid-help { margin:8px 0 0; }
				@media(max-width:767px){.qcmc-so-grid-dialog{width:calc(100vw - 16px)!important;max-width:none!important;margin:8px!important}.qcmc-so-grid-table{min-width:1360px}.qcmc-so-grid-table input,.qcmc-so-grid-table select,.qcmc-so-grid-remove .btn{height:44px}.qcmc-so-grid-table textarea{min-height:44px;height:44px}.qcmc-so-grid-dialog .modal-footer{position:sticky;bottom:0;background:var(--card-bg,#fff);z-index:2}}
			`;
			document.head.appendChild(style);
		}
		dialog.$wrapper.find(".modal-dialog").addClass("qcmc-so-grid-dialog").css({width: "min(1500px, calc(100vw - 24px))", maxWidth: "none"});
	};
	dialog.show();
	apply_styles();
	const $wrapper = dialog.fields_dict.schedule_grid.$wrapper;
	const original_rows = JSON.stringify(read_rows());
	let discard_confirmed = false;
	dialog.$wrapper.on("hide.bs.modal.schedule", event => {
		if (event.target !== dialog.$wrapper[0] || saved || discard_confirmed) return;
		if (JSON.stringify(read_rows()) === original_rows) return;
		event.preventDefault();
		frappe.confirm(__("Discard your unsaved schedule changes?"), () => {
			discard_confirmed = true;
			dialog.hide();
		});
	});
	const append_row = row => {
		$wrapper.find(".qcmc-so-grid-empty").remove();
		$wrapper.find(".qcmc-so-grid-rows").append(render_row(row));
	};
	$wrapper.on("input", ".qcmc-so-grid-qty, .qcmc-so-grid-remarks", event => {
		if (event.target.matches(".qcmc-so-grid-remarks")) {
			event.target.style.height = "auto";
			event.target.style.height = `${Math.min(Math.max(event.target.scrollHeight, 36), 120)}px`;
		}
		update_metrics();
		refresh_validation();
	});
	$wrapper.on("change", ".qcmc-so-grid-item-select", event => {
		const row = event.currentTarget.closest(".qcmc-so-grid-row");
		const selected = event.currentTarget.value;
		if (!selected) {
			row.dataset.salesOrderItem = "";
			row.dataset.itemIdx = "";
			row.dataset.ordered = "0";
			row.dataset.delivered = "0";
			row.querySelector(".qcmc-so-grid-ordered").textContent = "";
			update_metrics(); refresh_validation(); return;
		}
		const item = items.find(x => (x.sales_order_item || `@${x.idx}`) === selected);
		if (!item) { update_metrics(); refresh_validation(); return; }
		row.dataset.salesOrderItem = item.sales_order_item || "";
		row.dataset.itemIdx = item.idx;
		row.dataset.ordered = item.ordered_qty;
		row.dataset.delivered = item.delivered_qty;
		row.dataset.uom = item.uom || "";
		row.dataset.precision = item.precision || 3;
		row.querySelector(".qcmc-so-grid-ordered").textContent = `${format_schedule_qty(item.ordered_qty)} ${item.uom || ""}`;
		const qty = row.querySelector(".qcmc-so-grid-qty");
		qty.step = Math.pow(10, -(item.precision || 3));
		qty.min = Math.pow(10, -(item.precision || 3));
		update_metrics();
		refresh_validation();
	});
	$wrapper.on("change", ".qcmc-so-grid-date", event => {
		const source = event.currentTarget.closest(".qcmc-so-grid-row"), selected = event.currentTarget.value;
		const item = source.querySelector(".qcmc-so-grid-item-select")?.value || source.dataset.salesOrderItem || (source.dataset.itemIdx ? `@${source.dataset.itemIdx}` : "");
		const target = [...$wrapper[0].querySelectorAll(".qcmc-so-grid-row")].find(row => row !== source
			&& (row.querySelector(".qcmc-so-grid-item-select")?.value || row.dataset.salesOrderItem || (row.dataset.itemIdx ? `@${row.dataset.itemIdx}` : "")) === item
			&& row.querySelector(".qcmc-so-grid-date").value === selected);
		if (!target || !selected) { update_metrics(); refresh_validation(); return; }
		if (is_fully_committed({planned_qty: target.querySelector(".qcmc-so-grid-qty").value, dn_committed_qty: target.dataset.allocated})) {
			frappe.show_alert({message: __("Choose a new delivery date; the destination row is fully committed."), indicator: "orange"});
			event.currentTarget.value = source.dataset.originalDate;
			update_metrics(); refresh_validation(); return;
		}
		const source_qty = Number(source.querySelector(".qcmc-so-grid-qty").value || 0);
		const allocated = Number(source.dataset.allocated || 0);
		const free = Math.max(0, source_qty - allocated);
		const target_qty = target.querySelector(".qcmc-so-grid-qty");
		target_qty.value = String(Number(target_qty.value || 0) + free);
		const source_remarks = source.querySelector(".qcmc-so-grid-remarks").value;
		if (source_remarks) {
			const notes = target.querySelector(".qcmc-so-grid-remarks");
			notes.value = [...new Set([notes.value.trim(), source_remarks.trim()].filter(Boolean))].join("\n");
		}
		frappe.show_alert({message: __("Combined quantity on {0}: {1}", [selected, format_schedule_qty(Number(target_qty.value))]), indicator: "blue"});
		if (allocated > 0) {
			source.querySelector(".qcmc-so-grid-date").value = source.dataset.originalDate;
			source.querySelector(".qcmc-so-grid-qty").value = String(allocated);
		} else {
			source.remove();
		}
		update_metrics();
		refresh_validation();
	});
	$wrapper.on("click", ".qcmc-so-grid-add-date", event => {
		const source = event.currentTarget.closest(".qcmc-so-grid-row");
		const index = [...$wrapper[0].querySelectorAll(".qcmc-so-grid-row")].indexOf(source);
		const entry = read_rows()[index];
		const item = items.find(item => item.sales_order_item === entry.sales_order_item || item.idx === entry.item_idx);
		if (!item) return;
		append_row({...item, schedule_name: null, item_locked: true, delivery_date: "", planned_qty: "",
			dn_committed_qty: 0, has_dn_history: false, date_locked: false, remarks: ""});
		$wrapper.find(".qcmc-so-grid-row").last().find(".qcmc-so-grid-date").trigger("focus");
		update_metrics();
	});

	$wrapper.on("click", ".qcmc-so-grid-add", () => append_row({schedule_name:null,sales_order_item:null,item_idx:null,item_code:"",item_name:"",uom:"",ordered_qty:0,delivered_qty:0,remaining_qty:0,precision:3,delivery_date:"",planned_qty:"",dn_committed_qty:0,editable_qty:0,total_scheduled_qty:0,unscheduled_qty:0,has_dn_history:false,date_locked:false,remarks:"",item_locked:false}));
	$wrapper.on("click", ".qcmc-so-grid-remove-row", event => {
		$(event.currentTarget).closest(".qcmc-so-grid-row").remove();
		if (!$wrapper.find(".qcmc-so-grid-row").length) {
			$wrapper.find(".qcmc-so-grid-rows").append(`<tr class="qcmc-so-grid-empty"><td colspan="9" class="text-muted">${__("No delivery schedules yet. Use Add Row to select an item if you need to stagger its delivery.")}</td></tr>`);
		}
		update_metrics(); refresh_validation();
	});
	update_metrics();
}
function format_schedule_qty(value) {
	return format_number(value, null, 3).replace(/([.,]\d*?[1-9])0+$|[.,]0+$/, "$1");
}
