frappe.ui.form.on("Pick List", {
	refresh(frm) {
		// Keep the old value available only when opening historical Pick Lists.
		// New documents use separate Material Issue and Warehouse Transfer purposes.
		const purposes = [
			"Material Transfer for Manufacture",
			"Material Issue",
			"Warehouse Transfer",
			"Delivery",
		];
		if (frm.doc.purpose === "Material Transfer") {
			purposes.splice(1, 0, "Material Transfer");
		}
		frm.set_df_property("purpose", "options", purposes.join("\n"));
		// Warehouse Transfers are shown by the native Connections dashboard.
		frm.dashboard.parent.find(".qcmc-linked-transfers").remove();
		// Native Connections already shows linked Delivery Notes.
		frm.dashboard.parent.find(".qcmc-pick-linked-dn").remove();

		if (frm.doc.docstatus === 1 && frm.doc.purpose === "Delivery" &&
			frm.doc.status !== "Completed") {
			frm.add_custom_button(__("Sync Delivery Status"), async () => {
				const result = await frappe.xcall(
					"qcmc_logic.delivery_note_pick_list.repair_submitted_delivery_pick_list",
					{pick_list: frm.doc.name}
				);
				frappe.show_alert({
					message: __("Pick List delivery status updated: {0}", [result.status]),
					indicator: "green",
				}, 8);
				frm.reload_doc();
			});
		}

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Suggest Picking Locations"), () =>
				qcmc_logic.pick_list.suggest_locations(frm)
			);
			// Delivery Note-created Pick Lists start with item rows but no bins.
			// Suggest once on opening the draft, without saving or posting stock.
			const needs_suggestion = frm.doc.purpose === "Delivery" &&
				(frm.doc.locations || []).length > 0 &&
				frm.doc.locations.some(row => !row.location && flt(row.stock_qty) > 0) &&
				frm.doc.locations.every(row => !row.location && !flt(row.picked_qty));
			if (needs_suggestion && !frm.is_dirty() &&
				frm.__qcmc_auto_suggest_name !== frm.doc.name) {
				frm.__qcmc_auto_suggest_name = frm.doc.name;
				qcmc_logic.pick_list.suggest_locations(frm, true).catch(error =>
					console.warn("Automatic picking location suggestion failed", error)
				);
			}
		}

		if (frm.doc.purpose === "Warehouse Transfer") {
			// A Warehouse Transfer is a custom QCMC document, not a Stock Entry.
			frm.remove_custom_button(__("Stock Entry"), __("Create"));
		}

		if (
			frm.doc.docstatus !== 1 ||
			frm.doc.status === "Completed" ||
			!["Warehouse Transfer", "Material Transfer"].includes(frm.doc.purpose)
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

qcmc_logic.pick_list.suggest_locations = async function(frm, automatic = false) {
	if (frm.doc.docstatus !== 0) return;
	if (!frm.doc.locations?.length) {
		if (!automatic) frappe.msgprint(__("Add items first, then suggest picking locations."));
		return;
	}
	const name = frm.doc.name;
	const locations = await frappe.xcall("qcmc_logic.overrides.pick_list.suggest_pick_locations", {
		pick_list: JSON.stringify(frm.doc),
	});
	if (!locations || frm.doc.name !== name || frm.doc.docstatus !== 0) return;
	const allocated = locations.filter(row => row.location && flt(row.stock_qty) > 0);
	const unallocated = locations.filter(row => !row.location && flt(row.stock_qty) > 0);
	if (automatic && !allocated.length) {
		frappe.show_alert({
			message: __("No recorded location stock was found. Review Stock Summary or select a location manually."),
			indicator: "orange",
		}, 8);
		return;
	}
	frm.clear_table("locations");
	for (const location of locations) {
		const row = frm.add_child("locations");
		for (const [fieldname, value] of Object.entries(location)) {
			if (["name", "parent", "parenttype", "parentfield", "idx", "doctype", "__islocal"].includes(fieldname)) continue;
			row[fieldname] = value;
		}
	}
	frm.refresh_field("locations");
	frm.dirty();
	const missing = unallocated.reduce((total, row) => total + flt(row.stock_qty), 0);
	frappe.show_alert({
		message: missing
			? __("Suggested {0} locations; {1} stock units still have no available location. Review before saving.", [allocated.length, format_number(missing)])
			: __("Suggested {0} picking locations from available location stock. Review and save.", [allocated.length]),
		indicator: missing ? "orange" : "green",
	}, 10);
};

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
