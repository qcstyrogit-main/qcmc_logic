frappe.ui.form.on("Mode of Payment", {
	setup(frm) {
		frm.set_query("default_account", "accounts", function(doc, cdt, cdn) {
			const row = locals[cdt][cdn];
			const mode_of_payment = doc.mode_of_payment || "";

			if (/collected by/i.test(mode_of_payment)) {
				return {
					filters: [
						["Account", "account_type", "=", "Current Asset"],
						["Account", "account_name", "like", "%Advances%"],
						["Account", "is_group", "=", 0],
						["Account", "company", "=", row.company],
					],
				};
			}

			return {
				filters: [
					["Account", "account_type", "in", ["Bank", "Cash", "Receivable"]],
					["Account", "is_group", "=", 0],
					["Account", "company", "=", row.company],
				],
			};
		});
	},
});
