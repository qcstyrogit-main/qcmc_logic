frappe.ui.form.on("Role Profile Territory", {
	validate(frm) {
		set_single_territory_as_default(frm);
	},
});

frappe.ui.form.on("Role Profile Territory Detail", {
	allowed_territories_add(frm) {
		set_single_territory_as_default(frm);
	},

	allowed_territories_remove(frm) {
		set_single_territory_as_default(frm);
	},
});

function set_single_territory_as_default(frm) {
	const rows = frm.doc.allowed_territories || [];
	if (rows.length === 1 && !rows[0].is_default) {
		frappe.model.set_value(rows[0].doctype, rows[0].name, "is_default", 1);
	}
}

