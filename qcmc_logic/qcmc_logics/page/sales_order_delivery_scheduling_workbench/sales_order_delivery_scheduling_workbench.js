frappe.pages["sales-order-delivery-scheduling-workbench"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({parent: wrapper, title: __("Sales Order Delivery Scheduling Workbench"), single_column: true});
	new SalesOrderDeliverySchedulingWorkbench(page);
};

class SalesOrderDeliverySchedulingWorkbench {
	constructor(page) {
		this.page = page;
		this.rows = [];
		this.filters = {company: frappe.defaults.get_user_default("Company"), delivery_date: frappe.datetime.get_today(), warehouse: "", include_overdue: 0};
		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_inner_button(__("Update Delivery Dates"), () => this.update_dates());
		this.page.add_inner_button(__("Rebalance Quantity"), () => this.rebalance());
		this.page.add_inner_button(__("Create DR for Confirmation"), () => this.create_dr());
		this.setup_body();
		this.setup_filters();
		this.refresh();
	}

	setup_body() {
		this.page.main.html(`<div class="sodsw"><div class="sodsw-filters"></div><div class="sodsw-summary text-muted small"></div><div class="sodsw-table"></div></div>`);
		this.$filters = this.page.main.find(".sodsw-filters");
		this.$summary = this.page.main.find(".sodsw-summary");
		this.$table = this.page.main.find(".sodsw-table");
		frappe.dom.set_style(`.sodsw-filters{position:relative;z-index:20;margin-bottom:10px;padding:10px 12px 2px;border:1px solid var(--border-color);border-radius:6px;background:var(--fg-color)}.sodsw-filter-row{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start}.sodsw-filter{width:220px}.sodsw-filters .awesomplete>ul{z-index:1000}.sodsw-table{position:relative;z-index:1;border:1px solid var(--border-color);border-radius:6px}.sodsw-table .dt-header,.sodsw-table .dt-row{font-size:12px}.sodsw-table .dt-cell__content{padding:6px 8px}.sodsw-table .btn-link{padding:0;font-size:12px}.sodsw-grid-action{white-space:nowrap}.sodsw-table .dt-scrollable{max-height:calc(100vh - 300px)}`);
	}

	setup_filters() {
		this.$filters.html(`<div class="sodsw-filter-row"><div class="sodsw-filter" data-field="company"></div><div class="sodsw-filter" data-field="delivery_date"></div><div class="sodsw-filter" data-field="warehouse"></div><div class="sodsw-filter sodsw-filter-check" data-field="include_overdue"></div></div>`);
		this.company = this.make_filter("company", "Company", "Link", "Company");
		this.delivery_date = this.make_filter("delivery_date", "Delivery Date", "Date");
		this.warehouse = this.make_filter("warehouse", "Warehouse", "Link", "Warehouse");
		this.include_overdue = this.make_filter("include_overdue", "Include Overdue", "Check");
	}

	make_filter(fieldname, label, fieldtype, options) { return frappe.ui.form.make_control({parent: this.$filters.find(`[data-field="${fieldname}"]`), df: {fieldname, label: __(label), fieldtype, options, reqd: fieldname !== "warehouse" && fieldname !== "include_overdue", default: this.filters[fieldname], get_query: fieldname === "warehouse" ? () => ({filters: {company: this.filters.company, is_group: 0, custom_is_province: 0}}) : undefined, change: () => {this.filters[fieldname] = this[fieldname].get_value(); this.refresh();}}, render_input: true}); }
	refresh() { if (!this.filters.company || !this.filters.delivery_date) return; frappe.call({method: "qcmc_logic.qcmc_logics.page.sales_order_delivery_scheduling_workbench.sales_order_delivery_scheduling_workbench.get_data", args: {filters: this.filters}, freeze: true, freeze_message: __("Loading schedules..."), callback: r => {if (!r.exc) {this.rows = r.message.rows || []; this.$summary.text(r.message.message || ""); this.render();}}}); }

	render() {
		this.$table.empty();
		const esc = value => frappe.utils.escape_html(value == null ? "" : String(value));
		const link = (doctype, value) => value ? `<a href="/app/${doctype}/${encodeURIComponent(value)}">${esc(value)}</a>` : "";
		const columns = [
			{name: __("Sales Order"), id: "sales_order", width: 150, format: value => link("sales-order", value)},
			{name: __("Customer"), id: "customer_name", width: 220},
			{name: __("Item"), id: "item_code", width: 145, format: value => link("item", value)},
			{name: __("Item Name"), id: "item_name", width: 220},
			{name: __("Warehouse"), id: "warehouse", width: 180},
			{name: __("Ordered Qty"), id: "qty", width: 110, type: "float", align: "right"},
			{name: __("Active DR Qty"), id: "draft_dr_qty", width: 120, type: "float", align: "right"},
			{name: __("Scheduled Qty"), id: "scheduled_qty", width: 130, sortable: false, format: (value, row, column, data) => `<button class="btn btn-link btn-xs sodsw-grid-action" data-action="qty" data-so-detail="${esc(data?.so_detail || "")}">${format_number(value)}</button>`},
			{name: __("Delivery Date"), id: "delivery_date", width: 155, sortable: false, format: (value, row, column, data) => `<button class="btn btn-link btn-xs sodsw-grid-action" data-action="date" data-so-detail="${esc(data?.so_detail || "")}" title="${__("Change delivery date") }"><i class="fa fa-calendar-o"></i> ${esc(value)}</button>`},
			{name: __("Actions"), id: "actions", width: 90, sortable: false, format: (value, row, column, data) => `<button class="btn btn-xs btn-default sodsw-grid-action" data-action="dr" data-so-detail="${esc(data?.so_detail || "")}" title="${__("Create Delivery Note")}"><i class="fa fa-truck"></i></button>`},
		];
		const data = this.rows.map(row => ({...row, scheduled_qty: row.qty, actions: ""}));
		this.datatable = new frappe.DataTable(this.$table[0], {columns, data, checkboxColumn: true, inlineFilters: true, layout: "fluid", serialNoColumn: false, dynamicRowHeight: true});
		this.bind_row_details();
		this.$table.off("click.sodsw", ".sodsw-grid-action").on("click.sodsw", ".sodsw-grid-action", e => {e.preventDefault(); const detail = $(e.currentTarget).attr("data-so-detail"); const row = this.rows.find(item => item.so_detail === detail); if (row) this.run_action($(e.currentTarget).data("action"), row);});
	}
	bind_row_details() { this.$table.find(".dt-row").each((_, element) => {const $row = $(element); const index = cint($row.attr("data-row-index") || $row.data("row-index") || 0); const row = this.rows[index]; if (row) $row.find(".sodsw-date-editor").attr("data-so-detail", row.so_detail);}); }

	selected() { return (this.datatable?.rowmanager?.getCheckedRows() || []).map(index => this.rows[index]).filter(Boolean); }
	row_details(rows) { return JSON.stringify(rows.map(r => r.so_detail)); }
	run_action(action, row) { if (action === "date") return this.update_dates([row]); if (action === "qty") return this.rebalance([row]); return this.create_dr([row]); }
	update_dates(rows = this.selected()) {
		if (!rows.length) return frappe.msgprint(__("Select at least one schedule."));
		let dialog;
		dialog = frappe.prompt({fieldname: "delivery_date", label: __("New Delivery Date"), fieldtype: "Date", reqd: 1, default: rows.length === 1 ? rows[0].delivery_date : null}, values => {
			dialog && dialog.hide();
			frappe.call({method: "qcmc_logic.qcmc_logics.page.sales_order_delivery_scheduling_workbench.sales_order_delivery_scheduling_workbench.update_delivery_dates", args: {so_details: this.row_details(rows), delivery_date: values.delivery_date}, freeze: true, freeze_message: __("Saving delivery date..."), callback: r => {if (!r.exc) this.refresh();}});
		}, __("Update Delivery Date"), __("Apply"));
	}

	rebalance(rows = this.selected()) {
		if (rows.length !== 1) return frappe.msgprint(__("Select exactly one schedule to rebalance."));
		const row = rows[0];
		frappe.call({method: "qcmc_logic.qcmc_logics.page.sales_order_delivery_scheduling_workbench.sales_order_delivery_scheduling_workbench.get_related_schedules", args: {source_so_detail: row.so_detail}, callback: r => {
			const schedules = r.message || [];
			if (!schedules.length) return frappe.msgprint(__("No other delivery schedules were found for this item."));
			const labels = schedules.map(s => `${s.delivery_date} - Qty ${format_number(s.qty)} / Available ${format_number(s.available_qty)}`);
			const by_label = Object.fromEntries(schedules.map((s, i) => [labels[i], s.name]));
			frappe.prompt([{fieldname: "new_qty", label: __("New Quantity for {0}").replace("{0}", row.delivery_date), fieldtype: "Float", reqd: 1, default: row.qty}, {fieldname: "target_schedule", label: __("Schedule to receive/supply the quantity difference"), fieldtype: "Select", options: labels.join("\n"), reqd: 1}, {fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text", reqd: 1}], values => frappe.call({method: "qcmc_logic.qcmc_logics.page.sales_order_delivery_scheduling_workbench.sales_order_delivery_scheduling_workbench.adjust_scheduled_quantity", args: {source_so_detail: row.so_detail, target_so_detail: by_label[values.target_schedule], new_qty: values.new_qty, remarks: values.remarks}, freeze: true, callback: response => {if (!response.exc) {frappe.msgprint(response.message); this.refresh();}}}), __("Rebalance Scheduled Quantity"), __("Apply"));
		}});
	}

	create_dr(rows = this.selected()) {
		if (!rows.length) return frappe.msgprint(__("Select at least one schedule."));
		frappe.call({method: "qcmc_logic.qcmc_logics.page.sales_order_delivery_scheduling_workbench.sales_order_delivery_scheduling_workbench.get_consolidation_candidates", args: {so_details: this.row_details(rows)}, callback: r => {
			if (r.exc) return;
			const candidates = r.message || [];
			if (!candidates.length) return this.submit_create_dr(rows, "");
			const options = candidates.map(candidate => ({label: `${candidate.name} · ${candidate.customer_name} · ${candidate.delivery_date} · ${candidate.item_count} ${__("existing item(s)")}`, value: candidate.name}));
			options.push({label: __("Create a separate Delivery Note"), value: "__separate__"});
			const dialog = new frappe.ui.Dialog({title: __("Existing Delivery Note Found"), fields: [{fieldname: "target_dn", label: __("Add selected schedule to"), fieldtype: "Select", options, reqd: 1, description: __("Only unreleased drafts for this Sales Order, date, address, and warehouse are offered.")}], primary_action_label: __("Continue"), primary_action: values => {dialog.hide(); this.submit_create_dr(rows, values.target_dn === "__separate__" ? "" : values.target_dn);}});
			dialog.show();
		}});
	}
	submit_create_dr(rows, consolidate_into) {
		frappe.call({method: "qcmc_logic.qcmc_logics.page.sales_order_delivery_scheduling_workbench.sales_order_delivery_scheduling_workbench.create_delivery_notes", args: {so_details: this.row_details(rows), consolidate_into}, freeze: true, freeze_message: __("Creating Delivery Note..."), callback: r => {if (!r.exc) {frappe.msgprint(r.message); this.refresh();}}});
	}
}
