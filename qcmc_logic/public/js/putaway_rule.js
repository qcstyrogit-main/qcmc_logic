frappe.ui.form.on("Putaway Rule", {
	refresh(frm) {
		frm.set_df_property("priority", "read_only", 1);
		frm.set_df_property("priority", "hidden", frm.is_new() ? 1 : 0);
		frm.set_df_property("priority", "description", __("Assigned automatically on save. Use Manage Location Order to change the sequence."));
		if (!frm.is_new() && frm.perm?.[0]?.write) {
			frm.add_custom_button(__("Manage Location Order"), () => qcmc_manage_putaway_order(frm));
		}
		frm.trigger("custom_no_item_restriction");
		frm.trigger("custom_no_capacity_restriction");
	},

	custom_no_item_restriction(frm) {
		const unrestricted = cint(frm.doc.custom_no_item_restriction);
		const item_fields = ["item_code", "item_name", "uom", "conversion_factor", "stock_uom"];

		item_fields.forEach((fieldname) => {
			frm.set_df_property(fieldname, "hidden", unrestricted);
		});
		frm.set_df_property("item_code", "reqd", !unrestricted);

		if (unrestricted && frm.doc.item_code) {
			frm.set_value("item_code", "");
		}
		if (unrestricted) {
			frm.set_value("item_name", "");
			frm.set_value("uom", "");
			frm.set_value("stock_uom", "");
			frm.set_value("conversion_factor", 1);
		}
		frm.trigger("custom_no_capacity_restriction");
	},

	custom_no_capacity_restriction(frm) {
		const unrestricted = cint(frm.doc.custom_no_capacity_restriction);
		const no_item_restriction = cint(frm.doc.custom_no_item_restriction);
		const capacity_fields = ["capacity", "stock_capacity"];
		const item_capacity_fields = ["uom", "conversion_factor", "stock_uom"];

		capacity_fields.forEach((fieldname) => {
			frm.set_df_property(fieldname, "hidden", unrestricted);
		});
		item_capacity_fields.forEach((fieldname) => {
			frm.set_df_property(fieldname, "hidden", unrestricted || no_item_restriction);
		});
		frm.set_df_property("capacity", "reqd", !unrestricted);

		if (unrestricted) {
			frm.set_value("capacity", 0);
			frm.set_value("stock_capacity", 0);
		}
	},
});

async function qcmc_manage_putaway_order(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save your changes before managing the location order."));
		return;
	}
	const response = await frappe.call({
		method: "qcmc_logic.putaway_priority.get_priority_order",
		args: {rule_name: frm.doc.name},
	});
	const order = response.message;
	if (!order) return;
	const dialog = new frappe.ui.Dialog({
		title: __("Manage Location Order"), size: "large",
		fields: [
			{fieldtype: "HTML", options: `<p>${__("The first row fills first. Drag rows, or select one row and use Move Up or Move Down. Disabled rules keep their positions.")}</p>`},
			{
				fieldname: "rules", fieldtype: "Table", label: __("Location Order"),
				cannot_add_rows: true, cannot_delete_rows: true, in_place_edit: false,
				data: order.rules.map((rule, index) => ({...rule, idx: index + 1})),
				fields: [
					{fieldname: "rule", label: __("Rule"), fieldtype: "Link", options: "Putaway Rule", read_only: 1, in_list_view: 1, columns: 3},
					{fieldname: "location", label: __("Location"), fieldtype: "Link", options: "Storage Location", read_only: 1, in_list_view: 1, columns: 5},
					{fieldname: "disabled", label: __("Disabled"), fieldtype: "Check", read_only: 1, in_list_view: 1, columns: 2},
				],
			},
		],
		primary_action_label: __("Save Order"),
		async primary_action() {
			const button = dialog.get_primary_btn();
			button.prop("disabled", true);
			try {
				await frappe.call({
					method: "qcmc_logic.putaway_priority.save_priority_order",
					args: {
						rule_name: frm.doc.name,
						ordered_rules: dialog.fields_dict.rules.grid.get_data().map(row => row.rule),
						version: order.version,
					},
					freeze: true, freeze_message: __("Saving location order..."),
				});
				dialog.hide();
				await frm.reload_doc();
				frappe.show_alert({message: __("Location order saved"), indicator: "green"});
			} finally {
				button.prop("disabled", false);
			}
		},
	});
	dialog.show();
	const grid = dialog.fields_dict.rules.grid;
	grid.add_custom_button(__("Move Up"), () => qcmc_move_putaway_order_row(grid, -1));
	grid.add_custom_button(__("Move Down"), () => qcmc_move_putaway_order_row(grid, 1));
}

function qcmc_move_putaway_order_row(grid, direction) {
	const selected = grid.get_selected_children();
	if (selected.length !== 1) {
		frappe.msgprint(__("Select one location to move."));
		return;
	}
	const rows = grid.get_data();
	const index = rows.findIndex(row => row.rule === selected[0].rule);
	const destination = index + direction;
	if (index < 0 || destination < 0 || destination >= rows.length) return;
	[rows[index], rows[destination]] = [rows[destination], rows[index]];
	rows.forEach((row, position) => {row.idx = position + 1;});
	grid.refresh();
}
