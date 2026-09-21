frappe.listview_settings["Warehouse Allocation"] = {
	add_fields: ["status"],
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
					? __("The selected Warehouse Allocation is already {0}.", [checked[0].status])
					: __("Select at least one Draft or In Progress Warehouse Allocation."));
				return;
			}
			frappe.confirm(
				__("Abandon {0} selected Warehouse Allocation(s)? Their location reservations will be released.", [selected.length]),
				() => Promise.all(selected.map(doc => frappe.call({
					method: "qcmc_logic.qcmc_logics.doctype.warehouse_allocation.warehouse_allocation.abandon_allocation",
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
