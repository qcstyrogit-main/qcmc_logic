frappe.ui.form.on("HMO External Member", {
	rate_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.rate_code) {
			frappe.model.set_value(cdt, cdn, { level: "", mbl: 0 });
			return;
		}

		const separator = row.rate_code.lastIndexOf("-");
		const rate_group = row.rate_code.slice(0, separator);
		const mbl = flt(row.rate_code.slice(separator + 1));
		frappe.model.set_value(cdt, cdn, {
			level: row.member_type === "Principal" ? rate_group : "",
			mbl,
		});
	},
});
