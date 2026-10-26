frappe.ui.form.on("Weekly Production Plan", {
	setup(frm) {
		frm.set_query("section", () => ({
			filters: { company: frm.doc.company || "" },
		}));
		for (const fieldname of ["second_item", "third_item"]) {
			frm.set_query(fieldname, "machine_schedule", (_doc, cdt, cdn) => ({
				query: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_machine_fg_items",
				filters: { machine: frappe.get_doc(cdt, cdn).machine },
			}));
		}
		for (const tableField of ["item_1_schedule", "item_2_schedule"]) {
			frm.set_query("product_code", tableField, (_doc, cdt, cdn) => ({
				query: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_machine_fg_items",
				filters: { machine: frappe.get_doc(cdt, cdn).machine },
			}));
		}
		frm.set_query("roll_code", "extrusion_item_schedule", (_doc, cdt, cdn) => ({
			query: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_machine_fg_items",
			filters: { machine: frappe.get_doc(cdt, cdn).machine },
		}));
	},

	refresh(frm) {
		set_grid_read_only(frm);
		sync_production_plan_import_controls(frm);
	},

	async company(frm) {
		await frm.set_value("section", null);
		clear_generated_schedule(frm);
	},

	async start_date(frm) {
		if (frm.doc.start_date && frappe.datetime.str_to_obj(frm.doc.start_date).getDay() !== 1) {
			frappe.msgprint({
				title: __("Invalid Start Date"),
				message: __("Start Date must be a Monday."),
				indicator: "red",
			});
			await frm.set_value("start_date", null);
			return;
		}
		refresh_machine_schedule(frm);
	},

	section(frm) {
		sync_production_plan_import_controls(frm);
		refresh_machine_schedule(frm);
	},
});

function sync_production_plan_import_controls(frm) {
	const importButtonLabel = __("Import Production Plan");
	const clearButtonLabel = __("Clear Imported Items");
	const canImport = frm.doc.docstatus === 0 && !is_extrusion_section(frm.doc.section);
	frm.toggle_display("production_plan_file", false);
	frm.remove_custom_button(importButtonLabel);
	frm.remove_custom_button(clearButtonLabel);
	if (canImport) {
		frm.add_custom_button(importButtonLabel, () => show_production_plan_import_dialog(frm));
		frm.add_custom_button(clearButtonLabel, () => clear_imported_production_items(frm));
	}
}

function clear_imported_production_items(frm) {
	const allFg1Rows = frm.doc.item_1_schedule || [];
	const taggedRows = allFg1Rows.filter((row) => cint(row.imported_from_excel));
	const rowsToClear = taggedRows.length ? taggedRows : allFg1Rows;

	if (!rowsToClear.length) {
		frm.fields_dict.import_results?.$wrapper?.empty();
		frappe.show_alert({ message: __("There are no imported items to clear."), indicator: "blue" });
		return;
	}

	const message = taggedRows.length
		? __("Remove {0} Excel-imported schedule row(s)?", [rowsToClear.length])
		: __("This older plan has no import tags. Remove all {0} existing FG1 row(s)?", [rowsToClear.length]);
	frappe.confirm(message, () => {
		for (const row of rowsToClear) {
			frappe.model.clear_doc(row.doctype, row.name);
		}
		frm.refresh_field("item_1_schedule");
		frm.fields_dict.import_results?.$wrapper?.empty();
		frm.dirty();
		frappe.show_alert({ message: __("Imported schedule rows cleared."), indicator: "green" });
	});
}

frappe.ui.form.on("Weekly Production Plan Detail", {
	form_render(frm, cdt, cdn) {
		set_weekly_plan_row_editor_size(frm, cdn);
		render_possible_sales_orders(frm, cdt, cdn);
	},
});

function set_weekly_plan_row_editor_size(frm, cdn) {
	const gridRow = frm.fields_dict.machine_schedule?.grid?.grid_rows_by_docname?.[cdn];
	const formWrapper = gridRow?.grid_form?.wrapper;
	const wrapper = formWrapper?.jquery ? formWrapper[0] : formWrapper;
	const modal = wrapper?.closest?.(".modal") || Array.from(document.querySelectorAll(".modal"))
		.filter((element) => element.offsetParent !== null)
		.reverse()
		.find((element) => element.textContent.includes(__("Editing Row")));
	const visibleDialogs = Array.from(document.querySelectorAll(".modal-dialog")).filter((element) => element.offsetParent !== null);
	const modalDialog = wrapper?.closest?.(".modal-dialog") || modal?.querySelector?.(".modal-dialog") || visibleDialogs[visibleDialogs.length - 1];
	if (!modalDialog) return;

	modal?.classList.add("qcmc-weekly-production-plan-row-modal");
	modalDialog.classList.add("qcmc-weekly-production-plan-row-editor");
	if (document.getElementById("qcmc-weekly-production-plan-row-editor-style")) return;
	const style = document.createElement("style");
	style.id = "qcmc-weekly-production-plan-row-editor-style";
	style.textContent = `
		.qcmc-weekly-production-plan-row-modal {
			position: fixed !important;
			inset: 0 !important;
			width: 100vw !important;
			height: 100vh !important;
			height: 100dvh !important;
			padding: 0 !important;
			overflow: hidden !important;
		}
		.qcmc-weekly-production-plan-row-editor {
			position: absolute !important;
			inset: 0 !important;
			width: 100% !important;
			max-width: none !important;
			height: 100% !important;
			margin: 0 !important;
			padding: 0 !important;
		}
		.qcmc-weekly-production-plan-row-editor .modal-content {
			display: flex;
			flex-direction: column;
			height: 100%;
			max-height: 100%;
			border-radius: 0;
		}
		.qcmc-weekly-production-plan-row-editor .modal-body {
			flex: 1 1 auto;
			min-height: 0;
			overflow: auto;
		}
		.qcmc-weekly-production-plan-row-editor .scheduled-items-editor,
		.qcmc-weekly-production-plan-row-editor .scheduled-items-editor .table-responsive {
			width: 200%;
		}
		.qcmc-scheduled-resizable-table { table-layout: fixed; min-width: 100%; }
		.qcmc-scheduled-resizable-table th,
		.qcmc-scheduled-resizable-table td {
			white-space: normal !important;
			overflow-wrap: anywhere;
			word-break: normal;
		}
		.qcmc-scheduled-resizable-table th { position: relative; }
		.qcmc-scheduled-resizable-table th { padding-inline-end: 13px; }
		.qcmc-scheduled-column-handle { position: absolute; z-index: 2; inset-block: 0; inset-inline-end: -1px; width: 12px; cursor: col-resize; touch-action: none; }
		.qcmc-scheduled-column-handle::after { content: ""; position: absolute; inset-block: 15%; inset-inline-start: 5px; width: 2px; border-radius: 2px; background: var(--border-color, #c8cdd2); }
		.qcmc-scheduled-column-handle:hover::after, .qcmc-scheduled-column-handle:focus-visible::after { background: var(--primary, #5387ed); }
		.qcmc-scheduled-column-resizing, .qcmc-scheduled-column-resizing * { cursor: col-resize !important; user-select: none !important; }
	`;
	document.head.appendChild(style);
}

const productionItemHandlers = {
	product_code(frm, cdt, cdn) {
		populate_production_item(frm, cdt, cdn);
	},
	machine(frm, cdt, cdn) {
		populate_production_item(frm, cdt, cdn);
	},
	paid_hrs(frm, cdt, cdn) {
		calculate_plan_hours(frm, cdt, cdn);
	},
	vos(frm, cdt, cdn) {
		calculate_plan_hours(frm, cdt, cdn);
	},
	cm_co(frm, cdt, cdn) {
		calculate_plan_hours(frm, cdt, cdn);
	},
	stab(frm, cdt, cdn) {
		calculate_plan_hours(frm, cdt, cdn);
	},
	plan_hrs(frm, cdt, cdn) {
		calculate_daily_volume(frm, cdt, cdn);
	},
	soph(frm, cdt, cdn) {
		calculate_daily_volume(frm, cdt, cdn);
	},
	std_weight_gm(frm, cdt, cdn) {
		calculate_daily_volume(frm, cdt, cdn);
	},
	fg1_product_code(frm, cdt, cdn) {
		calculate_daily_volume(frm, cdt, cdn);
	},
	factor_rate(frm, cdt, cdn) {
		calculate_daily_volume(frm, cdt, cdn);
	},
	f_rate(frm, cdt, cdn) {
		calculate_daily_volume(frm, cdt, cdn);
	},
	cycle_time(frm, cdt, cdn) {
		const row = frappe.get_doc(cdt, cdn);
		if (row.doctype === "Weekly Production Plan Item") update_linked_secondary_rows(frm, row);
	},
};

frappe.ui.form.on("Weekly Production Plan Item", productionItemHandlers);
frappe.ui.form.on("Weekly Production Plan Secondary Item", productionItemHandlers);

frappe.ui.form.on("Weekly Production Plan Extrusion Item", {
	roll_code(frm, cdt, cdn) {
		populate_extrusion_item(frm, cdt, cdn);
	},
	machine(frm, cdt, cdn) {
		populate_extrusion_item(frm, cdt, cdn);
	},
	paid_time: calculate_extrusion_output,
	vos: calculate_extrusion_output,
	change_over: calculate_extrusion_output,
	stabilization: calculate_extrusion_output,
});

function render_possible_sales_orders(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const gridRow = frm.fields_dict.machine_schedule?.grid?.grid_rows_by_docname?.[cdn];
	const wrapper = gridRow?.grid_form?.fields_dict?.possible_sales_orders?.$wrapper;
	if (!wrapper) return;

	wrapper.html(scheduled_items_html(frm, row));
	enhance_scheduled_item_tables(wrapper);
	bind_scheduled_item_actions(wrapper, frm, row);
}

function enhance_scheduled_item_tables(wrapper) {
	const root = wrapper?.[0] || wrapper;
	if (!root?.querySelectorAll) return;
	root.querySelectorAll("table[data-resize-key]").forEach((table) => {
		const headers = Array.from(table.querySelectorAll("thead th"));
		if (!headers.length) return;
		let colgroup = table.querySelector("colgroup");
		if (!colgroup) {
			colgroup = document.createElement("colgroup");
			headers.forEach(() => colgroup.appendChild(document.createElement("col")));
			table.insertBefore(colgroup, table.firstChild);
		}
		const cols = Array.from(colgroup.children);
		if (cols.length !== headers.length) return;
		const key = `qcmc-weekly-plan-columns:${frappe.session.user}:${table.dataset.resizeKey}`;
		let widths = {};
		try { widths = JSON.parse(localStorage.getItem(key) || "{}"); } catch (error) { /* Ignore unavailable browser storage. */ }
		headers.forEach((header, index) => {
			const measured = header.getBoundingClientRect().width || 100;
			const width = Math.max(60, Number(widths[index]) || measured);
			cols[index].style.width = `${width}px`;
		});
		const updateTableWidth = () => {
			table.style.width = `${cols.reduce((total, col) => total + col.getBoundingClientRect().width, 0)}px`;
		};
		updateTableWidth();
		headers.forEach((header, index) => {
			if (header.querySelector(".qcmc-scheduled-column-handle")) return;
			const handle = document.createElement("span");
			handle.className = "qcmc-scheduled-column-handle";
			handle.tabIndex = 0;
			handle.setAttribute("role", "separator");
			handle.setAttribute("aria-orientation", "vertical");
			handle.setAttribute("aria-label", __("Resize {0} column", [header.textContent.trim()]));
			header.appendChild(handle);
			handle.addEventListener("pointerdown", (event) => {
				event.preventDefault();
				const startX = event.clientX;
				const startWidth = cols[index].getBoundingClientRect().width || header.getBoundingClientRect().width;
				const move = (moveEvent) => {
					const width = Math.max(60, startWidth + moveEvent.clientX - startX);
					cols[index].style.width = `${width}px`;
					updateTableWidth();
				};
				const finish = () => {
					document.body.classList.remove("qcmc-scheduled-column-resizing");
					window.removeEventListener("pointermove", move);
					window.removeEventListener("pointerup", finish);
					widths[index] = Math.round(cols[index].getBoundingClientRect().width);
					try { localStorage.setItem(key, JSON.stringify(widths)); } catch (error) { /* Resizing still works without persistence. */ }
				};
				document.body.classList.add("qcmc-scheduled-column-resizing");
				window.addEventListener("pointermove", move);
				window.addEventListener("pointerup", finish, {once: true});
			});
		});
	});
}

function rows_for_schedule(frm, tableField, scheduleRow) {
	return (frm.doc[tableField] || []).filter(
		(row) => row.machine === scheduleRow.machine && row.plan_date === scheduleRow.plan_date,
	);
}

function format_plan_number(value, precision = 2) {
	return flt(value).toFixed(precision);
}

function schedule_hours_summary_html(frm, scheduleRow, extrusion = false) {
	const totalPaidTime = 24;
	const rows = rows_for_schedule(
		frm,
		extrusion ? "extrusion_item_schedule" : "item_1_schedule",
		scheduleRow,
	);
	const totals = rows.reduce((result, row) => {
		result.plannedPaidHours += flt(extrusion ? row.paid_time : row.paid_hrs);
		result.vos += flt(row.vos);
		result.cmCo += flt(extrusion ? row.change_over : row.cm_co);
		result.stab += flt(extrusion ? row.stabilization : row.stab);
		return result;
	}, { plannedPaidHours: 0, vos: 0, cmCo: 0, stab: 0 });
	const remaining = totalPaidTime - totals.plannedPaidHours;
	const cells = [
		[__("Total Paid Time Hrs"), totalPaidTime],
		[__("Total Planned VOS Hrs"), totals.vos],
		[__("Total CM/CO Hrs"), totals.cmCo],
		[__("Total Stabilization Hrs"), totals.stab],
		[__("Remaining Paid Hrs"), remaining],
	];

	return `<div class="table-responsive" style="margin-top: 10px">
		<table class="table table-bordered table-condensed" style="width: auto; min-width: 680px; margin-bottom: 8px; white-space: nowrap">
			<thead><tr>${cells.map(([label]) => `<th>${label}</th>`).join("")}</tr></thead>
			<tbody><tr style="background-color: #fffec4; font-weight: 600">${cells.map(([, value]) => `<td>${format_plan_number(value)}</td>`).join("")}</tr></tbody>
		</table>
	</div>`;
}

function scheduled_items_html(frm, scheduleRow) {
	const escape = frappe.utils.escape_html;
	const hasFg1Item = rows_for_schedule(frm, "item_1_schedule", scheduleRow)
		.some((row) => row.product_code);
	const renderRows = (tableField, secondary = false) => {
		const rows = rows_for_schedule(frm, tableField, scheduleRow);
		if (!rows.length) return `<tr><td colspan="${secondary ? 11 : 18}" class="text-muted text-center">${__("No items added.")}</td></tr>`;
		return rows.map((row) => `
			<tr>
				${secondary ? `<td>${escape(row.fg1_product_code || "")}</td>` : ""}<td>${escape(row.product_code || "")}</td><td>${escape(row.product_description || "")}</td>
				<td>${row.cavs || 0}</td>
				${secondary ? "" : `<td>${format_plan_number(row.paid_hrs)}</td><td>${format_plan_number(row.vos)}</td><td>${format_plan_number(row.cm_co)}</td><td>${format_plan_number(row.stab)}</td><td>${format_plan_number(row.plan_hrs)}</td>`}
				<td>${format_plan_number(row.soph)}</td><td>${format_plan_number(row.std_weight_gm, 4)}</td><td>${format_plan_number(row.daily_volume_qty)}</td><td>${format_plan_number(row.daily_volume_kgs)}</td>
				<td>${format_plan_number(secondary ? row.factor_rate : row.f_rate)}</td><td>${format_plan_number(row.cycle_time, 4)}</td>
				${secondary ? "" : `<td>${escape(row.remarks || "")}</td><td>${escape(row.mat_type || "")}</td><td>${format_plan_number(row.steam_regmt)}</td>`}
				<td class="text-nowrap"><button class="btn btn-xs btn-default js-edit-scheduled-item" data-table="${tableField}" data-name="${row.name}">${__("Edit")}</button> <button class="btn btn-xs btn-default js-delete-scheduled-item" data-table="${tableField}" data-name="${row.name}">${__("Remove")}</button></td>
			</tr>`).join("");
	};
	const table = (title, tableField, secondary = false) => {
		const addDisabled = secondary && !hasFg1Item;
		const disabledAttributes = addDisabled
			? ` disabled aria-disabled="true" title="${__("Add at least one FG 1 item first.")}"`
			: "";
		return `
		<div style="margin-top: 15px"><div class="flex justify-between align-center"><strong>${__(title)}</strong><button class="btn btn-xs btn-primary js-add-scheduled-item" data-table="${tableField}"${disabledAttributes}>${__("Add Row")}</button></div>
		<div class="table-responsive"><table class="table table-bordered table-condensed qcmc-scheduled-resizable-table" data-resize-key="${tableField}" style="margin-top: 6px; white-space: nowrap"><thead><tr>
		${secondary ? `<th>${__("FG 1 Item")}</th>` : ""}<th>${__("Prodcode")}</th><th>${__("Proddesc")}</th><th>${__("Cavs")}</th>
		${secondary ? "" : `<th>${__("PaidHrs")}</th><th>${__("VOS")}</th><th>${__("CM/CO")}</th><th>${__("Stab")}</th><th>${__("PlanHrs")}</th>`}
		<th>${__("SOPH")}</th><th>${__("StdWt(gm)")}</th><th>${__("Daily Vol Qty")}</th><th>${__("DailyVolKgs")}</th><th>${__(secondary ? "FactorRate" : "F.Rate")}</th><th>${__(secondary ? "CycleTime" : "C.T.")}</th>
		${secondary ? "" : `<th>${__("Remarks")}</th><th>${__("MatType")}</th><th>${__("SteamRegmt")}</th>`}<th>${__("Action")}</th>
		</tr></thead><tbody>${renderRows(tableField, secondary)}</tbody></table></div></div>`;
	};
	if (is_extrusion_section(frm.doc.section)) {
		return extrusion_items_html(frm, scheduleRow);
	}
	return `<div class="scheduled-items-editor">${schedule_hours_summary_html(frm, scheduleRow)}<h6 style="margin-top: 18px">${__("Scheduled FG Items for {0} on {1}", [scheduleRow.machine, frappe.datetime.str_to_user(scheduleRow.plan_date)])}</h6>${table("FG 1", "item_1_schedule")}${table("FG 2", "item_2_schedule", true)}</div>`;
}

function extrusion_items_html(frm, scheduleRow) {
	const escape = frappe.utils.escape_html;
	const rows = rows_for_schedule(frm, "extrusion_item_schedule", scheduleRow);
	const body = rows.length ? rows.map((row) => `<tr>
		<td>${escape(row.roll_code || "")}</td><td>${format_plan_number(row.std_weight_kg, 4)}</td><td>${escape(row.roll_description || "")}</td>
		<td>${escape(row.used_for || "")}</td><td>${format_plan_number(row.paid_time)}</td><td>${format_plan_number(row.vos)}</td><td>${format_plan_number(row.change_over)}</td>
		<td>${format_plan_number(row.stabilization)}</td><td>${format_plan_number(row.plan_hours)}</td><td>${format_plan_number(row.trim_percent)}</td><td>${format_plan_number(row.soph)}</td>
		<td>${format_plan_number(row.number_of_kgs)}</td><td>${format_plan_number(row.number_of_rolls)}</td><td>${escape(row.remarks || "")}</td><td>${escape(row.color || "")}</td>
		<td>${format_plan_number(row.virgin)}</td><td>${format_plan_number(row.reco)}</td><td>${format_plan_number(row.colorant)}</td><td>${format_plan_number(row.additives)}</td>
		<td class="text-nowrap"><button class="btn btn-xs btn-default js-edit-scheduled-item" data-table="extrusion_item_schedule" data-name="${row.name}">${__("Edit")}</button> <button class="btn btn-xs btn-default js-delete-scheduled-item" data-table="extrusion_item_schedule" data-name="${row.name}">${__("Remove")}</button></td>
	</tr>`).join("") : `<tr><td colspan="20" class="text-muted text-center">${__("No extrusion items added.")}</td></tr>`;
	return `<div class="scheduled-items-editor">${schedule_hours_summary_html(frm, scheduleRow, true)}<h6 style="margin-top: 18px">${__("Extrusion Items for {0} on {1}", [scheduleRow.machine, frappe.datetime.str_to_user(scheduleRow.plan_date)])}</h6>
		<div class="flex justify-between align-center"><strong>${__("Extrusion Item List")}</strong><button class="btn btn-xs btn-primary js-add-scheduled-item" data-table="extrusion_item_schedule">${__("Add Row")}</button></div>
		<div class="table-responsive"><table class="table table-bordered table-condensed qcmc-scheduled-resizable-table" data-resize-key="extrusion_item_schedule" style="margin-top: 6px; white-space: nowrap"><thead><tr>
		<th>${__("Rollcode")}</th><th>${__("StdWt")}</th><th>${__("Rolldesc")}</th><th>${__("Used For")}</th><th>${__("PaidTim")}</th><th>${__("VOS")}</th><th>${__("C.O.")}</th><th>${__("Stab")}</th><th>${__("PlanHrs")}</th><th>${__("% Trim")}</th><th>${__("SOPH")}</th><th>${__("NoofKgs")}</th><th>${__("NoofRolls")}</th><th>${__("Remarks")}</th><th>${__("Color")}</th><th>${__("Virgin")}</th><th>${__("Reco")}</th><th>${__("Colorant")}</th><th>${__("Additives")}</th><th>${__("Action")}</th>
		</tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function bind_scheduled_item_actions(wrapper, frm, scheduleRow) {
	wrapper.find(".js-add-scheduled-item").on("click", function() {
		open_scheduled_item_dialog(frm, scheduleRow, this.dataset.table);
	});
	wrapper.find(".js-edit-scheduled-item").on("click", function() {
		open_scheduled_item_dialog(frm, scheduleRow, this.dataset.table, this.dataset.name);
	});
	wrapper.find(".js-delete-scheduled-item").on("click", function() {
		const deletedRow = locals[frm.fields_dict[this.dataset.table].df.options]?.[this.dataset.name];
		if (this.dataset.table === "item_1_schedule" && deletedRow) {
			for (const secondaryRow of rows_for_schedule(frm, "item_2_schedule", scheduleRow)) {
				if (secondaryRow.fg1_product_code === deletedRow.product_code) {
					frappe.model.clear_doc(secondaryRow.doctype, secondaryRow.name);
				}
			}
			frm.refresh_field("item_2_schedule");
		}
		frappe.model.clear_doc(frm.fields_dict[this.dataset.table].df.options, this.dataset.name);
		frm.refresh_field(this.dataset.table);
		frm.dirty();
		render_possible_sales_orders(frm, scheduleRow.doctype, scheduleRow.name);
	});
}

function open_scheduled_item_dialog(frm, scheduleRow, tableField, rowName = null, initialProduct = null) {
	if (tableField === "extrusion_item_schedule") {
		open_extrusion_item_dialog(frm, scheduleRow, rowName, initialProduct);
		return;
	}
	const secondary = tableField === "item_2_schedule";
	const existing = rowName ? locals[frm.fields_dict[tableField].df.options]?.[rowName] : null;
	const fg1Rows = rows_for_schedule(frm, "item_1_schedule", scheduleRow);
	if (secondary && !existing && !fg1Rows.some((row) => row.product_code)) {
		frappe.show_alert({
			message: __("Add at least one FG 1 item before adding an FG 2 item."),
			indicator: "orange",
		});
		return;
	}
	const defaultFg1Product = existing?.fg1_product_code || (fg1Rows.length === 1 ? fg1Rows[0].product_code : null);
	let dialog;
	const numeric = (fieldname, label, read_only = false, defaultValue = 0, precision = 2) => ({ fieldname, label, fieldtype: "Float", read_only, default: existing?.[fieldname] ?? defaultValue, precision });
	const fields = [
		{ fieldname: "machine", label: __("Machine"), fieldtype: "Link", options: "Workstation", read_only: 1, default: scheduleRow.machine },
		{ fieldname: "plan_date", label: __("Plan Date"), fieldtype: "Date", read_only: 1, default: scheduleRow.plan_date },
		...(secondary ? [{ fieldname: "fg1_product_code", label: __("FG 1 Item"), fieldtype: "Link", options: "Item", reqd: 1, default: defaultFg1Product, get_query: () => ({ filters: { name: ["in", fg1Rows.map((row) => row.product_code)] } }) }] : []),
		{ fieldname: "product_code", label: __("Prodcode"), fieldtype: "Link", options: "Item", reqd: 1, default: existing?.product_code || initialProduct, get_query: () => ({ query: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_machine_fg_items", filters: { machine: scheduleRow.machine } }), onchange: () => load_dialog_product_details(dialog, scheduleRow.machine, secondary, frm, scheduleRow) },
		{ fieldname: "product_description", label: __("Proddesc"), fieldtype: "Data", read_only: 1, default: existing?.product_description },
		{ fieldname: "cavs", label: __("Cavs"), fieldtype: "Int", read_only: 1, default: existing?.cavs },
	];
	if (!secondary) fields.push(numeric("paid_hrs", "PaidHrs", false, 24), numeric("vos", "VOS"), numeric("cm_co", "CM/CO"), numeric("stab", "Stab"), numeric("plan_hrs", "PlanHrs", true, 24));
	fields.push(numeric("soph", "SOPH", true), numeric("std_weight_gm", "StdWt(gm)", true, 0, 4), numeric("daily_volume_qty", "Daily Vol Qty", true), numeric("daily_volume_kgs", "DailyVolKgs", true), numeric(secondary ? "factor_rate" : "f_rate", secondary ? "FactorRate" : "F.Rate", secondary, 100), numeric("cycle_time", secondary ? "CycleTime" : "C.T.", secondary, 0, 4));
	if (!secondary) fields.push(
		{ fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text", default: existing?.remarks },
		{ fieldname: "mat_type", label: __("MatType"), fieldtype: "Data", default: existing?.mat_type },
		numeric("steam_regmt", "SteamRegmt"),
	);
	dialog = new frappe.ui.Dialog({ title: __(rowName ? "Edit {0}" : "Add {0}", [secondary ? "FG 2" : "FG 1"]), fields, primary_action_label: __("Save Row"), primary_action(values) {
		const target = existing || frm.add_child(tableField);
		const previousProductCode = target.product_code;
		Object.assign(target, values, { machine: scheduleRow.machine, plan_date: scheduleRow.plan_date });
		if (!secondary && previousProductCode && previousProductCode !== target.product_code) {
			for (const secondaryRow of rows_for_schedule(frm, "item_2_schedule", scheduleRow)) {
				if (secondaryRow.fg1_product_code === previousProductCode) secondaryRow.fg1_product_code = target.product_code;
			}
		}
		if (!secondary) update_linked_secondary_rows(frm, target);
		frm.refresh_field(tableField);
		frm.dirty();
		dialog.hide();
		keep_schedule_detail_open(frm, scheduleRow);
	} });
	for (const fieldname of ["paid_hrs", "vos", "cm_co", "stab"]) if (dialog.fields_dict[fieldname]) dialog.fields_dict[fieldname].df.onchange = () => calculate_dialog_plan_hours(dialog);
	if (dialog.fields_dict.fg1_product_code) dialog.fields_dict.fg1_product_code.df.onchange = () => calculate_dialog_volume(dialog, true, frm, scheduleRow);
	dialog.show();
	if (secondary) calculate_dialog_volume(dialog, true, frm, scheduleRow);
	else calculate_dialog_plan_hours(dialog);
	if (initialProduct) load_dialog_product_details(dialog, scheduleRow.machine, secondary, frm, scheduleRow);
}

function open_extrusion_item_dialog(frm, scheduleRow, rowName = null, initialProduct = null) {
	const tableField = "extrusion_item_schedule";
	const existing = rowName ? locals[frm.fields_dict[tableField].df.options]?.[rowName] : null;
	let dialog;
	const numeric = (fieldname, label, read_only = false, defaultValue = 0, precision = 2) => ({ fieldname, label: __(label), fieldtype: "Float", read_only, default: existing?.[fieldname] ?? defaultValue, precision });
	const fields = [
		{ fieldname: "machine", label: __("Machine"), fieldtype: "Link", options: "Workstation", read_only: 1, default: scheduleRow.machine },
		{ fieldname: "plan_date", label: __("Plan Date"), fieldtype: "Date", read_only: 1, default: scheduleRow.plan_date },
		{ fieldname: "roll_code", label: __("Rollcode"), fieldtype: "Link", options: "Item", reqd: 1, default: existing?.roll_code || initialProduct, get_query: () => ({ query: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_machine_fg_items", filters: { machine: scheduleRow.machine } }), onchange: () => load_extrusion_dialog_details(dialog, scheduleRow.machine) },
		numeric("std_weight_kg", "StdWt", true, 0, 4),
		{ fieldname: "roll_description", label: __("Rolldesc"), fieldtype: "Data", read_only: 1, default: existing?.roll_description },
		{ fieldname: "used_for", label: __("Used For"), fieldtype: "Data", default: existing?.used_for },
		numeric("paid_time", "PaidTim", false, 24), numeric("vos", "VOS"), numeric("change_over", "C.O."), numeric("stabilization", "Stab"), numeric("plan_hours", "PlanHrs", true, 24), numeric("trim_percent", "% Trim", true), numeric("soph", "SOPH", true), numeric("number_of_kgs", "NoofKgs", true), numeric("number_of_rolls", "NoofRolls", true),
		{ fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text", default: existing?.remarks },
		{ fieldname: "color", label: __("Color"), fieldtype: "Data", default: existing?.color },
		numeric("virgin", "Virgin"), numeric("reco", "Reco"), numeric("colorant", "Colorant"), numeric("additives", "Additives"),
	];
	dialog = new frappe.ui.Dialog({ title: __(rowName ? "Edit Extrusion Item" : "Add Extrusion Item"), fields, primary_action_label: __("Save Row"), primary_action(values) {
		const target = existing || frm.add_child(tableField);
		Object.assign(target, values, { machine: scheduleRow.machine, plan_date: scheduleRow.plan_date });
		frm.refresh_field(tableField); frm.dirty(); dialog.hide(); keep_schedule_detail_open(frm, scheduleRow);
	} });
	for (const fieldname of ["paid_time", "vos", "change_over", "stabilization"]) dialog.fields_dict[fieldname].df.onchange = () => calculate_extrusion_dialog_output(dialog);
	dialog.show(); calculate_extrusion_dialog_output(dialog);
	if (initialProduct) load_extrusion_dialog_details(dialog, scheduleRow.machine);
}

async function load_extrusion_dialog_details(dialog, machine) {
	const itemCode = dialog.get_value("roll_code"); if (!itemCode) return;
	const response = await frappe.call({ method: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_item_production_details", args: { item_code: itemCode, machine } });
	const details = response.message || {};
	dialog.set_value("std_weight_kg", details.std_weight_gm || 0);
	dialog.set_value("roll_description", details.product_description || "");
	dialog.set_value("trim_percent", details.trim_percent || 0);
	dialog.set_value("soph", details.soph || 0);
	calculate_extrusion_dialog_output(dialog);
}

function calculate_extrusion_dialog_output(dialog) {
	const planHours = calculate_net_paid_hours(dialog.get_value("paid_time"), dialog.get_value("vos"), dialog.get_value("change_over"), dialog.get_value("stabilization"));
	const kgs = planHours * flt(dialog.get_value("soph"));
	dialog.set_value("plan_hours", planHours);
	dialog.set_value("number_of_kgs", kgs);
	dialog.set_value("number_of_rolls", flt(dialog.get_value("std_weight_kg")) ? kgs / flt(dialog.get_value("std_weight_kg")) : 0);
}

function keep_schedule_detail_open(frm, scheduleRow) {
	setTimeout(() => {
		const gridRow = frm.fields_dict.machine_schedule?.grid?.grid_rows_by_docname?.[scheduleRow.name];
		if (!gridRow) return;
		gridRow.toggle_view(true, () => {
			render_possible_sales_orders(frm, scheduleRow.doctype, scheduleRow.name);
		});
	}, 100);
}

async function load_dialog_product_details(dialog, machine, secondary, frm = null, scheduleRow = null) {
	const productCode = dialog.get_value("product_code"); if (!productCode) return;
	const response = await frappe.call({ method: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_item_production_details", args: { item_code: productCode, machine } });
	const details = response.message || {};
	for (const fieldname of ["product_description", "cavs", "soph", "std_weight_gm", "cycle_time"]) dialog.set_value(fieldname, details[fieldname] || 0);
	calculate_dialog_volume(dialog, secondary, frm, scheduleRow);
}

function calculate_dialog_volume(dialog, secondary, frm = null, scheduleRow = null) {
	if (secondary) {
		const parent = rows_for_schedule(frm, "item_1_schedule", scheduleRow)
			.find((row) => row.product_code === dialog.get_value("fg1_product_code"));
		const factorRate = flt(parent?.f_rate);
		dialog.set_value("factor_rate", factorRate);
		dialog.set_value("cycle_time", flt(parent?.cycle_time));
		const quantity = flt(parent?.daily_volume_qty) * factorRate / 100;
		dialog.set_value("daily_volume_qty", quantity);
		dialog.set_value("daily_volume_kgs", flt(dialog.get_value("std_weight_gm")) * quantity / 1000);
		return;
	}
	const hours = calculate_net_paid_hours(
		dialog.get_value("paid_hrs"),
		dialog.get_value("vos"),
		dialog.get_value("cm_co"),
		dialog.get_value("stab"),
	);
	const quantity = hours * flt(dialog.get_value("soph"));
	dialog.set_value("daily_volume_qty", quantity);
	dialog.set_value("daily_volume_kgs", flt(dialog.get_value("std_weight_gm")) * quantity / 1000);
}

function calculate_dialog_plan_hours(dialog) {
	const planHours = calculate_net_paid_hours(
		dialog.get_value("paid_hrs"),
		dialog.get_value("vos"),
		dialog.get_value("cm_co"),
		dialog.get_value("stab"),
	);
	dialog.set_value("plan_hrs", planHours);
	calculate_dialog_volume(dialog, false);
}

async function add_scheduled_item(frm, tableField, scheduleRow, productCode) {
	const row = frm.add_child(tableField, {
		machine: scheduleRow.machine,
		plan_date: scheduleRow.plan_date,
		product_code: productCode,
		paid_hrs: 24,
		plan_hrs: 24,
		...(tableField === "item_1_schedule" ? { f_rate: 100 } : { factor_rate: 100 }),
	});
	await populate_production_item(frm, row.doctype, row.name);
	frm.refresh_field(tableField);
}

async function populate_production_item(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	if (!row.product_code || !row.machine) return;
	const response = await frappe.call({
		method: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_item_production_details",
		args: { item_code: row.product_code, machine: row.machine },
	});
	const details = response.message || {};
	for (const fieldname of ["product_description", "cavs", "soph", "std_weight_gm", "cycle_time"]) {
		await frappe.model.set_value(cdt, cdn, fieldname, details[fieldname] || 0);
	}
	calculate_daily_volume(frm, cdt, cdn);
}

async function populate_extrusion_item(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	if (!row.roll_code || !row.machine) return;
	const response = await frappe.call({
		method: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_item_production_details",
		args: { item_code: row.roll_code, machine: row.machine },
	});
	const details = response.message || {};
	for (const [fieldname, value] of Object.entries({
		std_weight_kg: details.std_weight_gm,
		roll_description: details.product_description,
		trim_percent: details.trim_percent,
		soph: details.soph,
	})) {
		await frappe.model.set_value(cdt, cdn, fieldname, value || 0);
	}
	calculate_extrusion_output(frm, cdt, cdn);
}

function calculate_extrusion_output(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const planHours = calculate_net_paid_hours(row.paid_time, row.vos, row.change_over, row.stabilization);
	const kgs = planHours * flt(row.soph);
	frappe.model.set_value(cdt, cdn, "plan_hours", planHours);
	frappe.model.set_value(cdt, cdn, "number_of_kgs", kgs);
	frappe.model.set_value(cdt, cdn, "number_of_rolls", flt(row.std_weight_kg) ? kgs / flt(row.std_weight_kg) : 0);
}

function calculate_daily_volume(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	let quantity;
	if (row.doctype === "Weekly Production Plan Secondary Item") {
		const parent = (frm.doc.item_1_schedule || []).find((candidate) =>
			candidate.machine === row.machine
			&& candidate.plan_date === row.plan_date
			&& candidate.product_code === row.fg1_product_code
		);
		frappe.model.set_value(cdt, cdn, "factor_rate", flt(parent?.f_rate));
		frappe.model.set_value(cdt, cdn, "cycle_time", flt(parent?.cycle_time));
		quantity = flt(parent?.daily_volume_qty) * flt(parent?.f_rate) / 100;
	} else {
		const hours = calculate_net_paid_hours(row.paid_hrs, row.vos, row.cm_co, row.stab);
		quantity = hours * flt(row.soph);
	}
	frappe.model.set_value(cdt, cdn, "daily_volume_qty", quantity);
	frappe.model.set_value(cdt, cdn, "daily_volume_kgs", flt(row.std_weight_gm) * quantity / 1000);
	if (row.doctype === "Weekly Production Plan Item") update_linked_secondary_rows(frm, row, quantity);
}

function update_linked_secondary_rows(frm, parentRow, parentQuantity = null) {
	const quantity = parentQuantity === null ? flt(parentRow.daily_volume_qty) : flt(parentQuantity);
	for (const row of frm.doc.item_2_schedule || []) {
		if (
			row.machine !== parentRow.machine
			|| row.plan_date !== parentRow.plan_date
			|| row.fg1_product_code !== parentRow.product_code
		) continue;
		frappe.model.set_value(row.doctype, row.name, "factor_rate", flt(parentRow.f_rate));
		frappe.model.set_value(row.doctype, row.name, "cycle_time", flt(parentRow.cycle_time));
		const secondaryQuantity = quantity * flt(parentRow.f_rate) / 100;
		frappe.model.set_value(row.doctype, row.name, "daily_volume_qty", secondaryQuantity);
		frappe.model.set_value(row.doctype, row.name, "daily_volume_kgs", flt(row.std_weight_gm) * secondaryQuantity / 1000);
	}
}

function calculate_plan_hours(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const planHours = calculate_net_paid_hours(row.paid_hrs, row.vos, row.cm_co, row.stab);
	frappe.model.set_value(cdt, cdn, "plan_hrs", planHours);
	calculate_daily_volume(frm, cdt, cdn);
}

function calculate_net_paid_hours(paidHours, vos, cmCo, stab) {
	return flt(paidHours) - flt(vos) - flt(cmCo) - flt(stab);
}

function is_extrusion_section(section) {
	return String(section || "").trim().toUpperCase().startsWith("EXTRUSION");
}

async function refresh_machine_schedule(frm) {
	if (!frm.doc.start_date) {
		await frm.set_value("end_date", null);
		await frm.set_value("record_no", null);
		clear_generated_schedule(frm);
		return;
	}

	await frm.set_value("end_date", frappe.datetime.add_days(frm.doc.start_date, 13));
	if (!frm.doc.company || !frm.doc.section) {
		await frm.set_value("record_no", null);
		clear_generated_schedule(frm);
		return;
	}

	const requestedCompany = frm.doc.company;
	const requestedSection = frm.doc.section;
	const requestedStartDate = frm.doc.start_date;
	const response = await frappe.call({
		method: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_machine_schedule",
		args: {
			company: requestedCompany,
			section: requestedSection,
			start_date: requestedStartDate,
		},
		freeze: true,
		freeze_message: __("Building 14-day machine schedule..."),
	});

	if (
		frm.doc.company !== requestedCompany
		|| frm.doc.section !== requestedSection
		|| frm.doc.start_date !== requestedStartDate
	) return;

	const schedule = response.message || {};
	await frm.set_value("end_date", schedule.end_date || null);
	await frm.set_value("record_no", schedule.record_no || null);
	frm.clear_table("machine_schedule");
	for (const row of schedule.rows || []) {
		frm.add_child("machine_schedule", row);
	}
	frm.refresh_field("machine_schedule");
	set_grid_read_only(frm);

	if (!(schedule.rows || []).length) {
		frappe.msgprint(__("No enabled Workstations are assigned to Plant Floor {0}.", [requestedSection]));
	}
}

function clear_generated_schedule(frm) {
	frm.clear_table("machine_schedule");
	frm.refresh_field("machine_schedule");
}

function set_grid_read_only(frm) {
	const grid = frm.fields_dict.machine_schedule?.grid;
	if (!grid) return;
	grid.cannot_add_rows = true;
	grid.cannot_delete_rows = true;
	grid.wrapper.find(".grid-add-row, .grid-remove-rows, .grid-delete-row").hide();
}

function show_production_plan_import_dialog(frm) {
	if (!frm.doc.section || !frm.doc.start_date) {
		frappe.msgprint(__("Select the Section and Start Date first."));
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Import Production Plan"),
		fields: [
			{
				fieldname: "file_url",
				fieldtype: "Attach",
				label: __("Production Plan Excel"),
				reqd: 1,
			},
		],
		primary_action_label: __("Import"),
		async primary_action(values) {
			await import_production_plan(frm, values.file_url);
			dialog.hide();
		},
	});
	dialog.show();
}

async function import_production_plan(frm, fileUrl) {
	if (frm.doc.docstatus !== 0) {
		frappe.msgprint(__("Production Plan Excel can only be imported while the plan is Active."));
		return;
	}
	if (is_extrusion_section(frm.doc.section)) {
		frappe.msgprint(__("Production Plan Excel can only be imported for FG plans, not Extrusion plans."));
		return;
	}
	if (!fileUrl || !frm.doc.section || !frm.doc.start_date) {
		frappe.msgprint(__("Select the Section, Start Date, and Production Plan Excel file first."));
		return;
	}
	const occupiedSlots = [
		...(frm.doc.item_1_schedule || []),
		...(frm.doc.item_2_schedule || []),
	].map((row) => ({
		machine: row.machine,
		plan_date: row.plan_date,
	}));
	const response = await frappe.call({
		method: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.import_production_plan",
		args: {
			file_url: fileUrl,
			section: frm.doc.section,
			start_date: frm.doc.start_date,
			plan_name: frm.is_new() ? null : frm.doc.name,
			occupied_slots: JSON.stringify(occupiedSlots),
		},
		freeze: true,
		freeze_message: __("Reading and scheduling production plan..."),
	});
	const result = response.message || {};
	for (const values of result.rows || []) {
		Object.assign(frm.add_child("item_1_schedule"), values);
	}
	frm.refresh_field("item_1_schedule");
	frm.dirty();
	render_production_plan_import_results(frm, result);

	const message = __("Scheduled {0} of {1} product(s) into {2} daily row(s).", [
		result.scheduled_products || 0,
		result.source_rows || 0,
		(result.rows || []).length,
	]);
	frappe.show_alert({ message, indicator: (result.unassigned || []).length ? "orange" : "green" }, 7);
}

function render_production_plan_import_results(frm, result) {
	const wrapper = frm.fields_dict.import_results?.$wrapper;
	if (!wrapper) return;

	const unassigned = result.unassigned || [];
	if (!unassigned.length) {
		wrapper.html(`
			<div class="alert alert-success" style="margin: 15px 0">
				<strong>${__("Excel Import Result")}</strong><br>
				${__("All products with a positive For Production quantity were scheduled.")}
			</div>
		`);
		return;
	}

	const escape = frappe.utils.escape_html;
	const rows = unassigned.map((row) => `
		<tr>
			<td>${escape((row.excel_rows || []).join(", "))}</td>
			<td>${escape(row.product_code || "")}</td>
			<td class="text-right">${format_number(row.for_production_qty || 0)}</td>
			<td>${escape(row.reason || "")}</td>
		</tr>
	`).join("");

	wrapper.html(`
		<div class="alert alert-warning" style="margin: 15px 0 8px">
			<strong>${__("Products Not Scheduled")}</strong><br>
			${__("The following Excel rows could not be fully assigned. Update the machine schedule or BOM workstation, then import again.")}
		</div>
		<div class="table-responsive" style="margin-bottom: 15px">
			<table class="table table-bordered table-condensed">
				<thead><tr>
					<th>${__("Excel Row")}</th>
					<th>${__("Product Code")}</th>
					<th class="text-right">${__("Remaining Qty")}</th>
					<th>${__("Reason")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
	`);
}
