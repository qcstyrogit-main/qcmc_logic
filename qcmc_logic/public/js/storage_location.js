frappe.ui.form.on("Storage Location", {
	refresh(frm) {
		if (!frm.is_new() && frappe.model.can_create("Putaway Rule")) {
			frm.add_custom_button(__("Create Putaway Rule"), async () => {
				const warehouse = frm.doc.custom_warehouse;
				const warehouse_result = warehouse
					? await frappe.db.get_value("Warehouse", warehouse, "company")
					: { message: {} };
				const route_options = {
					company: warehouse_result.message?.company || undefined,
					warehouse: warehouse || undefined,
					item_code: frm.doc.custom_restricted_item || undefined,
					location: frm.doc.name,
					priority: 1,
				};
				if (flt(frm.doc.custom_storage_capacity) > 0) {
					route_options.capacity = frm.doc.custom_storage_capacity;
				}

				frappe.route_options = route_options;
				frappe.new_doc("Putaway Rule");
			});
		}

		frm.rename_doc = () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Rename Storage Location"),
				fields: [
					{
						fieldname: "location_code",
						fieldtype: "Data",
						label: __("New Location Code"),
						reqd: 1,
						default: frm.doc.location_code || frm.doc.name,
					},
					{
						fieldname: "location_name",
						fieldtype: "Data",
						label: __("New Location Name"),
						reqd: 1,
						default: frm.doc.location_name,
					},
				],
				primary_action_label: __("Rename"),
				primary_action(values) {
					dialog.disable_primary_action();
					frappe.call({
						method: "qcmc_logic.qcmc_logics.doctype.storage_location.storage_location.rename_storage_location",
						args: {
							storage_location: frm.doc.name,
							location_code: values.location_code,
							location_name: values.location_name,
						},
						freeze: true,
						freeze_message: __("Renaming Storage Location..."),
					}).then((response) => {
						dialog.hide();
						frappe.show_alert({ message: __("Storage Location renamed"), indicator: "green" });
						frappe.set_route("Form", "Storage Location", response.message.name);
					}).catch(() => dialog.enable_primary_action());
				},
			});
			dialog.show();
		};
	},
});
