frappe.pages["delivery-schedule-workbench"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Delivery Schedule Workbench"),
		single_column: true,
	});
	new DeliveryScheduleWorkbench(page);
};

class DeliveryScheduleWorkbench {
	constructor(page) {
		this.page = page;
		this.rows = [];
		this.autosave_timers = {};
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
		this.load_reason_options();
		this.refresh();
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
			this.page.add_inner_button(__("Proceed Selected to DR"), () => this.proceed_selected());
		}
		this.page.add_inner_button(__("Open Report"), () => {
			frappe.set_route("query-report", "Delivery Schedule Confirmation", {
				company: this.filter_values.company,
				delivery_date: this.filter_values.delivery_date,
				warehouse: this.filter_values.warehouse,
			});
		});
	}

	setup_body() {
		this.page.main.html(`
			<div class="delivery-workbench">
				<div class="delivery-workbench-filters"></div>
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
		this.$summary = this.page.main.find(".delivery-workbench-summary");
		this.$thead = this.page.main.find("thead");
		this.$tbody = this.page.main.find("tbody");
		this.add_styles();
		this.setup_visible_filters();
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
				min-width: 2000px;
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
			.delivery-workbench-table .item-name {
				min-width: 180px;
				max-width: 240px;
				white-space: normal;
			}
			.delivery-workbench-table td:nth-child(3) {
				max-width: 180px;
				white-space: normal;
				overflow-wrap: anywhere;
			}
			.delivery-workbench-table td:nth-child(7) {
				min-width: 120px;
				max-width: 170px;
				white-space: normal;
				overflow-wrap: anywhere;
			}
			.delivery-workbench-table th:nth-child(10),
			.delivery-workbench-table td:nth-child(10) { min-width: 90px; }
			.delivery-workbench-table th:nth-child(11),
			.delivery-workbench-table td:nth-child(11) { min-width: 100px; }
			.delivery-workbench-table th:nth-child(12),
			.delivery-workbench-table td:nth-child(12) { min-width: 135px; }
			.delivery-workbench-table th:nth-child(13),
			.delivery-workbench-table td:nth-child(13) { min-width: 230px; }
			.delivery-workbench-table th:nth-child(1),
			.delivery-workbench-table td:nth-child(1),
			.delivery-workbench-table th:nth-child(2),
			.delivery-workbench-table td:nth-child(2),
			.delivery-workbench-table th:nth-child(3),
			.delivery-workbench-table td:nth-child(3) {
				position: sticky;
				background: var(--fg-color);
				z-index: 3;
			}
			.delivery-workbench-table thead th:nth-child(1),
			.delivery-workbench-table thead th:nth-child(2),
			.delivery-workbench-table thead th:nth-child(3) {
				z-index: 5;
				background: var(--gray-100);
			}
			.delivery-workbench-table th:nth-child(1), .delivery-workbench-table td:nth-child(1) { left: 0; width: 36px; min-width: 36px; }
			.delivery-workbench-table th:nth-child(2), .delivery-workbench-table td:nth-child(2) { left: 36px; width: 130px; min-width: 130px; }
			.delivery-workbench-table th:nth-child(3), .delivery-workbench-table td:nth-child(3) {
				left: 166px;
				width: 180px;
				min-width: 180px;
				box-shadow: 2px 0 0 var(--gray-400);
			}
			.delivery-workbench-table tr.logistics-ok [data-field="logistics_proposed_qty"],
			.delivery-workbench-table tr.logistics-ok [data-field="logistics_proposed_date"] {
				opacity: 0.7;
			}
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
				this.render();
			},
		});
	}

	refresh() {
		const filters = this.get_filters();
		if (!filters.company || !filters.delivery_date) return;
		frappe.call({
			method: "qcmc_logic.qcmc_logics.page.delivery_schedule_workbench.delivery_schedule_workbench.get_data",
			args: {filters},
			freeze: true,
			freeze_message: __("Loading Delivery Schedule..."),
			callback: (r) => {
				if (r.exc) return;
				this.rows = (r.message && r.message.rows) || [];
				this.message = (r.message && r.message.message) || "";
				this.render();
			},
		});
	}

	render() {
		if (!this.$tbody) return;
		this.$summary.text(this.message || __("{0} item(s)", [this.rows.length]));
		const sales_headers = this.can_sales_approve() ? `
				<th>${__("Final DR Qty")}</th>
				<th>${__("Move To")}</th>
				<th>${__("Remove")}</th>` : "";
		this.$thead.html(`
			<tr>
				<th class="check-col"><input class="delivery-check" type="checkbox" data-action="select-all"></th>
				<th>${__("DN")}</th>
				<th>${__("Customer")}</th>
				<th>${__("SO")}</th>
				<th>${__("Item")}</th>
				<th>${__("Item Name")}</th>
				<th>${__("Warehouse")}</th>
				<th>${__("DR Qty")}</th>
				<th>${__("Stock")}</th>
				<th>${__("Reason")}</th>
				<th>${__("Prop Qty")}</th>
				<th>${__("Prop Date")}</th>
				<th>${__("Logistics Remarks")}</th>
				${sales_headers}
				<th>${__("Save")}</th>
			</tr>
		`);
		this.$tbody.html(this.rows.map((row, index) => this.render_row(row, index)).join(""));
		this.bind_events();
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
		const final_qty = row.approved_qty != null ? row.approved_qty : committed_qty;
		const stock_color = flt(row.actual_qty) >= flt(row.qty) ? "green" : "red";
		const field_state = this.get_reason_field_state(row.logistics_reason);
		const proposed_qty_disabled = field_state.proposed_qty_disabled ? "disabled" : "";
		const proposed_date_disabled = field_state.proposed_date_disabled ? "disabled" : "";
		const remove_checked = cint(row.remove_item) ? "checked" : "";
		const sales_cells = this.can_sales_approve() ? `
				<td><input class="form-control input-xs" type="number" data-field="approved_qty" value="${final_qty ?? ""}"></td>
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
				<td><select class="form-control input-xs" data-field="logistics_reason">${reason_options}</select></td>
				<td><input class="form-control input-xs" type="number" data-field="logistics_proposed_qty" value="${row.logistics_proposed_qty ?? ""}" ${proposed_qty_disabled}></td>
				<td><input class="form-control input-xs" type="date" data-field="logistics_proposed_date" value="${row.logistics_proposed_date || ""}" ${proposed_date_disabled}></td>
				<td><textarea data-field="logistics_remarks">${frappe.utils.escape_html(row.logistics_remarks || "")}</textarea></td>
				${sales_cells}
				<td class="save-state text-muted">${row.__save_status || ""}</td>
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
		this.$thead.find('[data-action="select-all"]').on("change", (event) => {
			this.$tbody.find('[data-field="selected"]').prop("checked", event.currentTarget.checked);
		});
		this.$tbody.find("input, select, textarea").on("input change", (event) => {
			const $field = $(event.currentTarget);
			const index = cint($field.closest("tr").data("index"));
			const fieldname = $field.data("field");
			if (!fieldname || fieldname === "selected") return;
			const value = $field.attr("type") === "checkbox" ? ($field.prop("checked") ? 1 : 0) : $field.val();
			if (fieldname === "approved_qty") {
				this.rows[index].__sales_qty_touched = true;
			}
			this.rows[index][fieldname] = value;
			if (fieldname === "logistics_reason" && event.type === "change") {
				const meaning = this.reason_meanings[value];
				const remarks = meaning ? `${value} - ${meaning}` : "";
				this.rows[index].logistics_remarks = remarks;
				$field.closest("tr").find('[data-field="logistics_remarks"]').val(remarks);
			}
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
				row.approved_qty = row.logistics_proposed_qty || "";
				$final_qty.val(row.approved_qty);
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
		clearTimeout(this.autosave_timers[index]);
		this.set_save_status(index, __("Saving..."));
		this.autosave_timers[index] = setTimeout(() => this.autosave_row(index), 600);
	}

	autosave_row(index) {
		const row = Object.assign({}, this.rows[index]);
		if ((row.logistics_reason || "") === "OK") {
			row.logistics_proposed_qty = "";
			row.logistics_proposed_date = "";
		}
		frappe.call({
			method: "qcmc_logic.qcmc_logics.page.delivery_schedule_workbench.delivery_schedule_workbench.autosave_item",
			args: {row},
			callback: (r) => {
				if (r.exc) {
					this.set_save_status(index, __("Not saved"));
					return;
				}
				this.set_save_status(index, __("Saved"));
				setTimeout(() => this.set_save_status(index, ""), 1500);
			},
		});
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

	proceed_selected() {
		const rows = this.get_selected_rows();
		if (!rows.length) return frappe.msgprint(__("Select at least one row."));
		frappe.confirm(__("Proceed selected Delivery Note(s) to DR Printing?"), () => {
			frappe.call({
				method: "qcmc_logic.qcmc_logics.report.delivery_schedule_confirmation.delivery_schedule_confirmation.proceed_to_dr_printing_bulk",
				args: {items: rows},
				freeze: true,
				freeze_message: __("Applying Sales-approved DR values..."),
				callback: (r) => {
					if (r.exc) return;
					frappe.msgprint(r.message);
					this.refresh();
				},
			});
		});
	}
}
