frappe.pages["delivery-schedule-workbench"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Delivery Schedule Workbench"),
		single_column: true,
	});
	wrapper.delivery_schedule_workbench = new DeliveryScheduleWorkbench(page);
};
frappe.pages["delivery-schedule-workbench"].on_page_show = wrapper => wrapper.delivery_schedule_workbench?.resume_collaboration();

class DeliveryScheduleWorkbench {
	constructor(page) {
		this.page = page;
		this.v2_dirty = false;
		this.v2_dirty_fields = new Map();
		this.logistics_autosave_timers = {};
		this.logistics_save_requests = {};
		this.page.set_title(__("Delivery Schedule Workbench"));
		this.rows = [];
		this.autosave_timers = {};
		this.save_chain = Promise.resolve();
		this.dirty_rows = new Set();
		this.save_failed = false;
		this.load_sequence = 0;
		window.addEventListener("beforeunload", (event) => {
			if (this.dirty_rows.size || this.saving || this.v2_dirty) {
				event.preventDefault();
				event.returnValue = "";
			}
		});
		this.reason_options = "\nOK\nTO\nCR\nSA\nOR\nND\nSE";
		this.reason_meanings = {
			OK: "Good to go", TO: "Truck Overload", CR: "Customer Request",
			SA: "Stock Availability", OR: "Off Route", ND: "Next Delivery Date", SE: "Sales Error",
		};
		this.qty_reason_codes = ["SA", "CR", "TO", "SE"];
		this.date_reason_codes = ["OR", "ND"];
		this.setup_fields();
		this.setup_actions();
		this.setup_body();
		this.setup_collaboration();
		this.load_reason_options();
		this.refresh();
	}

	setup_collaboration() {
		this.collaboration_enabled = true;
		this.client_id = Array.from(crypto.getRandomValues(new Uint8Array(24)), byte => byte.toString(16).padStart(2, "0")).join("");
		this.edit_leases = {};
		this.edit_locks = {};
		this.lock_requests = {};
		this.release_requests = {};
		this.remote_pending = false;
		this.collaboration_offline = false;
		this.realtime_handler = event => {
			if (event?.kind === "saved") this.remote_pending = true;
			this.poll_collaboration();
			this.drain_remote_refresh();
		};
		frappe.router.on("change", () => {
			if (frappe.get_route()[0] === "delivery-schedule-workbench") this.resume_collaboration();
			else this.pause_collaboration();
		});
		document.addEventListener("visibilitychange", () => {
			if (!document.hidden && this.collaboration_active) {
				this.poll_collaboration();
				this.drain_remote_refresh();
			}
		});
		this.resume_collaboration();
	}

	resume_collaboration() {
		if (!this.collaboration_enabled || this.collaboration_active) return;
		this.collaboration_active = true;
		frappe.realtime.on("qcmc_delivery_workbench_changed", this.realtime_handler);
		this.collaboration_timer = setInterval(() => {
			this.poll_collaboration();
			this.release_idle_locks();
		}, 10000);
		this.remote_pending = true;
		this.poll_collaboration();
	}

	async pause_collaboration() {
		if (!this.collaboration_active) return;
		this.collaboration_active = false;
		clearInterval(this.collaboration_timer);
		clearTimeout(this.remote_timer);
		frappe.realtime.off("qcmc_delivery_workbench_changed", this.realtime_handler);
		if (await this.flush_saves() && !this.collaboration_active) {
			for (const name of Object.keys(this.edit_leases)) await this.release_edit(name);
		}
	}

	focused_note() {
		if (typeof document === "undefined") return null;
		const field = document.activeElement;
		if (!field?.dataset?.field || field.dataset.field === "selected" || !this.$tbody?.[0]?.contains(field)) return null;
		return this.rows[cint($(field).closest("tr").data("index"))]?.delivery_note;
	}

	has_local_work() {
		return !!(this.dirty_rows.size || this.saving || this.save_failed || this.v2_dirty || this.action_note || this.action_busy || this.focused_note() || Object.keys(this.lock_requests || {}).length);
	}

	async call_edit_action(options) {
		this.action_busy = true;
		try { return await frappe.call(options); }
		finally {
			this.action_busy = false;
			this.release_idle_locks();
			this.drain_remote_refresh();
		}
	}

	async ensure_edit(row) {
		const name = row.delivery_note;
		if (this.release_requests[name]) await this.release_requests[name];
		if (this.edit_leases[name] && !this.collaboration_offline) return true;
		if (this.lock_requests[name]) return this.lock_requests[name];
		this.lock_requests[name] = (async () => {
			try {
				const result = await frappe.call({
					method: "qcmc_logic.api.delivery_workbench_collaboration.acquire_edit",
					args: {delivery_note: name, client_id: this.client_id, document_modified: row.document_modified},
				});
				if (result.exc || !result.message) return false;
				this.edit_locks[name] = result.message.lock;
				if (!result.message.acquired) {
					frappe.msgprint(__("This Delivery Note is being edited by {0}.", [result.message.lock?.owner_name || ""]));
					return false;
				}
				this.edit_leases[name] = result.message.token;
				this.collaboration_offline = false;
				return true;
			} catch (error) {
				this.remote_pending = true;
				return false;
			} finally {
				delete this.lock_requests[name];
				this.paint_locks();
			}
		})();
		return this.lock_requests[name];
	}

	release_edit(name) {
		if (this.release_requests[name]) return this.release_requests[name];
		const token = this.edit_leases[name];
		if (!token) return Promise.resolve();
		this.release_requests[name] = (async () => {
			try {
				const result = await frappe.call({method: "qcmc_logic.api.delivery_workbench_collaboration.release_edit", args: {delivery_note: name, token}});
				if (result.exc) throw new Error("Release failed");
				if (this.edit_leases[name] === token) {
					delete this.edit_leases[name];
					delete this.edit_locks[name];
				}
				this.paint_locks();
			} catch (error) { this.collaboration_offline = true; this.paint_locks(); }
			finally { delete this.release_requests[name]; }
		})();
		return this.release_requests[name];
	}

	release_idle_locks() {
		if (this.saving || this.action_busy) return;
		for (const name of Object.keys(this.edit_leases)) {
			if (this.focused_note() === name || this.action_note === name) continue;
			if ([...this.dirty_rows].some(index => this.rows[index]?.delivery_note === name)) continue;
			this.release_edit(name);
		}
	}

	async poll_collaboration() {
		if (!this.collaboration_active || this.polling_collaboration) return;
		this.polling_collaboration = true;
		const leases = {...this.edit_leases};
		try {
			// The active grid is keyed by SO Delivery Schedule, not Delivery Note.
			// Only legacy DN rows and held DN leases belong in this lease query.
			const names = [...new Set([
				...this.rows.map(row => row.delivery_note).filter(name => typeof name === "string" && name),
				...Object.keys(leases),
			])];
			// Chunking keeps large grids within the API limit; renew all held leases.
			for (let offset = 0; offset < Math.max(names.length, 1); offset += 500) {
				const result = await frappe.call({method: "qcmc_logic.api.delivery_workbench_collaboration.get_state",
					args: {delivery_notes: names.slice(offset, offset + 500), client_id: this.client_id, leases}});
				if (result.exc || !result.message) throw new Error("Live update check failed");
				const state = result.message;
				Object.assign(this.edit_locks, state.locks);
				for (const name of Object.keys(state.locks)) {
					if (!leases[name] || this.edit_leases[name] !== leases[name] || state.renewed.includes(name)) continue;
					delete this.edit_leases[name];
					for (const index of this.dirty_rows) {
						if (this.rows[index]?.delivery_note !== name) continue;
						this.save_failed = true;
						this.set_save_status(index, __("Lock expired — copy edits and reload"));
					}
				}
				if (this.data_revision != null && this.data_revision !== state.revision) this.remote_pending = true;
			}
			this.collaboration_offline = false;
		} catch (error) {
			this.collaboration_offline = true;
		} finally {
			this.polling_collaboration = false;
			this.paint_locks();
			this.drain_remote_refresh();
		}
	}

	paint_locks() {
		if (!this.$tbody) return;
		this.$tbody.find("tr").each((_, element) => {
			const $row = $(element), row = this.rows[cint($row.data("index"))];
			if (!row) return;
			const lock = this.edit_locks[row.delivery_note];
			const blocked = this.collaboration_offline || (lock && !lock.mine);
			$row.find(".edit-lock-state").text(this.collaboration_offline ? __("Live connection unavailable") :
				lock ? (lock.mine ? __("Editing (you)") : __("🔒 Editing by {0}", [lock.owner_name])) : "");
			const state = this.get_reason_field_state(row.logistics_reason);
			$row.find("[data-field], [data-action]").each((_, field) => {
				if (field.dataset.field === "selected") return;
				const reason_disabled = (field.dataset.field === "logistics_proposed_qty" && state.proposed_qty_disabled) ||
					(field.dataset.field === "logistics_proposed_date" && state.proposed_date_disabled);
				field.disabled = !!(blocked || reason_disabled || this.lock_requests[row.delivery_note]);
			});
		});
	}

	drain_remote_refresh() {
		clearTimeout(this.remote_timer);
		if (!this.collaboration_active || !this.remote_pending || this.has_local_work()) return;
		this.remote_timer = setTimeout(() => {
			if (!this.collaboration_active || !this.remote_pending || this.has_local_work()) return;
			this.refresh({background: true}).catch(() => { this.remote_pending = true; });
		}, 250);
	}

	setup_fields() {
		this.filter_values = {
			company: frappe.defaults.get_user_default("Company"),
			delivery_date: frappe.datetime.get_today(),
			warehouse: "",
			include_overdue: 0,
		};
	}

	setup_actions() {
		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		if (this.can_sales_approve()) {
			this.page.add_inner_button(__("Create Delivery Note Details"), () => this.proceed_selected());
		}
	}

	setup_body() {
		this.page.main.html(`
			<div class="delivery-workbench">
				<div class="delivery-workbench-filters"></div>
				<div class="delivery-workbench-kpis"></div>
				<div class="delivery-workbench-summary text-muted small"></div>
				<div class="delivery-workbench-table-wrapper">
					<table class="table table-bordered table-sm delivery-workbench-table">
						<thead></thead>
						<tbody></tbody>
					</table>
				</div>
			</div>
		`);
		this.$filters = this.page.main.find(".delivery-workbench-filters");
		this.$kpis = this.page.main.find(".delivery-workbench-kpis");
		this.$summary = this.page.main.find(".delivery-workbench-summary");
		this.$thead = this.page.main.find("thead");
		this.$tbody = this.page.main.find("tbody");
		this.add_styles();
		this.setup_visible_filters();
		const {company, delivery_date} = this.filter_values;
		if (company) this.company.set_value(company);
		this.delivery_date.set_value(delivery_date);
	}

	setup_visible_filters() {
		this.$filters.html(`
			<div class="delivery-filter-row">
				<div class="delivery-filter" data-fieldname="company"></div>
				<div class="delivery-filter" data-fieldname="delivery_date"></div>
				<div class="delivery-filter" data-fieldname="warehouse"></div>
				<div class="delivery-filter delivery-filter-check" data-fieldname="include_overdue"></div>
			</div>
		`);
		this.company = frappe.ui.form.make_control({
			parent: this.$filters.find('[data-fieldname="company"]'),
			df: {
				fieldname: "company",
				label: __("Company"),
				fieldtype: "Link",
				options: "Company",
				reqd: 1,
				default: this.filter_values.company,
				change: () => {
					this.filter_values.company = this.company.get_value();
					this.refresh();
				},
			},
			render_input: true,
		});
		this.delivery_date = frappe.ui.form.make_control({
			parent: this.$filters.find('[data-fieldname="delivery_date"]'),
			df: {
				fieldname: "delivery_date",
				label: __("Delivery Date"),
				fieldtype: "Date",
				reqd: 1,
				default: this.filter_values.delivery_date,
				change: () => {
					this.filter_values.delivery_date = this.delivery_date.get_value();
					this.refresh();
				},
			},
			render_input: true,
		});
		this.warehouse = frappe.ui.form.make_control({
			parent: this.$filters.find('[data-fieldname="warehouse"]'),
			df: {
				fieldname: "warehouse",
				label: __("Warehouse"),
				fieldtype: "Link",
				options: "Warehouse",
				get_query: () => ({
					filters: {
						company: this.filter_values.company,
						is_group: 0,
						custom_is_province: 0,
					},
				}),
				change: () => {
					this.filter_values.warehouse = this.warehouse.get_value();
					this.refresh();
				},
			},
			render_input: true,
		});
		this.include_overdue = frappe.ui.form.make_control({
			parent: this.$filters.find('[data-fieldname="include_overdue"]'),
			df: {
				fieldname: "include_overdue",
				label: __("Include overdue"),
				fieldtype: "Check",
				default: this.filter_values.include_overdue,
				change: () => {
					this.filter_values.include_overdue = this.include_overdue.get_value();
					this.refresh();
				},
			},
			render_input: true,
		});
	}

	add_styles() {
		frappe.dom.set_style(`
			.delivery-workbench-table-wrapper {
				position: relative;
				z-index: 1;
				overflow: auto;
				max-height: calc(100vh - 240px);
				border: 1px solid var(--border-color);
				border-radius: 6px;
			}
			.delivery-workbench-filters {
				position: relative;
				z-index: 20;
				margin-bottom: 10px;
				padding: 10px 12px 2px;
				border: 1px solid var(--border-color);
				border-radius: 6px;
				background: var(--fg-color);
			}
			.delivery-workbench-filters .awesomplete > ul {
				z-index: 1000;
			}
			.delivery-filter-row {
				display: flex;
				flex-wrap: wrap;
				gap: 12px;
				align-items: flex-start;
			}
			.delivery-filter {
				min-width: 220px;
				max-width: 320px;
			}
			.delivery-filter-check {
				min-width: 140px;
				padding-top: 24px;
			}
			.delivery-workbench-table {
				min-width: 1040px;
				margin-bottom: 0;
				background: var(--fg-color);
				font-size: 12px;
				border-collapse: separate;
				border-spacing: 0;
			}
			.delivery-workbench-table thead th {
				position: sticky;
				top: 0;
				z-index: 4;
				background: var(--gray-100);
				white-space: nowrap;
				font-weight: 600;
				border-bottom: 1px solid var(--gray-400) !important;
			}
			.delivery-workbench-table td,
			.delivery-workbench-table th {
				vertical-align: middle !important;
				padding: 5px 6px !important;
				line-height: 1.2;
				border-right: 1px solid var(--gray-300) !important;
				border-bottom: 1px solid var(--gray-300) !important;
			}
			.delivery-workbench-table tbody tr:nth-child(even) td {
				background: var(--gray-50);
			}
			.delivery-workbench-table tbody tr:hover td {
				background: var(--highlight-color) !important;
			}
			.delivery-workbench-table input:not([type="checkbox"]),
			.delivery-workbench-table select,
			.delivery-workbench-table textarea {
				width: 100%;
				min-width: 70px;
				border: 1px solid var(--border-color);
				border-radius: 4px;
				background: var(--control-bg);
				color: var(--text-color);
				padding: 3px 6px;
				font-size: 12px;
				height: 28px;
			}
			.delivery-workbench-table input:disabled,
			.delivery-workbench-table select:disabled {
				background: var(--disabled-control-bg);
				color: var(--text-muted);
				cursor: not-allowed;
			}
			.delivery-workbench-table textarea {
				min-width: 220px;
				height: 32px;
				resize: vertical;
			}
			.delivery-workbench-table .readonly {
				background: var(--control-bg);
			}
			.delivery-workbench-table .number-cell {
				text-align: right;
				white-space: nowrap;
			}
			.delivery-workbench-table .check-col {
				width: 36px;
				min-width: 36px;
				text-align: center;
			}
			.delivery-workbench-table .delivery-check {
				width: 14px !important;
				min-width: 14px !important;
				height: 14px;
				margin: 0;
				vertical-align: middle;
			}
			.delivery-workbench-table .delivery-link {
				font-weight: 500;
			}
			.delivery-workbench-table tr.logistics-ok [data-field="logistics_proposed_qty"],
			.delivery-workbench-table tr.logistics-ok [data-field="logistics_proposed_date"] {
				opacity: 0.7;
			}
			.delivery-workbench-kpis { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 10px; }
			.delivery-workbench-kpi {
				min-width: 145px; padding: 9px 13px; background: var(--fg-color);
				border: 1px solid var(--border-color); border-left: 3px solid var(--primary); border-radius: 5px;
			}
			.delivery-workbench-kpi strong { display: block; font-size: 18px; }
			.delivery-workbench-summary {
				margin-bottom: 10px;
			}
		`);
	}

	can_logistics_review() {
		return frappe.session.user === "Administrator" || frappe.user.has_role("Stock Confirm User");
	}

	can_sales_approve() {
		return frappe.session.user === "Administrator" || frappe.user.has_role("Sales Coordinator");
	}

	get_filters() {
		return {
			company: this.filter_values.company,
			delivery_date: this.filter_values.delivery_date,
			warehouse: this.filter_values.warehouse,
			include_overdue: this.filter_values.include_overdue,
		};
	}

	load_reason_options() {
		frappe.call({
			method: "qcmc_logic.qcmc_logics.page.delivery_schedule_workbench.delivery_schedule_workbench.get_logistics_reason_options",
			callback: (r) => {
				this.reason_options = (r.message && r.message.options) || this.reason_options;
				this.reason_meanings = (r.message && r.message.meanings) || this.reason_meanings;
				if (!this.has_local_work()) this.render();
			},
		});
	}

	async refresh({background = false} = {}) {
		const sequence = ++this.load_sequence;
		if (this.v2_dirty && !background) {
			frappe.msgprint(__("Save your schedule edits before refreshing."));
			return;
		}
		if (background ? this.has_local_work() : !(await this.flush_saves())) {
			this.remote_pending = true;
			return;
		}
		const filters = this.get_filters();
		if (!filters.company || !filters.delivery_date) {
			this.rows = [];
			this.message = __("Select a company and delivery date to view schedules.");
			this.render();
			return;
		}
		return frappe.call({
				method: "qcmc_logic.api.delivery_schedule_collaboration_v2.get_schedule_rows",
				args: {...filters, limit: 500},
				freeze: !background,
				freeze_message: __("Loading SO Delivery Schedules..."),
				callback: r => {
					if (r.exc || sequence !== this.load_sequence) return;
					if (this.has_local_work() || this.focused_v2_field()) {this.remote_pending = true; return;}
					this.draft_dn_count = r.message?.draft_dn_count || 0;
					this.possibly_truncated = !!r.message?.possibly_truncated;
					this.rows = (r.message?.rows || []).filter(row => this.is_visible_schedule(row));
					if (r.message?.revision != null) this.data_revision = r.message.revision;
					this.message = __("{0} schedule(s)", [this.rows.length]);
					this.remote_pending = false;
					this.render();
				},
			});
	}

	render() {
		if (!this.$tbody) return;
		return this.render_v2();
	}

	focused_v2_field() {
		const field = document.activeElement;
		return !!(field?.dataset?.v2field && this.$tbody?.[0]?.contains(field));
	}

	is_visible_schedule(row) {
		return !row.has_active_dn && (row.history_status !== "Verified" ||
			Number(row.current_total ?? row.planned_qty) !== 0);
	}

	render_schedule_summary(escape) {
		if (!this.filter_values.company || !this.filter_values.delivery_date) return this.$kpis.empty();

		const pending = this.rows.filter(row => row.history_status === "Verified" && !row.has_protected_dn);
		const quantities = new Map();
		const orders = new Set();
		let items = 0;
		for (const row of pending) {
			const available = flt(row.current_total ?? row.planned_qty) - flt(row.draft_allocated_qty) - flt(row.submitted_dn_qty);
			if (available <= 0) continue;
			items++;
			orders.add(row.sales_order);
			quantities.set(row.uom, (quantities.get(row.uom) || 0) + available);
		}
		const remaining = [...quantities].sort(([left], [right]) => left.localeCompare(right))
			.map(([uom, qty]) => `${format_number(qty)} ${uom}`).join(" · ") || "0";
		const cards = [
			[__("Pending Sales Orders"), orders.size],
			[__("Pending Schedule Items"), items],
			[__("Remaining Schedulable Qty"), remaining],
			[__("Draft DNs · Selected Date"), this.draft_dn_count || 0],
		];
		this.$kpis.html(cards.map(([label, value]) => `
			<div class="delivery-workbench-kpi">
				<strong>${escape(value)}</strong><span class="small text-muted">${escape(label)}</span>
			</div>`).join(""));
	}

	render_v2() {
		const esc = value => frappe.utils.escape_html(String(value ?? ""));
		this.render_schedule_summary(esc);
		const reasonOptions = (this.reason_options || "").split("\n").filter(Boolean).map(code => ({
			code, meaning: this.reason_meanings?.[code] || "",
		}));
		this.$summary.text(`${this.message || __("{0} schedule(s)", [this.rows.length])} · ${__("Logistics changes save automatically. Completed schedules appear in Delivery Note Printing.")}`);
		if (this.possibly_truncated) this.$summary.append(" " + __("Showing a limited result set. Narrow the date or warehouse filter."));
		this.$thead.html(`<tr>
			<th class="check-col"><input class="delivery-check" type="checkbox" data-v2-action="select-all" title="${__("Select eligible schedules")}"></th>
			<th>${__("DN")}</th><th>${__("Customer")}</th><th>${__("SO")}</th><th>${__("Item")}</th>
			<th>${__("Warehouse")}</th><th>${__("Schedule Date")}</th><th>${__("Scheduled Qty")}</th>
			<th>${__("Stock (Stock UOM)")}</th><th>${__("Reason")}</th><th>${__("Transfer Qty")}</th>
			<th>${__("Transfer Date")}</th><th>${__("Shared Remarks")}</th><th>${__("Confirmed Qty")}</th>
		</tr>`);
		const selected = new Set(this.$tbody.find('[data-v2field="selected"]:checked')
			.map((_, checkbox) => checkbox.closest("tr").dataset.schedule).get());
		this.$tbody.html(this.rows.map((row, index) => {
			if (!this.is_visible_schedule(row)) return "";
			const status = row.confirmation_status || "Pending";
			const final = status === "Finalized";
			const reconciliationBlocked = row.history_status !== "Verified";
			const logisticsBlocked = !!row.has_protected_dn || reconciliationBlocked;
			const logistics = row.can_edit_logistics && !logisticsBlocked;
			const hasFinalQuantity = final && row.sales_confirmed_by && row.final_qty != null;
			const salesQuantity = flt(hasFinalQuantity ? row.final_qty : row.logistics_committed_qty);
			const draftDnQty = flt(row.draft_dn_qty || 0);
			const fullyAllocated = draftDnQty > 0 && draftDnQty >= salesQuantity;
			const canCreateDetails = row.can_edit_sales && row.logistics_confirmed_by && salesQuantity > draftDnQty && !row.has_protected_dn && !row.cancelled_dn_count && !reconciliationBlocked;
			const reopen = row.can_edit_sales && final && !row.has_dn_history ? `<button class="btn btn-xs btn-default" data-v2-action="reopen">${__("Reopen")}</button>` : "";
			const replacement = row.can_edit_sales && row.cancelled_dn_count > 0 && !row.has_active_dn && flt(row.planned_qty) > 0 ?
				`<button class="btn btn-xs btn-warning" data-v2-action="replacement">${__("Authorize Replacement")}</button>` : "";
			const reconcile = row.can_edit_logistics && row.active_dn_count === 1 && row.active_dn_state === "To Deliver and Bill" && !row.active_dn_has_invoice ?
				`<button class="btn btn-xs btn-warning" data-v2-action="reconcile">${__("Reconcile")}</button>` : "";
			const draftLink = row.active_dn
				? `<a href="/app/delivery-note/${encodeURIComponent(row.active_dn)}">${esc(row.active_dn)}</a>`
				: "—";
			const soLink = `<a href="/app/sales-order/${encodeURIComponent(row.sales_order)}">${esc(row.sales_order)}</a>`;
			const scheduleLink = row.name.startsWith("unscheduled:") ? esc(row.delivery_date) : `<a href="/app/so-delivery-schedule/${encodeURIComponent(row.name)}">${esc(row.delivery_date)}</a>`;
			const logisticsInput = (field, type, label, disabled = false) => {
				const value = row[field] ?? "";
				if (!logistics) return esc(value || "—");
				return `<input type="${type}" ${type === "number" ? 'min="0" step="any"' : ""} data-v2field="${field}" ${disabled ? "disabled" : ""} value="${esc(type === "number" && !Number(value) ? "" : value)}" aria-label="${esc(label)}">`;
			};
			const reasonState = this.get_reason_field_state(row.logistics_reason);
			const reason = logistics
				? `<select data-v2field="logistics_reason" aria-label="${__("Logistics reason")}"><option value="">${__("Select reason")}</option>${reasonOptions.map(({code, meaning}) => `<option value="${esc(code)}" ${row.logistics_reason === code ? "selected" : ""}>${esc(meaning || code)}</option>`).join("")}</select>`
				: esc(this.reason_meanings?.[row.logistics_reason] || row.logistics_reason || "—");
			let deliveryStatus = __("Waiting for Logistics");
			if (reconciliationBlocked) deliveryStatus = __("Reconciliation required");
			else if (fullyAllocated) deliveryStatus = __("Fully allocated to Draft DN");
			else if (row.cancelled_dn_count) deliveryStatus = __("Replacement authorization required");
			else if (row.has_protected_dn) deliveryStatus = __("Delivery Note protected");
			else if (canCreateDetails) deliveryStatus = draftDnQty ? __("Draft DN · quantity remaining") : __("Ready for Sales");
			else if (row.logistics_confirmed_by && salesQuantity > draftDnQty) deliveryStatus = __("Sales access required");
			return `<tr data-index="${index}" data-schedule="${esc(row.name)}">
				<td class="check-col"><input class="delivery-check" type="checkbox" data-v2field="selected" ${canCreateDetails ? (selected.has(row.name) ? "checked" : "") : "disabled"} aria-label="${esc(__("Select {0}", [row.name]))}"></td>
				<td>${draftLink}<div class="small text-muted">${esc(deliveryStatus)}</div>${reopen}${replacement}${reconcile}</td>
				<td>${esc(row.customer_name || row.customer)}</td>
				<td>${soLink}</td>
				<td title="${esc(row.item_name)}"><a href="/app/item/${encodeURIComponent(row.item_code)}">${esc(row.item_code)}</a></td>
				<td>${esc(row.warehouse)}</td>
				<td>${scheduleLink}${row.source_date ? `<div class="small text-muted">${__("From")} ${esc(row.source_date)}</div>` : ""}</td>
				<td class="number-cell">${esc(format_number(row.current_total ?? row.planned_qty))} ${esc(row.uom)}</td>
				<td class="number-cell">${row.actual_qty == null ? "—" : esc(format_number(row.actual_qty))}</td>
				<td>${reason}</td>
				<td>${logisticsInput("logistics_transfer_qty", "number", __("Transfer quantity"), reasonState.proposed_qty_disabled || reasonState.proposed_date_disabled)}</td>
				<td>${logisticsInput("logistics_destination_date", "date", __("Transfer destination date"), reasonState.proposed_date_disabled)}</td>
				<td>${logisticsInput("logistics_remarks", "text", __("Logistics remarks"))}</td>
				<td>${logisticsInput("logistics_committed_qty", "number", __("Confirmed quantity"))}<small class="logistics-save-status text-muted" role="status"></small></td>
			</tr>`;
		}).join(""));
		this.$thead.off("change.v2").on("change.v2", '[data-v2-action="select-all"]', event => this.$tbody.find('[data-v2field="selected"]:not(:disabled)').prop("checked", event.currentTarget.checked));
		this.$tbody.off("input.v2 change.v2 focusout.v2 click.v2");
		this.$tbody.on("input.v2 change.v2", "[data-v2field]", event => {
			if (event.currentTarget.dataset.v2field === "selected") return;
			const tr = $(event.currentTarget).closest("tr"), index = cint(tr.data("index"));
			const row = this.rows[index], field = event.currentTarget.dataset.v2field;
			if (!row) return;
			row[field] = event.currentTarget.value;
			const dirty = this.v2_dirty_fields.get(index) || new Set();
			dirty.add(field);
			this.v2_dirty_fields.set(index, dirty);
			this.v2_dirty = this.v2_dirty_fields.size > 0;
		});
		this.$tbody.on("change.v2", '[data-v2field="logistics_reason"]', event => {
			const tr = $(event.currentTarget).closest("tr");
			const index = cint(tr.data("index"));
			const row = this.rows[index];
			const state = this.get_reason_field_state(row.logistics_reason);
			const updateTransferField = (field, disabled) => {
				const input = tr.find(`[data-v2field="${field}"]`).prop("disabled", disabled);
				if (disabled && input.val()) input.val("").trigger("input");
			};
			updateTransferField("logistics_transfer_qty", state.proposed_qty_disabled || state.proposed_date_disabled);
			updateTransferField("logistics_destination_date", state.proposed_date_disabled);
			if (row.logistics_reason === "OK") {
				tr.find('[data-v2field="logistics_committed_qty"]')
					.val(row.current_total ?? row.planned_qty).trigger("input");
			}
			this.schedule_logistics_autosave(index, row, tr);
		});
		this.$tbody.on("focusout.v2", '[data-v2field^="logistics_"]', event => {
			const tr = $(event.currentTarget).closest("tr"), index = cint(tr.data("index")), row = this.rows[index];
			if (row && this.v2_dirty_fields.has(index)) this.schedule_logistics_autosave(index, row, tr);
		});
		this.$tbody.on("click.v2", "[data-v2-action]", event => {
			const button = $(event.currentTarget), tr = button.closest("tr"), row = this.rows[cint(tr.data("index"))];
			if (!row || button.prop("disabled")) return;
			this.handle_v2_action(button.attr("data-v2-action"), row, tr);
		});
	}

	schedule_logistics_autosave(index, row, tr) {
		clearTimeout(this.logistics_autosave_timers[index]);
		this.logistics_autosave_timers[index] = setTimeout(() => this.autosave_logistics_row(index, row, tr), 200);
	}

	async autosave_logistics_row(index, row, tr) {
		if (this.logistics_save_requests[index]) return this.logistics_save_requests[index];
		const value = field => {
			const control = tr.find(`[data-v2field="${field}"]`);
			return control.length ? control.val() : (row[field] ?? "");
		};
		const reason = value("logistics_reason");
		const state = this.get_reason_field_state(reason);
		const destinationDate = state.proposed_date_disabled ? "" : value("logistics_destination_date");
		const dateOnly = this.date_reason_codes.includes(reason);
		const transferQty = dateOnly && destinationDate ? (row.current_total ?? row.planned_qty)
			: state.proposed_date_disabled ? "" : value("logistics_transfer_qty");
		const quantity = dateOnly && destinationDate ? 0 : value("logistics_committed_qty");
		if (dateOnly && !destinationDate) return false;
		const hasTransfer = Number(transferQty) > 0;
		if (hasTransfer !== Boolean(destinationDate) || (!hasTransfer && quantity === "")) return false;
		const fields = ["logistics_committed_qty", "logistics_remarks", "logistics_reason", "logistics_transfer_qty", "logistics_destination_date"];
		const submitted = Object.fromEntries(fields.map(field => [field, String(value(field) ?? "")]));
		tr.find(".logistics-save-status").text(__("Saving…")).removeClass("text-danger");
		const request = frappe.call({
			method: "qcmc_logic.api.delivery_schedule_collaboration_v2.save_logistics_commitment",
			args: {schedule: row.name, expected_modified: row.modified, quantity,
				remarks: value("logistics_remarks").trim() || (dateOnly && destinationDate ? this.reason_meanings?.[reason] || reason : ""),
				reason_code: reason,
				transfer_qty: transferQty, destination_date: destinationDate},
		});
		this.logistics_save_requests[index] = request;
		try {
			const result = await request;
			if (result.exc || !result.message) return false;
			const dirty = this.v2_dirty_fields.get(index) || new Set();
			for (const field of fields) if (String(row[field] ?? "") === submitted[field]) dirty.delete(field);
			if (dirty.size) this.v2_dirty_fields.set(index, dirty);
			else this.v2_dirty_fields.delete(index);
			this.v2_dirty = this.v2_dirty_fields.size > 0;
			const initialized = row.name.startsWith("unscheduled:");
			this.merge_v2_response(row, index, result.message);
			if (initialized) row.name = result.message.schedule;
			const pending = [...(this.v2_dirty_fields.get(index) || [])].some(field => field.startsWith("logistics_"));
			if (pending) {
				this.schedule_logistics_autosave(index, row, tr);
			} else {
				tr.find(".logistics-save-status").text(__("Saved")).removeClass("text-danger");
				this.render_schedule_summary(value => frappe.utils.escape_html(String(value)));
				if (result.message.transfer) {
					this.remote_pending = true;
					tr.hide();
					this.drain_remote_refresh();
					frappe.show_alert({message: __("Moved to {0}", [destinationDate]), indicator: "green"});
				}
			}
			return true;
		} catch {
			tr.find(".logistics-save-status").text(__("Not saved — refresh required")).addClass("text-danger");
			return false;
		} finally {
			delete this.logistics_save_requests[index];
		}
	}

	async flush_logistics_autosaves() {
		const pending = [];
		for (const [index, fields] of this.v2_dirty_fields.entries()) {
			if (![...fields].some(field => field.startsWith("logistics_"))) continue;
			const tr = this.$tbody.find(`tr[data-index="${index}"]`);
			if (!tr.length) return false;
			clearTimeout(this.logistics_autosave_timers[index]);
			pending.push(this.autosave_logistics_row(index, this.rows[index], tr));
		}
		if (!pending.length && this.v2_dirty) return false;
		const results = await Promise.all(pending);
		return results.every(Boolean) && !this.v2_dirty;
	}

	async handle_v2_action(action, row, tr) {
		if (action === "reopen") return this.show_v2_reopen_dialog(row);
		if (action === "replacement") return this.show_v2_replacement_dialog(row);
		if (action === "reconcile") return this.show_v2_reconcile_dialog(row);
	}

	merge_v2_response(row, index, values) {
		const dirty = this.v2_dirty_fields.get(index) || new Set();
		Object.entries(values).forEach(([field, value]) => {
			if (!dirty.has(field)) row[field] = value;
		});
	}

	show_v2_reopen_dialog(row) {
		const dialog = new frappe.ui.Dialog({title: __("Reopen Finalized Schedule"), fields: [{fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1}],
			primary_action_label: __("Reopen"), primary_action: async values => {
				const result = await frappe.call({method: "qcmc_logic.api.delivery_schedule_collaboration_v2.reopen_schedule", args: {schedule: row.name, expected_modified: row.modified, reason: values.reason}, freeze: true});
				if (!result.exc) {dialog.hide(); this.v2_dirty = false; await this.refresh();}
			}});
		dialog.show();
	}

	show_v2_replacement_dialog(row) {
		if (!row.cancelled_dn_count || row.has_active_dn || flt(row.planned_qty) <= 0) {
			return frappe.msgprint(__("Only fully canceled Delivery Note demand can be replaced."));
		}
		const dialog = new frappe.ui.Dialog({title: __("Authorize Replacement Schedule"), fields: [
			{fieldname: "delivery_date", label: __("New Delivery Date"), fieldtype: "Date", reqd: 1},
			{fieldname: "reason", label: __("Authorization Reason / Remarks"), fieldtype: "Small Text", reqd: 1,
				description: __("Restored quantity: {0} {1}. This creates a new Pending schedule and keeps the canceled delivery history.", [format_number(row.planned_qty), row.uom])},
		], primary_action_label: __("Authorize Replacement"), primary_action: async values => {
			const result = await frappe.call({
				method: "qcmc_logic.api.delivery_schedule_collaboration_v2.authorize_cancelled_schedule_replacement",
				args: {schedule: row.name, expected_modified: row.modified,
					delivery_date: values.delivery_date, reason: values.reason}, freeze: true,
				freeze_message: __("Moving restored quantity to a new Pending schedule...")});
			if (!result.exc) { dialog.hide(); await this.refresh(); }
		}});
		dialog.show();
	}

	show_v2_reconcile_dialog(row) {
		if (row.active_dn_count !== 1 || !row.active_dn || !row.active_dn_detail) return frappe.msgprint(__("A single linked Draft Delivery Note is required."));
		const dialog = new frappe.ui.Dialog({title: __("Reconcile Actual Delivered Quantity"),
			fields: [
				{fieldname: "actual_qty", label: __("Actual Delivered Qty"), fieldtype: "Float", precision: row.qty_precision, default: row.active_dn_qty, reqd: 1,
					description: __("The quantity cannot exceed {0}. A zero delivery requires cancellation handling.", [format_number(row.active_dn_qty)])},
				{fieldname: "deferred_date", label: __("Reschedule Undelivered Balance To"), fieldtype: "Date"},
			],
			primary_action_label: __("Save Reconciliation"),
			primary_action: async values => {
				if (flt(values.actual_qty) < flt(row.active_dn_qty) && !values.deferred_date) return frappe.msgprint(__("Choose a date for the undelivered quantity."));
				const result = await frappe.call({method: "qcmc_logic.api.delivery_schedule_service.reconcile_delivered_quantity",
					args: {schedule: row.name, delivery_note: row.active_dn, dn_detail: row.active_dn_detail,
						actual_qty: values.actual_qty, deferred_date: values.deferred_date,
						expected_modified: row.modified, expected_dn_modified: row.active_dn_modified},
					freeze: true, freeze_message: __("Revising the Draft Delivery Note and schedule balance...")});
				if (!result.exc) {dialog.hide(); await this.refresh();}
			}});
		dialog.show();
	}

	render_row(row, index) {
		const reason_options = this.reason_options.split("\n").map((option) => {
			const selected = (option || "") === (row.logistics_reason || "") ? "selected" : "";
			const meaning = this.reason_meanings[option];
			const label = meaning ? `${option} - ${meaning}` : option;
			return `<option value="${frappe.utils.escape_html(option)}" ${selected}>${frappe.utils.escape_html(label)}</option>`;
		}).join("");
		const selected_approved_date = row.approved_date || (this.date_reason_codes.includes(row.logistics_reason || "") ? row.logistics_proposed_date : "");
		const available_dates = this.get_approved_date_options(row);
		if (selected_approved_date && !available_dates.includes(selected_approved_date)) {
			available_dates.unshift(selected_approved_date);
		}
		const approved_date_options = available_dates.map((date) => {
			const selected = date === (selected_approved_date || "") ? "selected" : "";
			return `<option value="${frappe.utils.escape_html(date)}" ${selected}>${frappe.utils.escape_html(date)}</option>`;
		}).join("");
		const committed_qty = row.logistics_proposed_qty != null ? row.logistics_proposed_qty : row.qty;
		const final_qty = row.qty;
		const qty_variance = flt(committed_qty) - flt(final_qty);
		const stock_color = flt(row.actual_qty) >= flt(row.qty) ? "green" : "red";
		const field_state = this.get_reason_field_state(row.logistics_reason);
		const proposed_qty_disabled = field_state.proposed_qty_disabled ? "disabled" : "";
		const proposed_date_disabled = field_state.proposed_date_disabled ? "disabled" : "";
		const remove_checked = cint(row.remove_item) ? "checked" : "";
		const logistics_cells = this.can_logistics_review() ? `
				<td><select class="form-control input-xs" data-field="logistics_reason">${reason_options}</select></td>
				<td><input class="form-control input-xs" type="number" data-field="logistics_proposed_qty" value="${row.logistics_proposed_qty ?? ""}" ${proposed_qty_disabled}></td>
				<td><input class="form-control input-xs" type="date" data-field="logistics_proposed_date" value="${row.logistics_proposed_date || ""}" ${proposed_date_disabled}></td>
				<td><textarea data-field="logistics_remarks">${frappe.utils.escape_html(row.logistics_remarks || "")}</textarea></td>` : `
				<td class="readonly logistics-readonly">${frappe.utils.escape_html(row.logistics_reason || "")}</td>
				<td class="readonly logistics-readonly number-cell">${format_number(committed_qty)}</td>
				<td class="readonly logistics-readonly">${frappe.utils.escape_html(row.logistics_proposed_date || "")}</td>
				<td><textarea data-field="logistics_remarks">${frappe.utils.escape_html(row.logistics_remarks || "")}</textarea></td>`;
		const sales_cells = this.can_sales_approve() ? `
				<td><button class="btn btn-default btn-xs" data-action="change-quantity">${format_number(row.qty)} · ${__("Change")}</button></td>
				<td class="number-cell sales-final-qty">${format_number(final_qty)}</td>
				<td class="number-cell sales-qty-variance">${format_number(qty_variance)}</td>
				<td><select class="form-control input-xs" data-field="approved_date"><option value=""></option>${approved_date_options}</select></td>
				<td class="text-center"><input class="delivery-check" type="checkbox" data-field="remove_item" ${remove_checked}></td>` : "";
		return `
			<tr data-index="${index}" class="${field_state.row_class}">
				<td class="check-col"><input class="delivery-check" type="checkbox" data-field="selected"></td>
				<td><a class="delivery-link" href="/app/delivery-note/${encodeURIComponent(row.delivery_note)}">${frappe.utils.escape_html(row.delivery_note || "")}</a></td>
				<td>${frappe.utils.escape_html(row.customer_name || "")}</td>
				<td><a class="delivery-link" href="/app/sales-order/${encodeURIComponent(row.sales_order)}">${frappe.utils.escape_html(row.sales_order || "")}</a></td>
				<td><a class="indicator ${stock_color}" href="/app/item/${encodeURIComponent(row.item_code)}">${frappe.utils.escape_html(row.item_code || "")}</a></td>
				<td class="item-name">${frappe.utils.escape_html(row.item_name || "")}</td>
				<td>${frappe.utils.escape_html(row.warehouse || "")}</td>
				<td class="number-cell">${format_number(row.qty)}</td>
				<td class="number-cell">${format_number(row.actual_qty)}</td>
				${logistics_cells}
				${sales_cells}
				<td class="save-state text-muted">${row.__save_status || ""}</td>
				<td class="edit-lock-state text-muted"></td>
			</tr>
		`;
	}


	get_approved_date_options(row) {
		return (row.available_reschedule_dates || "")
			.split(",")
			.map((value) => value.trim().split(" ")[0])
			.filter(Boolean);
	}

	get_next_delivery_date(row) {
		const base_date = row.workbench_date || this.filter_values.delivery_date || row.delivery_date;
		return base_date ? frappe.datetime.add_days(base_date, 1) : "";
	}

	bind_events() {
		this.$tbody.find("input, select, textarea").on("focusin", async event => {
			const field = event.currentTarget;
			if (!field.dataset.field || field.dataset.field === "selected") return;
			const index = cint($(field).closest("tr").data("index"));
			if (this.edit_leases[this.rows[index].delivery_note]) return;
			field.disabled = true;
			if (await this.ensure_edit(this.rows[index])) {
				this.paint_locks();
				if (!field.disabled && field.isConnected) field.focus();
			}
		});
		this.$tbody.find("input, select, textarea").on("focusout", () => {
			clearTimeout(this.idle_lock_timer);
			this.idle_lock_timer = setTimeout(() => { this.release_idle_locks(); this.drain_remote_refresh(); }, 1200);
		});
		this.$tbody.find('[data-action="change-quantity"]').on("click", async event => {
			const index = cint($(event.currentTarget).closest("tr").data("index"));
			if (!(await this.flush_saves())) return;
			const row = this.rows[index];
			if (!(await this.ensure_edit(row))) return;
			this.action_note = row.delivery_note;
			const dialog = new frappe.ui.Dialog({
				title: __("Change DR Quantity"),
				fields: [
					{fieldname: "qty", label: __("New DR Quantity"), fieldtype: "Float", default: row.qty},
					{fieldname: "move_date", label: __("Schedule balance on"), fieldtype: "Date", reqd: 1, description: __("The balance returns to Sales Order scheduling. No new DR is created.")},
					{fieldname: "remarks", label: __("Reason / Remarks"), fieldtype: "Small Text", reqd: 1},
				],
				primary_action_label: __("Apply"),
				primary_action: async values => {
					if (flt(values.qty) === 0) {
						await this.confirm_whole_dr_move(row, values.move_date, values.remarks, dialog);
						return;
					}
					const result = await this.call_edit_action({method: "qcmc_logic.qcmc_logics.page.delivery_schedule_workbench.delivery_schedule_workbench.change_dr_quantity", args: {delivery_note: row.delivery_note, dn_detail: row.dn_detail, document_modified: row.document_modified, edit_token: this.edit_leases[row.delivery_note], ...values}, freeze: true});
					if (!result.exc) { dialog.hide(); this.action_note = null; await this.release_edit(row.delivery_note); this.refresh(); }
				},
			});
			dialog.$wrapper.on("hidden.bs.modal", () => { this.action_note = null; this.release_idle_locks(); this.drain_remote_refresh(); });
			dialog.show();
		});
		this.$thead.find('[data-action="select-all"]').on("change", (event) => {
			this.$tbody.find('[data-field="selected"]').prop("checked", event.currentTarget.checked);
		});
		this.$tbody.find('[data-field="selected"]').on("change", (event) => {
			const index = cint($(event.currentTarget).closest("tr").data("index"));
			const delivery_note = this.rows[index].delivery_note;
			const checked = event.currentTarget.checked;
			this.$tbody.find("tr").each((_, tr) => {
				if (this.rows[cint($(tr).data("index"))].delivery_note === delivery_note) {
					$(tr).find('[data-field="selected"]').prop("checked", checked);
				}
			});
		});
		this.$tbody.find("input, select, textarea").on("input change", (event) => {
			const $field = $(event.currentTarget);
			const index = cint($field.closest("tr").data("index"));
			const fieldname = $field.data("field");
			if (!fieldname || fieldname === "selected") return;
			if (!this.edit_leases[this.rows[index].delivery_note]) return;
			const value = $field.attr("type") === "checkbox" ? ($field.prop("checked") ? 1 : 0) : $field.val();
			if (fieldname === "approved_qty") {
				this.rows[index].__sales_qty_touched = true;
			}
			this.rows[index][fieldname] = value;
			if (["logistics_reason", "logistics_proposed_qty", "logistics_proposed_date"].includes(fieldname)) {
				this.apply_reason_state($field.closest("tr"), this.rows[index], fieldname);
			}
			this.queue_autosave(index);
		});
	}

	get_reason_field_state(reason) {
		reason = reason || "";
		const is_ok = reason === "OK";
		const is_qty_reason = this.qty_reason_codes.includes(reason);
		const is_date_reason = this.date_reason_codes.includes(reason);
		return {
			proposed_qty_disabled: is_ok || is_date_reason,
			proposed_date_disabled: is_ok || is_qty_reason,
			row_class: is_ok ? "logistics-ok" : is_qty_reason ? "logistics-qty-exception" : is_date_reason ? "logistics-date-exception" : "",
		};
	}

	async confirm_whole_dr_move(row, move_date, remarks, quantity_dialog) {
		const method = "qcmc_logic.qcmc_logics.page.delivery_schedule_workbench.delivery_schedule_workbench.";
		const response = await this.call_edit_action({method: method + "preview_whole_dr_move", args: {delivery_note: row.delivery_note}});
		if (response.exc) return;
		const preview = response.message;
		const esc = value => frappe.utils.escape_html(String(value ?? ""));
		const table = `<p>${esc(preview.name)} · ${esc(preview.customer)}</p>
			<p>${__("Destination date")}: <strong>${esc(move_date)}</strong></p>
			<table class="table table-bordered"><thead><tr><th>${__("Item")}</th><th>${__("Description")}</th><th>${__("DR Qty")}</th><th>${__("Current Date")}</th></tr></thead><tbody>
			${preview.items.map(item => `<tr><td>${esc(item.item_code)}</td><td>${esc(item.item_name)}</td><td>${esc(format_number(item.qty))}</td><td>${esc(item.delivery_date)}</td></tr>`).join("")}</tbody></table>
			<p>${__("Moving the whole DR keeps these quantities allocated and requires Logistics confirmation again.")}</p>`;
		const dialog = new frappe.ui.Dialog({title: __("Move Whole DR to Another Date"), size: "large",
			fields: [
				{fieldtype: "HTML", fieldname: "preview", options: table},
				{fieldtype: "Small Text", fieldname: "remarks", label: __("Reason / Remarks"), reqd: 1, default: remarks || ""},
			],
			primary_action_label: __("Move Whole DR"),
			primary_action: async () => {
				const values = dialog.get_values();
				if (!values || !values.remarks.trim()) return;
				await submit("move_whole_dr", {delivery_note: row.delivery_note, move_date, remarks: values.remarks, document_modified: preview.document_modified});
			},
		});
		let saving = false;
		const submit = async (action, args) => {
			if (saving) return;
			saving = true;
			try {
				const result = await this.call_edit_action({method: method + action, args: {...args, remarks: args.remarks || remarks, edit_token: this.edit_leases[row.delivery_note]}, freeze: true});
				if (!result.exc) {dialog.hide(); quantity_dialog.hide(); this.action_note = null; await this.release_edit(row.delivery_note); await this.refresh();}
			} finally {saving = false;}
		};
		if (preview.items.length > 1) {
			dialog.set_secondary_action_label(__("Move Only This Item"));
			dialog.set_secondary_action(() => submit("change_dr_quantity", {delivery_note: row.delivery_note, dn_detail: row.dn_detail, qty: 0, move_date, document_modified: preview.document_modified}));
		}
		dialog.add_custom_action(__("Cancel"), () => dialog.hide());
		dialog.show();
	}

	apply_reason_state($row, row, changed_fieldname) {
		const reason = row.logistics_reason || "";
		const field_state = this.get_reason_field_state(reason);
		$row.toggleClass("logistics-ok", field_state.row_class === "logistics-ok");
		$row.toggleClass("logistics-qty-exception", field_state.row_class === "logistics-qty-exception");
		$row.toggleClass("logistics-date-exception", field_state.row_class === "logistics-date-exception");
		const $proposed_qty = $row.find('[data-field="logistics_proposed_qty"]');
		const $proposed_date = $row.find('[data-field="logistics_proposed_date"]');
		const $final_qty = $row.find('[data-field="approved_qty"]');
		const $move_date = $row.find('[data-field="approved_date"]');
		const $remove_item = $row.find('[data-field="remove_item"]');
		$proposed_qty.prop("disabled", field_state.proposed_qty_disabled);
		$proposed_date.prop("disabled", field_state.proposed_date_disabled);
		if (reason === "OK") {
			row.logistics_proposed_qty = "";
			row.logistics_proposed_date = "";
			row.approved_date = "";
			row.remove_item = 0;
			$proposed_qty.val("");
			$proposed_date.val("");
			$move_date.val("");
			$remove_item.prop("checked", false);
			row.approved_qty = row.qty;
			$final_qty.val(row.qty);
		} else if (this.qty_reason_codes.includes(reason)) {
			row.logistics_proposed_date = "";
			$proposed_date.val("");
			$remove_item.prop("checked", false);
			row.remove_item = 0;
			if (changed_fieldname === "logistics_proposed_qty" || (changed_fieldname === "logistics_reason" && !row.__sales_qty_touched)) {
				row.approved_qty = row.logistics_proposed_qty === "" || row.logistics_proposed_qty == null ? "" : row.logistics_proposed_qty;
				$final_qty.val(row.approved_qty);
				if (flt(row.logistics_proposed_qty) === 0) {
					row.remove_item = 1;
					$remove_item.prop("checked", true);
				} else {
					row.remove_item = 0;
					$remove_item.prop("checked", false);
				}
			}
		} else if (this.date_reason_codes.includes(reason)) {
			if (reason === "ND" && !row.logistics_proposed_date) {
				row.logistics_proposed_date = this.get_next_delivery_date(row);
				$proposed_date.val(row.logistics_proposed_date);
			}
			row.logistics_proposed_qty = "";
			row.approved_qty = 0;
			row.approved_date = row.logistics_proposed_date || row.approved_date || "";
			row.remove_item = 1;
			$proposed_qty.val("");
			$final_qty.val(0);
			if (row.approved_date && !$move_date.find("option").filter((_, option) => option.value === row.approved_date).length) {
				$move_date.append($("<option>").val(row.approved_date).text(row.approved_date));
			}
			$move_date.val(row.approved_date);
			$remove_item.prop("checked", true);
		}
	}

	queue_autosave(index) {
		this.dirty_rows.add(index);
		clearTimeout(this.autosave_timers[index]);
		this.set_save_status(index, __("Saving..."));
		this.autosave_timers[index] = setTimeout(() => this.autosave_row(index), 600);
	}

	autosave_row(index) {
		clearTimeout(this.autosave_timers[index]);
		this.save_chain = this.save_chain.then(async () => {
			if (this.save_failed || !this.dirty_rows.has(index)) return;
			this.dirty_rows.delete(index);
			const row = Object.assign({}, this.rows[index]);
			row.edit_token = this.edit_leases?.[row.delivery_note];
			this.saving = true;
			try {
				if (this.collaboration_enabled && !row.edit_token) throw new Error("Editing lock required");
				const r = await frappe.call({
					method: "qcmc_logic.qcmc_logics.page.delivery_schedule_workbench.delivery_schedule_workbench.autosave_item",
					args: {row},
				});
				if (r.exc || !r.message?.saved) throw new Error("Save failed");
				this.rows.filter(item => item.delivery_note === row.delivery_note).forEach(item => {
					item.document_modified = r.message.document_modified;
				});
				this.set_save_status(index, this.dirty_rows.has(index) ? __("Saving...") : __("Saved"));
			} catch (error) {
				this.dirty_rows.add(index);
				this.save_failed = true;
				this.set_save_status(index, __("Not saved — reload required"));
			} finally {
				this.saving = false;
				if (this.collaboration_enabled) {
					this.remote_pending = true;
					this.release_idle_locks();
					this.drain_remote_refresh();
				}
			}
		});
		return this.save_chain;
	}

	async flush_saves() {
		for (const index of this.dirty_rows) this.autosave_row(index);
		await this.save_chain;
		if (this.save_failed) {
			frappe.msgprint(__("Changes could not be saved. Copy your unsaved edits, then reload this page before continuing."));
			return false;
		}
		if (this.dirty_rows.size) return this.flush_saves();
		return true;
	}

	set_save_status(index, status) {
		this.rows[index].__save_status = status;
		this.$tbody.find(`tr[data-index="${index}"] .save-state`).text(status);
	}

	get_selected_rows() {
		const selected = [];
		this.$tbody.find("tr").each((_, row) => {
			const $row = $(row);
			if (!$row.find('[data-field="selected"]').prop("checked")) return;
			selected.push(this.rows[cint($row.data("index"))]);
		});
		return selected;
	}

	async proceed_selected() {
		return this.proceed_v2_selected();
	}

	async proceed_v2_selected() {
		if (this.v2_dirty && !(await this.flush_logistics_autosaves())) {
			return frappe.msgprint(__("Complete any unfinished Logistics fields and wait for them to save before creating Delivery Note details."));
		}
		const selected = [];
		this.$tbody.find("tr").each((_, element) => {
			const tr = $(element);
			if (tr.find('[data-v2field="selected"]').prop("checked")) selected.push(this.rows[cint(tr.data("index"))]);
		});
		if (!selected.length) return frappe.msgprint(this.$tbody.find('[data-v2field="selected"]:enabled').length
			? __("Select at least one eligible schedule.")
			: __("No schedules on this date have quantity eligible for a new or existing Draft Delivery Note. Open a linked Delivery Note to review quantities already allocated."));
		if (selected.some(row => !row.logistics_confirmed_by || !row.logistics_committed_qty || flt(row.logistics_committed_qty) <= 0)) {
			return frappe.msgprint(__("Every selected schedule needs a Logistics-confirmed quantity."));
		}
		const selection = selected.map(row => ({schedule: row.name, modified: row.modified,
			draft_allocated_qty: row.draft_allocated_qty || 0}));
		const preview_call = await frappe.call({
			method: "qcmc_logic.api.delivery_schedule_collaboration_v2.get_proceed_to_dr_preview",
			args: {schedules: selection}, freeze: true, freeze_message: __("Preparing Delivery Note details..."),
		});
		if (preview_call.exc || !preview_call.message) return;
		const preview = preview_call.message;
		const esc = value => frappe.utils.escape_html(value == null ? "" : String(value));
		const displayQty = value => format_number(value);
		const groups = (preview.groups || []).map(group => `
			<section class="border rounded mb-3">
				<div class="px-3 py-2 border-bottom">
					<div><strong>${esc(group.sales_order)}</strong> · ${esc(group.customer)}</div>
					<div class="small text-muted">${esc(group.delivery_date)} · ${esc(group.warehouse)}</div>
				</div>
				<div class="table-responsive">
					<table class="table table-sm mb-0">
						<thead><tr>
							<th scope="col" style="width:38%">${__("Item")}</th>
							<th scope="col" class="text-right">${__("Confirmed")}</th>
							<th scope="col" class="text-right" style="min-width:110px">${__("Qty for DN")}</th>
							<th scope="col" class="text-right">${__("On Draft DN")}</th>
							<th scope="col" class="text-right">${__("To Add")}</th>
							<th scope="col">${__("UOM")}</th>
						</tr></thead>
						<tbody>${group.items.map(item => `
							<tr>
								<td><strong>${esc(item.item_code)}</strong><div class="small text-muted">${esc(item.item_name)}</div></td>
								<td class="text-right text-nowrap">${esc(displayQty(item.logistics_confirmed_qty))}</td>
								<td>
									<input type="number" class="form-control input-sm text-right"
										data-dn-schedule-qty="${esc(item.schedule)}" min="${esc(item.draft_allocated_qty)}"
										max="${esc(item.logistics_confirmed_qty)}" step="any" value="${esc(item.final_qty)}"
										${item.quantity_locked ? "readonly" : ""} aria-label="${esc(__("Quantity for {0}", [item.item_code]))}">
								</td>
								<td class="text-right text-nowrap">${esc(displayQty(item.draft_allocated_qty))}</td>
								<td class="text-right text-nowrap font-weight-bold" data-dn-to-add>${esc(displayQty(item.qty_to_add))}</td>
								<td>${esc(item.uom)}</td>
							</tr>`).join("")}</tbody>
					</table>
				</div>
			</section>`).join("");
		const omitted = (preview.omitted || []).length ? `<div class="alert alert-warning"><b>${__("Not selected — will not be added")}</b><ul>
			${preview.omitted.map(row => `<li>${esc(row.sales_order)} · ${esc(row.customer)} · ${esc(row.item_code)} · ${esc(row.delivery_date)} · ${esc(row.final_qty)} ${esc(row.uom)} · ${esc(row.warehouse)}</li>`).join("")}
			</ul>${__("These other Logistics-confirmed schedules share the selected Sales Order and date. They are omitted from this request and will not be included unless selected separately.")}</div>` : "";
		const dialog = new frappe.ui.Dialog({
			title: __("Review Draft Delivery Notes"),
			size: "extra-large",
			fields: [{fieldtype: "HTML", fieldname: "preview", options: `<div>${groups}${omitted}</div>`}],
			primary_action_label: __("Create Draft Delivery Notes"),
			primary_action: async () => {
				const quantities = {};
				let invalid = false;
				dialog.$wrapper.find("[data-dn-schedule-qty]").each((_, element) => {
					const input = $(element), qty = Number(input.val()), minimum = Number(input.attr("min")), maximum = Number(input.attr("max"));
					input.removeClass("is-invalid");
					if (!Number.isFinite(qty) || qty <= 0 || qty < minimum || qty > maximum) {
						input.addClass("is-invalid");
						invalid = true;
						return;
					}
					quantities[input.attr("data-dn-schedule-qty")] = qty;
				});
				if (invalid) return frappe.msgprint(__("Enter a positive DN quantity no greater than Logistics Confirmed and no lower than what is already on the Draft DN."));
				dialog.disable_primary_action();
				try {
					const schedules = preview.schedules.map(entry => ({...entry, quantity: quantities[entry.schedule]}));
					const result = await frappe.call({
						method: "qcmc_logic.api.delivery_schedule_collaboration_v2.proceed_to_dr",
						args: {schedules}, freeze: true,
						freeze_message: __("Creating Draft Delivery Note details..."),
					});
					if (!result.exc) { dialog.hide(); frappe.msgprint(result.message?.message || __("Draft Delivery Note details created.")); await this.refresh(); }
				} finally {
					dialog.enable_primary_action();
				}
			},
		});
		dialog.show();
		dialog.$wrapper.on("input.delivery-qty", "[data-dn-schedule-qty]", event => {
			const input = $(event.currentTarget), qty = Number(input.val()) || 0;
			const allocated = Number(input.attr("min")) || 0;
			input.closest("tr").find("[data-dn-to-add]").text(displayQty(Math.max(0, qty - allocated)));
		});
	}
}
