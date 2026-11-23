frappe.listview_settings["Storage Allocation"] = {
	add_fields: ["status", "source_doctype", "source_document_count"],
	formatters: {
		source_document(value, df, doc) {
			if (doc.source_document_count > 1) {
				const label = __("Multiple documents ({0})", [doc.source_document_count]);
				return `<span>${frappe.utils.escape_html(label)}</span>`;
			}
			if (!value || !doc.source_doctype) return "";
			return frappe.utils.get_form_link(doc.source_doctype, value, true, frappe.utils.escape_html(value));
		},
	},
	has_indicator_for_draft: true,
	has_indicator_for_cancelled: true,
	onload(listview) {
		listview.page.add_action_item(__("Abandon Allocation"), () => {
			const checked = listview.get_checked_items();
			const selected = checked.filter(
				doc => doc.docstatus === 0 && ["Draft", "In Progress"].includes(doc.status)
			);
			if (!selected.length) {
				const already_closed = checked.length && checked.every(
					doc => ["Cancelled", "Completed"].includes(doc.status)
				);
				frappe.msgprint(already_closed
					? __("The selected Storage Allocation is already {0}.", [checked[0].status])
					: __("Select at least one Draft or In Progress Storage Allocation."));
				return;
			}
			frappe.confirm(
				__("Abandon {0} selected Storage Allocation(s)? Their location reservations will be released.", [selected.length]),
				() => Promise.all(selected.map(doc => frappe.call({
					method: "qcmc_logic.qcmc_logics.doctype.storage_allocation.storage_allocation.abandon_allocation",
					args: { name: doc.name },
				}))).then(() => listview.refresh())
			);
		});
	},
	get_indicator(doc) {
		const indicators = {
			Cancelled: [__("Cancelled"), "gray", "status,=,Cancelled"],
			Completed: [__("Completed"), "green", "status,=,Completed"],
			"In Progress": [__("In Progress"), "orange", "status,=,In Progress"],
			Draft: [__("Draft"), "red", "status,=,Draft"],
		};
		return indicators[doc.status] || [__(doc.status || "Draft"), "gray", `status,=,${doc.status || "Draft"}`];
	},
};
