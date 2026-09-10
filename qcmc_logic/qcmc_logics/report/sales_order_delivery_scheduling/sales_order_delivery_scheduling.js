frappe.query_reports["Sales Order Delivery Scheduling"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company")},
		{fieldname: "delivery_date", label: __("Delivery Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today()},
		{
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			get_query: () => ({filters: {company: frappe.query_report.get_filter_value("company"), is_group: 0, custom_is_province: 0}})
		}
	],
	onload(report) {
		report.page.add_inner_button(__("Update Delivery Dates"), () => update_delivery_dates(report));
		report.page.add_inner_button(__("Create DR for Confirmation"), () => create_delivery_notes(report));
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "item_code" && data) {
			const color = flt(data.actual_qty) >= flt(data.available_qty) ? "green" : "red";
			return `<span class="indicator ${color}">${value}</span>`;
		}
		return value;
	},
	get_datatable_options(options) { options.checkboxColumn = true; return options; }
};

function selected_rows(report) {
	return (report.datatable?.rowmanager?.getCheckedRows() || []).map(index => report.data[index]).filter(Boolean);
}

function update_delivery_dates(report) {
	const rows = selected_rows(report);
	if (!rows.length) return frappe.msgprint(__("Select at least one item row."));
	frappe.prompt({fieldname: "delivery_date", label: __("New Delivery Date"), fieldtype: "Date", reqd: 1}, values => {
		frappe.call({method: "qcmc_logic.qcmc_logics.report.sales_order_delivery_scheduling.sales_order_delivery_scheduling.update_delivery_dates", args: {so_details: rows.flatMap(row => row.so_details || [row.so_detail]), delivery_date: values.delivery_date}, callback: r => { if (!r.exc) { frappe.msgprint(r.message); report.refresh(); } }});
	}, __("Update"), __("Apply"));
}

function create_delivery_notes(report) {
	const so_details = [...new Set(selected_rows(report).flatMap(row => row.so_details || [row.so_detail]))];
	if (!so_details.length) return frappe.msgprint(__("Select at least one Sales Order item."));
	frappe.confirm(__("Create one Delivery Note per selected Sales Order and submit for Stock Confirmation?"), () => {
		frappe.call({method: "qcmc_logic.qcmc_logics.report.sales_order_delivery_scheduling.sales_order_delivery_scheduling.create_delivery_notes", args: {so_details}, freeze: true, freeze_message: __("Creating Delivery Notes..."), callback: r => { if (!r.exc) { frappe.msgprint(r.message); report.refresh(); } }});
	});
}
