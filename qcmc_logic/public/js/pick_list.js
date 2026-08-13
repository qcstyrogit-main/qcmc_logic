frappe.ui.form.on("Pick List", {
	refresh(frm) {
		if (
			frm.doc.docstatus !== 1 ||
			frm.doc.status === "Completed" ||
			frm.doc.purpose !== "Material Transfer"
		) {
			return;
		}

		frm.add_custom_button(
			__("Warehouse Transfer"),
			() => qcmc_logic.pick_list.create_warehouse_transfer(frm),
			__("Create")
		);
	},
});

frappe.provide("qcmc_logic.pick_list");

qcmc_logic.pick_list.create_warehouse_transfer = function(frm) {
	const open_transfer = target_warehouse => {
		frappe
			.xcall("qcmc_logic.overrides.pick_list.create_warehouse_transfer", {
				pick_list: frm.doc,
				target_warehouse,
			})
			.then(warehouse_transfer => {
				if (!warehouse_transfer) return;
				frappe.model.sync(warehouse_transfer);
				frappe.set_route("Form", "Warehouse Transfer", warehouse_transfer.name);
			});
	};

	if (frm.doc.material_request) {
		open_transfer();
		return;
	}

	frappe.prompt(
		{
			fieldtype: "Link",
			options: "Warehouse",
			fieldname: "target_warehouse",
			label: __("Target Warehouse"),
			reqd: 1,
			get_query() {
				return {
					query: "qcmc_logic.utils.get_target_warehouse_query",
					filters: {
						user: frappe.session.user,
						source_warehouse: "",
						transfer_type: "Warehouse Transfer",
					},
				};
			},
		},
		values => open_transfer(values.target_warehouse),
		__("Create Warehouse Transfer"),
		__("Create")
	);
};
