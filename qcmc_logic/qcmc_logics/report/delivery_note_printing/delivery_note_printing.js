frappe.query_reports["Delivery Note Printing"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company")},
		{fieldname: "delivery_date", label: __("Delivery Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today()},
		{fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse", get_query: () => ({filters: {company: frappe.query_report.get_filter_value("company"), is_group: 0, custom_is_province: 0}})}
	],
	onload(report) {
		report.page.add_inner_button(__("Print DR"), () => assign_and_print(report));
		report.page.add_inner_button(__("Submit for Delivery"), () => submit_for_delivery(report));
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

function invoicing_selected_rows(report) {
	return (report.datatable?.rowmanager?.getCheckedRows() || []).map(index => report.data[index]).filter(Boolean);
}

function assign_and_print(report) {
	const rows = invoicing_selected_rows(report);
	const delivery_notes = [...new Set(rows.map(row => row.delivery_note))];
	if (delivery_notes.length !== 1) return frappe.msgprint(__("Select rows from exactly one Delivery Note to print."));
	const row = rows[0];
	frappe.prompt(
		{fieldname: "dr_number", label: __("DR Number"), fieldtype: "Data", reqd: 1, default: row.dr_number || ""},
		values => {
			const preview = window.open("", "_blank");
			frappe.call({
				method: "qcmc_logic.qcmc_logics.report.delivery_note_printing.delivery_note_printing.assign_dr_number",
				args: {delivery_note: delivery_notes[0], dr_number: values.dr_number},
				freeze: true,
				freeze_message: __("Saving DR Number..."),
				callback: response => {
					if (response.exc) { preview?.close(); return; }
					const result = response.message;
					report.refresh();
					const url = `/printview?doctype=${encodeURIComponent("Delivery Note")}&name=${encodeURIComponent(result.delivery_note)}&format=${encodeURIComponent(result.print_format)}&no_letterhead=0`;
					if (preview) preview.location = url;
					else frappe.msgprint(__("Allow popups to open the print preview."));
				}
			});
		},
		__("Assign DR Number"),
		__("Save and Preview")
	);
}

function submit_for_delivery(report) {
	const delivery_notes = [...new Set(invoicing_selected_rows(report).map(row => row.delivery_note))];
	if (!delivery_notes.length) return frappe.msgprint(__("Select at least one Delivery Note row."));
	frappe.confirm(
		__("Submit {0} Delivery Note(s) for delivery?", [delivery_notes.length]),
		() => frappe.call({
			method: "qcmc_logic.qcmc_logics.report.delivery_note_printing.delivery_note_printing.submit_for_delivery",
			args: {delivery_notes},
			freeze: true,
			freeze_message: __("Submitting Delivery Notes..."),
			callback: response => { if (!response.exc) { frappe.msgprint(response.message); report.refresh(); } }
		})
	);
}
