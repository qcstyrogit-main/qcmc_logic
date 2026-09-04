frappe.provide("qcmc_logic.warehouse_allocation");

frappe.ui.form.on("Warehouse Allocation", {
	refresh(frm) {
		qcmc_logic.warehouse_allocation.toggle_scanner_fields(frm);
		qcmc_logic.warehouse_allocation.add_get_items_button(frm);
	},
});

qcmc_logic.warehouse_allocation.toggle_scanner_fields = function(frm) {
	const scanner_handover = Boolean(frm.doc.handover);
	["handover", "transaction_type", "posting_time", "picker", "checker", "device_id", "completed_at"].forEach(fieldname => {
		frm.set_df_property(fieldname, "hidden", scanner_handover ? 0 : 1);
	});
};

qcmc_logic.warehouse_allocation.source_doctypes = [
	"Stock Entry",
	"Warehouse Transfer",
	"Purchase Receipt",
	"Delivery Note",
	"Sales Invoice",
];

qcmc_logic.warehouse_allocation.add_get_items_button = function(frm) {
	if (frm.doc.docstatus !== 0) return;

	frm.add_custom_button(__("Get Items From"), () => {
		qcmc_logic.warehouse_allocation.open_source_dialog(frm);
	});
};

qcmc_logic.warehouse_allocation.open_source_dialog = function(frm) {
	if (!frm.doc.company || !frm.doc.warehouse) {
		frappe.msgprint(__("Please select Company and Warehouse first."));
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Get Items From"),
		size: "extra-large",
		fields: [
			{
				fieldtype: "Select",
				fieldname: "source_doctype",
				label: __("Source Document Type"),
				options: qcmc_logic.warehouse_allocation.source_doctypes.join("\n"),
				reqd: 1,
				onchange() {
					qcmc_logic.warehouse_allocation.load_documents(frm, dialog);
				},
			},
			{
				fieldtype: "HTML",
				fieldname: "documents_html",
			},
		],
		primary_action_label: __("Get Items"),
		primary_action() {
			const values = dialog.get_values();
			if (!values) return;

			const selected = [];
			dialog.$wrapper.find(".wa-document-check:checked").each(function() {
				selected.push($(this).data("name"));
			});

			if (!selected.length) {
				frappe.msgprint(__("Select at least one document."));
				return;
			}

			qcmc_logic.warehouse_allocation.get_items(frm, dialog, values.source_doctype, selected);
		},
	});

	dialog.show();
	dialog.set_value("source_doctype", "Stock Entry");
	qcmc_logic.warehouse_allocation.load_documents(frm, dialog);
};

qcmc_logic.warehouse_allocation.load_documents = function(frm, dialog) {
	const source_doctype = dialog.get_value("source_doctype");
	if (!source_doctype) return;

	frappe.call({
		method: "qcmc_logic.qcmc_logics.doctype.warehouse_allocation.warehouse_allocation.get_receiving_documents",
		args: {
			source_doctype,
			company: frm.doc.company,
			warehouse: frm.doc.warehouse,
		},
		freeze: true,
		callback(r) {
			const documents = r.message || [];
			qcmc_logic.warehouse_allocation.render_documents(dialog, documents);
		},
	});
};

qcmc_logic.warehouse_allocation.render_documents = function(dialog, documents) {
	const rows = documents.map(document => `
		<tr>
			<td style="width: 32px">
				<input type="checkbox" class="wa-document-check" data-name="${frappe.utils.escape_html(document.name)}">
			</td>
			<td>${frappe.utils.escape_html(document.name || "")}</td>
			<td>${frappe.utils.escape_html(document.posting_date || "")}</td>
			<td>${frappe.utils.escape_html(document.company || "")}</td>
			<td>${frappe.utils.escape_html(document.stock_entry_type || document.transfer_status || document.supplier || document.customer || "")}</td>
		</tr>
	`).join("");

	const html = documents.length ? `
		<table class="table table-bordered table-sm">
			<thead>
				<tr>
					<th style="width: 32px"><input type="checkbox" class="wa-select-all-documents"></th>
					<th>${__("Document")}</th>
					<th>${__("Date")}</th>
					<th>${__("Company")}</th>
					<th>${__("Type / Party")}</th>
				</tr>
			</thead>
			<tbody>${rows}</tbody>
		</table>
	` : `<p class="text-muted">${__("No eligible receiving documents found for this Company and Warehouse.")}</p>`;

	dialog.fields_dict.documents_html.$wrapper.html(html);
	dialog.$wrapper.off("change.warehouse_allocation").on("change.warehouse_allocation", ".wa-select-all-documents", function() {
		dialog.$wrapper.find(".wa-document-check").prop("checked", $(this).is(":checked"));
	});
};

qcmc_logic.warehouse_allocation.get_items = function(frm, dialog, source_doctype, documents) {
	frappe.call({
		method: "qcmc_logic.qcmc_logics.doctype.warehouse_allocation.warehouse_allocation.get_items_from_documents",
		args: {
			source_doctype,
			documents,
			company: frm.doc.company,
			warehouse: frm.doc.warehouse,
		},
		freeze: true,
		callback(r) {
			const data = r.message || {};
			frm.clear_table("references");
			frm.clear_table("items");
			frm.clear_table("locations");

			(data.references || []).forEach(reference => {
				const row = frm.add_child("references");
				row.reference_doctype = reference.source_doctype;
				row.reference_name = reference.source_name;
				row.item_code = reference.item_code;
				row.qty = flt(reference.qty || 0);
				row.uom = reference.uom;
			});

			(data.items || []).forEach(item => {
				const row = frm.add_child("items");
				row.item_code = item.item_code;
				row.uom = item.uom;
				row.qty = flt(item.qty || 0);
				row.putaway_qty = flt(item.putaway_qty || 0);
				row.remaining_qty = flt(item.remaining_qty || item.qty || 0);
			});

			frm.refresh_field("references");
			frm.refresh_field("items");
			frm.refresh_field("locations");
			dialog.hide();
		},
	});
};
