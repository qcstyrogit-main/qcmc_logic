frappe.pages["delivery-note-printing-workbench"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({parent: wrapper, title: __("Delivery Note Printing Workbench"), single_column: true});
	new DeliveryNotePrintingWorkbench(page);
};

class DeliveryNotePrintingWorkbench {
	constructor(page) {
		this.page = page;
		this.rows = [];
		this.filters = {company: frappe.defaults.get_user_default("Company"), delivery_date: frappe.datetime.get_today(), warehouse: ""};
		this.setup_actions();
		this.setup_body();
		this.refresh();
	}

	setup_actions() {
		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
	}

	setup_body() {
		this.page.main.html(`<div class="dn-printing-workbench"><div class="dn-printing-filters"></div><div class="dn-printing-summary"></div><div class="dn-printing-guidance">${__("Each row is one Delivery Note. Its item list is grouped inside the row, and actions apply to the whole note. The date shown is the Delivery Note date. A DR number is assigned before preview, but does not prove it was physically printed. Submit for Delivery moves the note out of this queue. Draft invoices remain unsubmitted until actual delivery is finalized.")}</div><div class="dn-printing-grid"></div></div>`);
		this.$filters = this.page.main.find(".dn-printing-filters");
		this.$summary = this.page.main.find(".dn-printing-summary");
		this.$grid = this.page.main.find(".dn-printing-grid");
		frappe.dom.set_style(`.dn-printing-filters{padding:10px;border:1px solid var(--border-color);border-radius:6px;margin-bottom:10px;background:var(--fg-color)}.dn-printing-filter-row{display:flex;gap:12px;flex-wrap:wrap}.dn-printing-filter{min-width:220px}.dn-printing-summary,.dn-printing-guidance{font-size:14px;line-height:1.5}.dn-printing-guidance{margin:5px 0 12px}.dn-printing-grid .dt-scrollable{max-height:calc(100vh - 300px)}.dn-printing-grid .dt-cell__content{font-size:14px;line-height:1.4;white-space:nowrap!important;padding:10px 8px;min-height:48px}.dn-printing-grid .dt-cell--header .dt-cell__content{font-size:14px;font-weight:650;white-space:nowrap!important}.dn-printing-grid .dt-cell--filter .dt-cell__content{padding:5px}.dn-printing-grid .dt-cell--filter input{font-size:13px;min-height:32px}.dn-printing-row-actions{display:flex;gap:6px;align-items:center;white-space:nowrap}.dn-printing-row-actions .btn{font-size:13px;padding:5px 8px}.dn-printing-row-actions .btn[disabled]{opacity:.45}.dn-items-dialog .modal-body{max-height:65vh;overflow:auto}.dn-items-dialog .table{font-size:14px}.dn-items-dialog .table th{position:sticky;top:0;background:var(--fg-color);z-index:1}`);
		this.$filters.html(`<div class="dn-printing-filter-row"><div class="dn-printing-filter" data-field="company"></div><div class="dn-printing-filter" data-field="delivery_date"></div><div class="dn-printing-filter" data-field="warehouse"></div></div>`);
		this.company = this.make_filter("company", "Company", "Link", "Company");
		this.delivery_date = this.make_filter("delivery_date", "Delivery Note Date", "Date");
		this.warehouse = this.make_filter("warehouse", "Warehouse", "Link", "Warehouse");
	}

	make_filter(fieldname, label, fieldtype, options) {
		return frappe.ui.form.make_control({parent: this.$filters.find(`[data-field="${fieldname}"]`), df: {fieldname, label: __(label), fieldtype, options, default: this.filters[fieldname], reqd: fieldname !== "warehouse", get_query: fieldname === "warehouse" ? () => ({filters: {company: this.filters.company, is_group: 0, custom_is_province: 0}}) : undefined, change: () => {this.filters[fieldname] = this[fieldname].get_value(); this.refresh();}}, render_input: true});
	}

	refresh() {
		const request_id = this.refresh_request_id = (this.refresh_request_id || 0) + 1;
		if (!this.filters.company || !this.filters.delivery_date) {
			this.rows = [];
			this.$summary.text(__("Select a company and Delivery Note date."));
			this.render();
			return;
		}
		frappe.call({method: "qcmc_logic.qcmc_logics.page.delivery_note_printing_workbench.delivery_note_printing_workbench.get_data", args: {filters: {...this.filters}}, freeze: true, freeze_message: __("Loading Delivery Notes..."), callback: r => {if (!r.exc && request_id === this.refresh_request_id) {this.rows = r.message.rows || []; this.$summary.text(r.message.message || ""); this.render();}}});
	}

	render() {
		const esc = value => frappe.utils.escape_html(String(value ?? ""));
		const columns = [
			{id: "delivery_note", name: __("Delivery Note"), width: 165, editable: false, format: value => `<a href="/app/delivery-note/${encodeURIComponent(value)}">${esc(value)}</a>`},
			{id: "delivery_note_date", name: __("DN Date"), width: 130, editable: false},
			{id: "dr_number", name: __("DR Number"), width: 130, editable: false, format: value => esc(value || "")},
			{id: "print_readiness", name: __("Print Readiness"), width: 175, editable: false, format: (value, row, column, data) => data.dr_number ? `<span class="indicator-pill blue">${__("DR number assigned")}</span>` : `<span class="indicator-pill orange">${__("Ready to assign DR number")}</span>`},
			{id: "invoice_status", name: __("Invoice"), width: 190, editable: false, format: (value, row, column, data) => data.invoice_html},
			{id: "sales_order", name: __("Sales Order"), width: 125, editable: false},
			{id: "customer_name", name: __("Customer"), width: 230, editable: false},
			{id: "items_action", name: __("Items"), width: 145, editable: false, sortable: false, format: value => value},
			{id: "actions", name: __("Actions"), width: 300, editable: false, sortable: false, focusable: false, dropdown: false, format: value => value},
		];
		const data = this.rows.map(row => {
			const items_action = `<button class="btn btn-default btn-sm" data-action="items" data-dn="${esc(row.delivery_note)}"><i class="fa fa-list"></i> ${__("View {0} items", [row.items.length])}</button>`;
			const invoice_html = row.invoices.length ? row.invoices.map(invoice => `<a href="/app/sales-invoice/${encodeURIComponent(invoice.name)}">${esc(invoice.name)}</a> <span class="indicator-pill ${invoice.status === __("Draft") ? "orange" : "green"}">${esc(invoice.status)}</span>`).join("<br>") : `<span class="text-muted">${__("No accessible invoice linked")}</span>`;
			const invoice_label = row.invoices.length ? __("Preview Invoice") : __("Invoice");
			const actions = `<div class="dn-printing-row-actions"><button class="btn btn-default btn-sm" data-action="print" data-dn="${esc(row.delivery_note)}" title="${esc(row.dr_number ? __("Print DR") : __("Assign DR and Print"))}"><i class="fa fa-print"></i> ${row.dr_number ? __("Print") : __("Assign & Print")}</button><button class="btn btn-default btn-sm" data-action="invoice" data-dn="${esc(row.delivery_note)}" title="${esc(row.invoices.length ? __("Preview Invoice") : __("Create Draft Invoice"))}"><i class="fa fa-file-text-o"></i> ${invoice_label}</button><button class="btn btn-primary btn-sm" data-action="deliver" data-dn="${esc(row.delivery_note)}" ${row.dr_number ? "" : "disabled"} title="${esc(__("Submit for Delivery"))}"><i class="fa fa-truck"></i> ${__("Deliver")}</button></div>`;
			return {delivery_note: row.delivery_note, delivery_note_date: row.delivery_note_date, dr_number: row.dr_number || "", print_readiness: "", invoice_status: "", invoice_html, sales_order: row.sales_order || "", customer_name: row.customer_name || "", items_action, actions};
		});
		this.$grid.empty();
		this.datatable = new frappe.DataTable(this.$grid[0], {
			columns,
			data,
			layout: "fixed",
			inlineFilters: true,
			checkboxColumn: false,
			serialNoColumn: false,
			cellHeight: 58,
			dynamicRowHeight: true,
			noDataMessage: __("No Delivery Notes match the current filters."),
			language: frappe.boot.lang,
			translations: frappe.utils.datatable.get_translations(),
		});
		this.$grid.off("click.dnActions").on("click.dnActions", "[data-action]", event => {
			const button = $(event.currentTarget);
			const name = button.attr("data-dn");
			if (button.attr("data-action") === "items") this.show_items(name);
			if (button.attr("data-action") === "print") this.assign_and_print(name);
			if (button.attr("data-action") === "invoice") this.create_invoice(name);
			if (button.attr("data-action") === "deliver" && !button.prop("disabled")) this.submit_delivery(name);
		});
	}

	show_items(delivery_note) {
		const row = this.rows.find(candidate => candidate.delivery_note === delivery_note);
		if (!row) return;
		const esc = value => frappe.utils.escape_html(String(value ?? ""));
		const item_rows = row.items.map(item => `<tr><td><a href="/app/item/${encodeURIComponent(item.item_code)}">${esc(item.item_code)}</a></td><td>${esc(item.item_name)}</td><td class="text-right">${format_number(item.qty)}</td><td>${esc(item.warehouse)}</td></tr>`).join("");
		const dialog = new frappe.ui.Dialog({title: __("Items in {0}", [row.delivery_note]), fields: [{fieldtype: "HTML", fieldname: "items_html"}]});
		dialog.$wrapper.addClass("dn-items-dialog");
		dialog.fields_dict.items_html.$wrapper.html(`<div class="table-responsive"><table class="table table-bordered"><thead><tr><th>${__("Item Code")}</th><th>${__("Item Name")}</th><th class="text-right">${__("Quantity")}</th><th>${__("Warehouse")}</th></tr></thead><tbody>${item_rows}</tbody></table></div>`);
		dialog.show();
		dialog.$wrapper.find(".modal-dialog").addClass("modal-lg");
	}

	assign_and_print(delivery_note) {
		let preview = null;
		let preview_started = false;
		const existing_row = this.rows.find(row => row.delivery_note === delivery_note);
		const dialog = new frappe.ui.Dialog({title: existing_row && existing_row.dr_number ? __("Confirm DR Number") : __("Assign DR Number"), fields: [{fieldname: "dr_number", label: __("DR Number"), fieldtype: "Data", default: existing_row ? existing_row.dr_number : "", reqd: 1}], primary_action_label: __("Save and Preview"), primary_action: values => {
			const dr_number = String(values.dr_number || "").trim();
			if (!dr_number) return;
			// Open only after the clerk confirms Save and Preview, within that user gesture.
			preview = window.open("about:blank", "_blank");
			if (!preview) return frappe.msgprint({title: __("Popup blocked"), message: __("Allow popups for this ERPNext site, then click Save and Preview again. The DR number was not saved."), indicator: "orange"});
			preview.document.write(`<title>${__("Preparing DR Preview")}</title><p style="font:16px sans-serif;padding:24px">${__("Saving and verifying the DR number…")}</p>`);
			frappe.call({method: "qcmc_logic.qcmc_logics.page.delivery_note_printing_workbench.delivery_note_printing_workbench.assign_dr_number", args: {delivery_note, dr_number}, freeze: true, callback: r => {
				if (r.exc) {if (preview && !preview.closed) preview.close(); return;}
				const result = r.message;
				if (!result || result.delivery_note !== delivery_note || result.dr_number !== dr_number || !result.print_format) {
					if (preview && !preview.closed) preview.close();
					return frappe.msgprint({title: __("DR Number Not Verified"), message: __("The server did not confirm that this DR number was saved. The print preview was not opened. Refresh and try again."), indicator: "red"});
				}
				dialog.hide();
				const url = `/printview?doctype=${encodeURIComponent("Delivery Note")}&name=${encodeURIComponent(result.delivery_note)}&format=${encodeURIComponent(result.print_format)}&no_letterhead=0`;
				preview_started = true;
				preview.location.replace(url);
				this.refresh();
			}});
		}});
		dialog.$wrapper.on("hidden.bs.modal", () => {if (!preview_started && preview && !preview.closed) preview.close();});
		dialog.show();
	}

	create_invoice(delivery_note) {
		const row = this.rows.find(candidate => candidate.delivery_note === delivery_note);
		if (row?.invoices?.length) return this.preview_invoice(delivery_note, row.invoices);
		if (!row || !String(row.dr_number || "").trim()) {
			return frappe.msgprint({title: __("DR Number Required"), message: __("Assign a DR Number before creating the Sales Invoice for {0}.", [delivery_note]), indicator: "orange"});
		}
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
						method: "qcmc_logic.qcmc_logics.page.delivery_note_printing_workbench.delivery_note_printing_workbench.verify_sales_invoice_for_preview",
						args: {delivery_note, sales_invoice: candidate_invoice, invoice_number},
						callback: verification => {
							this.refresh();
							if (verification.exc || !verification.message?.verified || verification.message.invoice_number !== invoice_number || verification.message.dr_number !== String(row.dr_number).trim() || (candidate_invoice && verification.message.sales_invoice !== candidate_invoice)) {
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
					method: "qcmc_logic.qcmc_logics.page.delivery_note_printing_workbench.delivery_note_printing_workbench.create_sales_invoices",
					args: {delivery_notes: [delivery_note], invoice_number},
					freeze: true,
					freeze_message: __("Creating draft Sales Invoice…"),
					callback: r => {
						const result = r.message;
						const candidate_invoice = !r.exc && result && result.delivery_note === delivery_note && result.invoice_number === invoice_number && result.dr_number === String(row.dr_number).trim() ? result.sales_invoice : null;
						verify_saved_invoice(candidate_invoice);
					},
					error: () => { if (preview && !preview.closed) preview.close(); this.refresh(); }
				});
			}
		});
		dialog.$wrapper.on("hidden.bs.modal", () => {if (!preview_started && preview && !preview.closed) preview.close();});
		dialog.show();
	}

	preview_invoice(delivery_note, invoices) {
		if (invoices.length !== 1) return frappe.msgprint(__("Multiple invoices are linked. Open the Delivery Note to resolve its invoice references."));
		const preview = window.open("about:blank", "_blank");
		if (!preview) return frappe.msgprint(__("Allow popups for this ERPNext site to preview the invoice."));
		frappe.call({
			method: "qcmc_logic.qcmc_logics.page.delivery_note_printing_workbench.delivery_note_printing_workbench.verify_sales_invoice_for_preview",
			args: {delivery_note, sales_invoice: invoices[0].name},
			callback: r => {
				if (r.exc || !r.message?.verified) { preview.close(); return; }
				preview.location.replace(`/printview?doctype=Sales%20Invoice&name=${encodeURIComponent(r.message.sales_invoice)}&no_letterhead=0`);
			},
			error: () => preview.close()
		});
	}

	submit_delivery(delivery_note) {
		frappe.confirm(__("Submit Delivery Note {0} for delivery?", [delivery_note]), () => frappe.call({method: "qcmc_logic.qcmc_logics.page.delivery_note_printing_workbench.delivery_note_printing_workbench.submit_for_delivery", args: {delivery_notes: [delivery_note]}, freeze: true, callback: r => {if (!r.exc) {frappe.msgprint(r.message); this.refresh();}}}));
	}
}
