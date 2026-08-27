frappe.listview_settings["Storage Location"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Print Selected QR Labels"), () => {
			const selected = listview.get_checked_items().map((row) => row.name);
			if (!selected.length) {
				frappe.msgprint(__("Select at least one Storage Location to print."));
				return;
			}

			const query = new URLSearchParams({ locations: JSON.stringify(selected) });
			window.open(`/storage_location_qr?${query.toString()}`, "_blank", "noopener");
		});
	},
};
