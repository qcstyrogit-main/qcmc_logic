frappe.ui.form.on("Sales Order", {
	onload(frm) {
		set_shipping_address_query(frm);
		set_customer_account_manager(frm, false);
	},

	refresh(frm) {
		set_shipping_address_query(frm);
		set_customer_account_manager(frm, false);
	},

	customer(frm) {
		set_shipping_address_query(frm);
		set_customer_account_manager(frm, true);
	},
});

function set_shipping_address_query(frm) {
	frm.set_query("shipping_address_name", () => ({
		query: "frappe.contacts.doctype.address.address.address_query",
		filters: {
			link_doctype: "Customer",
			link_name: frm.doc.customer,
			address_type: "Shipping",
		},
	}));
}

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
