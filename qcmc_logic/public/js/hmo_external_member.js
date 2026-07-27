frappe.ui.form.on("HMO External Member", {
	rate_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.rate_code) return;
		const separator = row.rate_code.lastIndexOf("-");
		frappe.model.set_value(cdt, cdn, {
			level: row.member_type === "Principal" ? row.rate_code.slice(0, separator) : "",
			mbl: flt(row.rate_code.slice(separator + 1)),
		});
	},
});
