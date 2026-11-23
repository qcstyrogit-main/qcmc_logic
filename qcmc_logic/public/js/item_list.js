(() => {
	const settings = frappe.listview_settings.Item || {};
	const original_onload = settings.onload;
	settings.onload = function (listview) {
		original_onload?.(listview);
		const printSelected = () => {
			const items = listview.get_checked_items().map((item) => item.name);
			if (!items.length || items.length > 100) {
				frappe.msgprint(__("Select between 1 and 100 Items."));
				return;
			}
			const dialog = new frappe.ui.Dialog({
				title: __("Print Material Scanner QR"),
				fields: [{ fieldname: "pack_type", fieldtype: "Select", label: __("Pack Type"),
					options: ["Standard Pack", "Big Pack Qty"], default: "Big Pack Qty", reqd: 1 }],
				primary_action_label: __("Open QR Labels"),
				primary_action(values) {
					const query = new URLSearchParams({ items: JSON.stringify(items),
						pack_type: values.pack_type === "Standard Pack" ? "standard" : "big" });
					window.open(`/material_scanner_qr?${query.toString()}`, "_blank", "noopener");
					dialog.hide();
				},
			});
			dialog.show();
		};
		listview.page.add_inner_button(__("Print Selected QR Labels"), printSelected);
		listview.page.add_actions_menu_item(__("Print Material Scanner QR"), printSelected);
	};
	frappe.listview_settings.Item = settings;
})();
