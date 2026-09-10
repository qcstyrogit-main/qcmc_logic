frappe.query_reports["Delivery Note Stock Confirmation"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company")},
		{fieldname: "delivery_date", label: __("Delivery Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today()},
		{fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse", get_query: () => ({filters: {company: frappe.query_report.get_filter_value("company"), is_group: 0, custom_is_province: 0}})}
	],
	onload(report) {
		report.page.add_inner_button(__("Adjust Quantity"), () => adjust_quantity(report));
		report.page.add_inner_button(__("Remove Unavailable Items"), () => remove_items(report));
		report.page.add_inner_button(__("Submit For DR Printing"), () => confirm_delivery_notes(report));
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "item_code" && data) {
			const color = flt(data.actual_qty) >= flt(data.qty) ? "green" : "red";
			return `<span class="indicator ${color}">${value}</span>`;
		}
		return value;
	},
	get_datatable_options(options) { options.checkboxColumn = true; return options; }
};

function logistics_selected_rows(report) {
	return (report.datatable?.rowmanager?.getCheckedRows() || []).map(index => report.data[index]).filter(Boolean);
}

function confirm_delivery_notes(report) {
	const delivery_notes = [...new Set(logistics_selected_rows(report).map(row => row.delivery_note))];
	if (!delivery_notes.length) return frappe.msgprint(__("Select at least one Delivery Note row."));
	frappe.prompt({fieldname: "remarks", label: __("Stock Confirmation Remarks"), fieldtype: "Small Text"}, values => {
		frappe.call({method: "qcmc_logic.qcmc_logics.report.delivery_note_stock_confirmation.delivery_note_stock_confirmation.confirm_delivery_notes", args: {delivery_notes, remarks: values.remarks}, freeze: true, freeze_message: __("Updating workflow..."), callback: r => { if (!r.exc) { frappe.msgprint(r.message); report.refresh(); } }});
	}, __("Confirm Stock"), __("Submit For DR Printing"));
}

function adjust_quantity(report) {
	const rows = logistics_selected_rows(report);
	if (rows.length !== 1) return frappe.msgprint(__("Select exactly one item row to adjust."));
	const row = rows[0];
	frappe.prompt([
		{fieldname: "qty", label: __("Available Qty"), fieldtype: "Float", reqd: 1, default: row.qty},
		{fieldname: "remarks", label: __("Stock Availability Remarks"), fieldtype: "Small Text"}
	], values => {
		frappe.call({method: "qcmc_logic.qcmc_logics.report.delivery_note_stock_confirmation.delivery_note_stock_confirmation.adjust_item_quantity", args: {dn_detail: row.dn_detail, qty: values.qty, scheduling_date: report.get_filter_value("delivery_date"), remarks: values.remarks}, callback: r => { if (!r.exc) { frappe.msgprint(r.message); report.refresh(); } }});
	}, __("Adjust Quantity"), __("Apply"));
}

function remove_items(report) {
	const rows = logistics_selected_rows(report);
	if (!rows.length) return frappe.msgprint(__("Select at least one unavailable item row."));
	frappe.prompt([
		{fieldname: "reason_code", label: __("Reason"), fieldtype: "Select", options: "SA\nND", default: "SA", reqd: 1},
		{fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text", reqd: 1}
	], values => {
		frappe.call({method: "qcmc_logic.qcmc_logics.report.delivery_note_stock_confirmation.delivery_note_stock_confirmation.remove_items", args: {dn_details: rows.map(row => row.dn_detail), scheduling_date: report.get_filter_value("delivery_date"), reason_code: values.reason_code, remarks: values.remarks}, freeze: true, freeze_message: __("Removing unavailable items..."), callback: r => { if (!r.exc) { frappe.msgprint(r.message); report.refresh(); } }});
	}, __("Remove Items"), __("Remove"));
}
