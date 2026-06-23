frappe.ui.form.on("Work Order", {
	refresh(frm) {
		schedule_roll_formulation_preview(frm);
	},

	bom_no(frm) {
		schedule_roll_formulation_preview(frm);
	},

	qty(frm) {
		schedule_roll_formulation_preview(frm);
	},

	required_items_add(frm) {
		schedule_roll_formulation_preview(frm);
	},

	required_items_remove(frm) {
		schedule_roll_formulation_preview(frm);
	},
});

frappe.ui.form.on("Work Order Item", {
	item_code(frm) {
		schedule_roll_formulation_preview(frm);
	},
});

function schedule_roll_formulation_preview(frm) {
	if ((frm.doc.required_items || []).length) {
		frm._roll_formulation_had_required_items = true;
	}

	clearTimeout(frm._roll_formulation_timer);
	frm._roll_formulation_timer = setTimeout(() => apply_roll_formulation_preview(frm), 400);
}

async function apply_roll_formulation_preview(frm) {
	if (
		frm.doc.docstatus !== 0 ||
		!frm.doc.bom_no ||
		!flt(frm.doc.qty) ||
		(!(frm.doc.required_items || []).length && !frm._roll_formulation_had_required_items) ||
		frm._applying_roll_formulation
	) {
		return;
	}

	frm._applying_roll_formulation = true;

	try {
		const response = await frappe.call({
			method: "qcmc_logic.customs.work_order_formulation.preview_roll_formulation_required_items",
			args: {
				doc: frm.doc,
			},
			freeze: false,
		});

		apply_required_item_updates(frm, response.message && response.message.required_items);
	} finally {
		frm._applying_roll_formulation = false;
	}
}

function apply_required_item_updates(frm, required_items) {
	if (!required_items) {
		return;
	}

	const rows_by_name = {};
	for (const row of frm.doc.required_items || []) {
		rows_by_name[row.name] = row;
	}

	for (const source of required_items) {
		const target = rows_by_name[source.name];
		if (!target) {
			continue;
		}

		for (const fieldname of get_roll_formulation_fields()) {
			frappe.model.set_value(target.doctype, target.name, fieldname, source[fieldname]);
		}
	}

	frm.refresh_field("required_items");
}

function get_roll_formulation_fields() {
	return [
		"custom_include_in_formulation",
		"custom_apply_roll_trimming",
		"custom_material_ratio_percent",
		"custom_bom_item_code",
		"custom_bom_item_group",
		"custom_bom_material_tag",
		"required_qty",
		"amount",
	];
}
