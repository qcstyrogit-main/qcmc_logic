frappe.ui.form.on("Sales Order", {
	onload(frm) {
		set_customer_account_manager(frm, false);
	},

	refresh(frm) {
		set_customer_account_manager(frm, false);
	},

	customer(frm) {
		set_customer_account_manager(frm, true);
	},
});

function set_customer_account_manager(frm, force) {
	if (!frm.doc.customer) {
		if (force) {
			frm.set_value("custom_account_manager", "");
		}
		return;
	}

	if (!force && frm.doc.custom_account_manager) {
		return;
	}

	frappe.call({
		method: "qcmc_logic.customs.sales_order.get_customer_account_manager",
		args: {
			customer: frm.doc.customer,
		},
		callback(r) {
			frm.set_value("custom_account_manager", r.message || "");
		},
	});
}
