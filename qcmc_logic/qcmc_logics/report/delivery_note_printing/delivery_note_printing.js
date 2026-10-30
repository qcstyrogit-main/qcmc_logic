frappe.query_reports["Delivery Note Printing"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company")},
		{fieldname: "delivery_date", label: __("Delivery Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today()},
		{fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse", get_query: () => ({filters: {company: frappe.query_report.get_filter_value("company"), is_group: 0, custom_is_province: 0}})}
	],
	onload(report) {
		report.page.add_inner_button(__("Print DR"), () => assign_and_print(report));
		report.page.add_inner_button(__("Create Invoice"), () => create_invoices(report));
		report.page.add_inner_button(__("Submit for Delivery"), () => submit_for_delivery(report));
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
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

function create_invoices(report) {
	const delivery_notes = [...new Set(invoicing_selected_rows(report).map(row => row.delivery_note))];
	if (!delivery_notes.length) return frappe.msgprint(__("Select at least one Delivery Note row."));
	if (delivery_notes.length !== 1) return frappe.msgprint(__("Create an invoice for exactly one Delivery Note at a time."));
	const selected_row = invoicing_selected_rows(report).find(row => row.delivery_note === delivery_notes[0]);
	if (!selected_row?.dr_number) return frappe.msgprint({title: __("DR Number Required"), message: __("Assign a DR Number before creating the Sales Invoice for {0}.", [delivery_notes[0]]), indicator: "orange"});
	let preview = null;
	let preview_started = false;
	const dialog = new frappe.ui.Dialog({
		title: __("Create Draft Invoice"),
		fields: [{fieldname: "invoice_number", label: __("Invoice Number"), fieldtype: "Data", length: 10, reqd: 1}],
		primary_action_label: __("Create and Preview"),
		primary_action: values => {
			const invoice_number = String(values.invoice_number || "").trim();
			if (!invoice_number) return;
			preview = window.open("about:blank", "_blank");
			if (!preview) return frappe.msgprint({title: __("Popup blocked"), message: __("Allow popups for this ERPNext site, then click Create and Preview again. No invoice was created."), indicator: "orange"});
			preview.document.write(`<title>${__("Preparing Invoice Preview")}</title><p style="font:16px sans-serif;padding:24px">${__("Creating and verifying the draft invoice…")}</p>`);
			const verify_saved_invoice = candidate_invoice => {
				frappe.call({
					method: "qcmc_logic.qcmc_logics.report.delivery_note_printing.delivery_note_printing.verify_sales_invoice_for_preview",
					args: {delivery_note: delivery_notes[0], sales_invoice: candidate_invoice, invoice_number},
					callback: verification => {
						report.refresh();
						if (verification.exc || !verification.message?.verified || verification.message.invoice_number !== invoice_number || verification.message.dr_number !== selected_row.dr_number || (candidate_invoice && verification.message.sales_invoice !== candidate_invoice)) {
							if (preview && !preview.closed) preview.close();
							const invoice_name = verification.message?.sales_invoice || candidate_invoice;
							const invoice_link = invoice_name ? `<br><a href="/app/sales-invoice/${encodeURIComponent(invoice_name)}">${frappe.utils.escape_html(invoice_name)}</a>` : "";
							return frappe.msgprint({title: __("Invoice Not Verified"), message: __("No saved draft invoice with matching invoice and DR references could be verified. Print preview was not opened.{0}", [invoice_link]), indicator: "orange"});
						}
						dialog.hide();
						preview_started = true;
						preview.location.replace(`/printview?doctype=${encodeURIComponent("Sales Invoice")}&name=${encodeURIComponent(verification.message.sales_invoice)}&no_letterhead=0`);
					},
					error: () => {
						if (preview && !preview.closed) preview.close();
						frappe.msgprint({title: __("Invoice Not Verified"), message: __("The saved invoice could not be verified. Print preview was not opened."), indicator: "orange"});
					}
				});
			};
			frappe.call({
				method: "qcmc_logic.qcmc_logics.report.delivery_note_printing.delivery_note_printing.create_sales_invoices",
				args: {delivery_notes, invoice_number},
				freeze: true,
				freeze_message: __("Creating draft Sales Invoice…"),
				callback: response => {
					const result = response.message;
					const candidate_invoice = !response.exc && result && result.delivery_note === delivery_notes[0] && result.invoice_number === invoice_number && result.dr_number === selected_row.dr_number ? result.sales_invoice : null;
					verify_saved_invoice(candidate_invoice);
				},
				error: () => verify_saved_invoice(null)
			});
		}
	});
	dialog.$wrapper.on("hidden.bs.modal", () => {if (!preview_started && preview && !preview.closed) preview.close();});
	dialog.show();
}
