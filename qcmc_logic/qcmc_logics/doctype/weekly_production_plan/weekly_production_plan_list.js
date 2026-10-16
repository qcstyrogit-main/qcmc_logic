frappe.listview_settings["Weekly Production Plan"] = {
	onload(listview) {
		listview.page.add_action_item(__("Delete Selected"), async () => {
			const selected = listview.get_checked_items();
			if (!selected.length) {
				frappe.msgprint(__("Select at least one Weekly Production Plan to delete."));
				return;
			}

			const finalPlans = selected.filter((row) => row.docstatus === 1);
			if (finalPlans.length) {
				frappe.msgprint(__("Final plans must be cancelled before they can be deleted."));
				return;
			}

			frappe.confirm(
				__("Permanently delete {0} selected Weekly Production Plan(s)?", [selected.length]),
				async () => {
					for (const row of selected) {
						await frappe.call({
							method: "frappe.client.delete",
							args: { doctype: "Weekly Production Plan", name: row.name },
							freeze: true,
							freeze_message: __("Deleting {0}...", [row.name]),
						});
					}
					frappe.show_alert({ message: __("Selected production plan(s) deleted."), indicator: "green" });
					listview.refresh();
				},
			);
		});
	},
};
