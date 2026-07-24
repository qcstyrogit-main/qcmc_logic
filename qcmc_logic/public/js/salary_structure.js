frappe.ui.form.on("Salary Structure", {
	refresh(frm) {
		if (frm.doc.docstatus !== 0) return;

		frm.add_custom_button(
			__("Populate Earnings"),
			() => populate_salary_components(frm, "Earning", "earnings"),
			__("Salary Components"),
		);
		frm.add_custom_button(
			__("Populate Deductions"),
			() => populate_salary_components(frm, "Deduction", "deductions"),
			__("Salary Components"),
		);
	},
});

async function populate_salary_components(frm, component_type, table_field) {
	if (!frm.doc.company) {
		frappe.msgprint(__("Please select a Company first."));
		return;
	}

	const response = await frappe.call({
		method: "qcmc_logic.api.salary_structure.get_salary_components",
		args: {
			component_type,
			company: frm.doc.company,
		},
		freeze: true,
		freeze_message: __("Loading {0} components...", [component_type.toLowerCase()]),
	});

	const component_names = Array.from(
		new Set((response.message || []).filter(Boolean)),
	);
	const existing = new Set(
		(frm.doc[table_field] || []).map((row) => row.salary_component).filter(Boolean),
	);
	const components_to_add = component_names.filter((name) => !existing.has(name));

	for (const component of components_to_add) {
		const row = frm.add_child(table_field);
		await frappe.model.set_value(row.doctype, row.name, "salary_component", component);
	}

	if (components_to_add.length) {
		frm.refresh_field(table_field);
		frm.dirty();
		frappe.show_alert({
			message: __(
				"Added {0} {1} component(s). Existing rows were preserved.",
				[components_to_add.length, component_type.toLowerCase()],
			),
			indicator: "green",
		});
	} else {
		frappe.show_alert({
			message: __("All enabled {0} components are already present.", [
				component_type.toLowerCase(),
			]),
			indicator: "blue",
		});
	}
}
