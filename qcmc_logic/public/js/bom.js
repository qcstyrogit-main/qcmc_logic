frappe.ui.form.on("BOM", {
	refresh(frm) {
		set_roll_bom_flag(frm);
		recalculate_formulation_total(frm);
	},

	item(frm) {
		set_roll_bom_flag(frm);
	},

	validate(frm) {
		recalculate_formulation_total(frm);
	},

	items_add(frm) {
		recalculate_formulation_total(frm);
	},

	items_remove(frm) {
		recalculate_formulation_total(frm);
	},
});

frappe.ui.form.on("BOM Item", {
	custom_include_in_formulation(frm, cdt, cdn) {
		recalculate_formulation_total(frm);
	},

	custom_material_ratio_percent(frm) {
		recalculate_formulation_total(frm);
	},

	items_remove(frm) {
		recalculate_formulation_total(frm);
	},
});

function recalculate_formulation_total(frm) {
	const total = (frm.doc.items || []).reduce((sum, row) => {
		if (!cint(row.custom_include_in_formulation)) {
			return sum;
		}

		return sum + flt(row.custom_material_ratio_percent);
	}, 0);

	frm.set_value("custom_total_formulation_percent", total);
}

async function set_roll_bom_flag(frm) {
	if (!frm.doc.item) {
		frm.set_value("custom_is_roll_bom", 0);
		return;
	}

	const result = await frappe.db.get_value("Item", frm.doc.item, "item_group");
	const item_group = result && result.message && result.message.item_group;

	frm.set_value("custom_is_roll_bom", item_group === "Rolls" ? 1 : 0);
}
