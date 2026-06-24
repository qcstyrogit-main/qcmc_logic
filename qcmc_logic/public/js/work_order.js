frappe.ui.form.on("Work Order", {
	refresh(frm) {
		configure_roll_formulation_grid(frm);
		schedule_roll_formulation_preview(frm);
	},

	bom_no(frm) {
		configure_roll_formulation_grid(frm);
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

async function configure_roll_formulation_grid(frm) {
	if (!frm.doc.bom_no || frm.doc.docstatus !== 0) {
		return;
	}

	const requested_bom = frm.doc.bom_no;
	const response = await frappe.db.get_value(
		"BOM",
		requested_bom,
		["custom_is_roll_bom", "item"]
	);
	const bom = response && response.message;
	if (!bom) {
		return;
	}

	let is_roll_bom = cint(bom.custom_is_roll_bom);
	if (!is_roll_bom && bom.item) {
		const item_response = await frappe.db.get_value("Item", bom.item, "item_group");
		is_roll_bom = item_response?.message?.item_group === "Rolls";
	}
	if (!is_roll_bom || frm.doc.bom_no !== requested_bom) {
		return;
	}

	const field = frm.get_field("required_items");
	if (!field) {
		return;
	}

	frm.set_df_property("required_items", "cannot_add_rows", false);
	frm.set_df_property("required_items", "cannot_delete_rows", false);

	const grid = field.grid;
	grid.cannot_add_rows = false;
	grid.cannot_delete_rows = false;
	grid.update_docfield_property("item_code", "read_only", false);
	grid.update_docfield_property("custom_material_ratio_percent", "read_only", false);
	grid.update_docfield_property("required_qty", "read_only", true);
	grid.refresh();
}

frappe.ui.form.on("Work Order Item", {
	item_code(frm) {
		schedule_roll_formulation_preview(frm);
	},

	custom_material_ratio_percent(frm) {
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

		const result = response.message;
		if (!result || result.document_modified !== frm.doc.modified) {
			return;
		}

		apply_required_item_updates(frm, result.required_items);
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
