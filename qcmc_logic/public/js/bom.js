const ROLL_FORMULATION_ITEM_FIELDS = [
	"custom_include_in_formulation",
	"custom_material_ratio_percent",
	"custom_apply_roll_trimming",
];

frappe.ui.form.on("BOM", {
	async refresh(frm) {
		await set_roll_bom_flag(frm);
		recalculate_formulation_total(frm);
		apply_roll_formulation_field_visibility(frm);
		schedule_roll_required_kg_recalculation(frm);
	},

	async item(frm) {
		await set_roll_bom_flag(frm);
		await fetch_finished_good_standard_weight(frm);
	},

	async validate(frm) {
		await set_roll_bom_flag(frm);
		recalculate_formulation_total(frm);
		schedule_roll_required_kg_recalculation(frm);
	},

	quantity(frm) {
		schedule_roll_required_kg_recalculation(frm);
	},

	custom_standard_weight_grams(frm) {
		schedule_roll_required_kg_recalculation(frm);
	},

	custom_stabilizer_percent(frm) {
		schedule_roll_required_kg_recalculation(frm);
	},

	custom_reject_percent(frm) {
		schedule_roll_required_kg_recalculation(frm);
	},

	custom_roll_yield(frm) {
		schedule_roll_required_kg_recalculation(frm);
	},

	custom_is_roll_bom(frm) {
		apply_roll_formulation_field_visibility(frm);
	},

	items_add(frm) {
		apply_roll_formulation_field_visibility(frm);
		recalculate_formulation_total(frm);
		schedule_roll_required_kg_recalculation(frm);
	},

	items_remove(frm) {
		recalculate_formulation_total(frm);
		apply_roll_formulation_field_visibility(frm);
		schedule_roll_required_kg_recalculation(frm);
	},
});

frappe.ui.form.on("BOM Item", {
	item_code(frm, cdt, cdn) {
		handle_roll_item_code_change(frm, cdt, cdn);
	},

	custom_include_in_formulation(frm, cdt, cdn) {
		recalculate_formulation_total(frm);
		refresh_bom_items_grid(frm);
	},

	custom_material_ratio_percent(frm) {
		recalculate_formulation_total(frm);
	},

	custom_apply_roll_trimming(frm) {
		refresh_bom_items_grid(frm);
	},

	items_remove(frm) {
		recalculate_formulation_total(frm);
		schedule_roll_required_kg_recalculation(frm);
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
		await frm.set_value("custom_is_roll_bom", 0);
		apply_roll_formulation_field_visibility(frm);
		return;
	}

	const details = await get_item_roll_details(frm, frm.doc.item);

	await frm.set_value("custom_is_roll_bom", details.is_roll ? 1 : 0);
	apply_roll_formulation_field_visibility(frm);
}

function apply_roll_formulation_field_visibility(frm) {
	const grid = frm.get_field("items") && frm.get_field("items").grid;
	if (!grid) {
		return;
	}

	const show = cint(frm.doc.custom_is_roll_bom) ? true : false;
	frm._qcmc_roll_formulation_fields_visible = show;
	for (const fieldname of get_roll_formulation_item_fields()) {
		grid.set_column_disp(fieldname, show);
		grid.update_docfield_property(fieldname, "hidden", show ? 0 : 1);
		grid.update_docfield_property(fieldname, "in_list_view", show ? 1 : 0);
	}
	refresh_bom_items_grid(frm);
}

function get_roll_formulation_item_fields() {
	return ROLL_FORMULATION_ITEM_FIELDS;
}

function refresh_bom_items_grid(frm) {
	if (frm && frm.fields_dict && frm.fields_dict.items) {
		frm.refresh_field("items");
	}
}

async function fetch_finished_good_standard_weight(frm) {
	if (!frm.doc.item) {
		return;
	}

	const details = await get_item_roll_details(frm, frm.doc.item);
	await frm.set_value("custom_standard_weight_grams", flt(details.weight_per_unit));
	schedule_roll_required_kg_recalculation(frm);
}

async function handle_roll_item_code_change(frm, cdt, cdn) {
	frappe.after_ajax(() => {
		schedule_roll_required_kg_recalculation(frm, true, 150);
	});
}

async function recalculate_roll_required_kg_for_all_rows(frm, show_message) {
	const roll_rows = await get_roll_rows(frm);
	if (!validate_single_roll_row(roll_rows, show_message)) {
		return;
	}

	if (!roll_rows.length) {
		for (const row of frm.doc.items || []) {
			await frappe.model.set_value(row.doctype, row.name, "custom_roll_required_kg", 0);
		}
		frm.refresh_field("items");
		return;
	}

	await recalculate_roll_required_kg_for_row(
		frm,
		roll_rows[0].doctype,
		roll_rows[0].name,
		show_message
	);
}

async function recalculate_roll_required_kg_for_row(frm, cdt, cdn, show_message) {
	const row = locals[cdt] && locals[cdt][cdn];
	if (!row) {
		return;
	}

	if (!(await is_roll_item(frm, row.item_code))) {
		await recalculate_roll_required_kg_for_all_rows(frm);
		return;
	}

	const roll_rows = await get_roll_rows(frm);
	if (!validate_single_roll_row(roll_rows, show_message)) {
		return;
	}

	const missing_values = get_missing_roll_required_values(frm, row);
	if (missing_values.length) {
		if (show_message) {
			frappe.msgprint({
				title: __("Roll Required KG"),
				message: __(
					"Row #{0}: Cannot compute Roll Required KG for item {1}. Missing: {2}.",
					[row.idx, escape_html(row.item_code || ""), missing_values.join(", ")]
				),
				indicator: "orange",
			});
		}
		return;
	}

	const roll_required_kg = round_to_3(
		(((flt(frm.doc.quantity) * flt(frm.doc.custom_standard_weight_grams)) / 1000)
			/ flt(frm.doc.custom_roll_yield))
			* (1 + ((flt(frm.doc.custom_stabilizer_percent) + flt(frm.doc.custom_reject_percent)) / 100))
	);

	await frappe.model.set_value(cdt, cdn, "qty", roll_required_kg);
	await frappe.model.set_value(cdt, cdn, "custom_roll_required_kg", roll_required_kg);
	frm.refresh_field("items");
}

function get_missing_roll_required_values(frm, row) {
	const missing_values = [];
	if (!flt(frm.doc.quantity)) {
		missing_values.push(__("BOM Qty"));
	}
	if (!flt(frm.doc.custom_standard_weight_grams)) {
		missing_values.push(__("Standard Weight (g)"));
	}
	if (!flt(frm.doc.custom_roll_yield)) {
		missing_values.push(__("Roll Yield"));
	}

	return missing_values;
}

function round_to_3(value) {
	return flt(value, 3);
}

function schedule_roll_required_kg_recalculation(frm, show_message, delay) {
	clearTimeout(frm._qcmc_roll_required_kg_timer);
	frm._qcmc_roll_required_kg_timer = setTimeout(() => {
		recalculate_roll_required_kg_for_all_rows(frm, show_message);
	}, delay || 100);
}

async function is_roll_item(frm, item_code) {
	if (!item_code) {
		return false;
	}

	const details = await get_item_roll_details(frm, item_code);
	return details.is_roll;
}

async function get_item_roll_details(frm, item_code) {
	frm._qcmc_roll_item_details_cache = frm._qcmc_roll_item_details_cache || {};
	if (Object.prototype.hasOwnProperty.call(frm._qcmc_roll_item_details_cache, item_code)) {
		return frm._qcmc_roll_item_details_cache[item_code];
	}

	const result = await frappe.call({
		method: "qcmc_logic.customs.bom_formulation.get_item_roll_details",
		args: {
			item_code,
		},
	});
	const details = result.message || {};
	frm._qcmc_roll_item_details_cache[item_code] = details;
	return details;
}

async function get_roll_rows(frm) {
	const rows = [];
	for (const row of frm.doc.items || []) {
		if (await is_roll_item(frm, row.item_code)) {
			rows.push(row);
		}
	}
	return rows;
}

function validate_single_roll_row(roll_rows, show_message) {
	if (roll_rows.length <= 1) {
		return true;
	}

	if (show_message) {
		frappe.msgprint({
			title: __("Roll Required KG"),
			message: __(
				"Only one Roll item can be used as the BOM basis for Roll Required KG. Found Roll items: {0}.",
				[roll_rows.map((row) => escape_html(row.item_code || "")).join(", ")]
			),
			indicator: "orange",
		});
	}
	return false;
}

function escape_html(value) {
	if (frappe.utils && frappe.utils.escape_html) {
		return frappe.utils.escape_html(value);
	}

	return value;
}
