frappe.ui.form.on("Putaway Rule", {
	refresh(frm) {
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
