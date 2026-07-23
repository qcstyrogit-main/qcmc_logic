frappe.ui.form.on("Mode of Payment", {
	setup(frm) {
		frm.set_query("default_account", "accounts", function(doc, cdt, cdn) {
			const row = locals[cdt][cdn];
			const account_types = ["Bank", "Cash", "Receivable"];

			if (doc.mode_of_payment === "Intercompany Collection") {
				account_types.push("Current Asset");
			}

			return {
				filters: [
					["Account", "account_type", "in", account_types],
					["Account", "is_group", "=", 0],
					["Account", "company", "=", row.company],
				],
			};
		});
	},
});
