frappe.ui.form.on("Item", {
	setup(frm) {
		frm.set_query("custom_eps_process_main_item", () => {
			return {
				filters: {
					custom_is_eps_process_main_item: 1,
					disabled: 0,
				},
			};
		});
	},

	custom_is_eps_process_main_item(frm) {
		if (cint(frm.doc.custom_is_eps_process_main_item)) {
			frm.set_value("custom_eps_process_main_item", "");
		}
	},

	validate(frm) {
		if (
			frm.doc.custom_eps_process_main_item
			&& frm.doc.custom_eps_process_main_item === frm.doc.name
		) {
			frappe.throw(__("EPS Process Main Item cannot point to the same Item."));
		}
	},
});
