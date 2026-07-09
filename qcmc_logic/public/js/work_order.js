const QCMC_ROLL_FORMULATION_PATCH = "2026.06.25.10";

console.info(
	`[QCMC Roll Formulation] Client patch ${QCMC_ROLL_FORMULATION_PATCH} loaded`
);

frappe.ui.form.on("Work Order", {
	refresh(frm) {
		schedule_roll_formulation_grid_config(frm);
		schedule_roll_formulation_preview(frm);
	},

	bom_no(frm) {
		schedule_roll_formulation_grid_config(frm);
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

	toggle_items_editable(frm) {
		schedule_roll_formulation_grid_config(frm);
	},

	required_items_on_form_rendered(frm) {
		schedule_roll_formulation_grid_config(frm);
	},
});

function schedule_roll_formulation_grid_config(frm) {
	clearTimeout(frm._roll_formulation_grid_timer);
	frm._roll_formulation_grid_timer = setTimeout(
		() => configure_roll_formulation_grid(frm),
		0
	);

	frappe.after_ajax(() => configure_roll_formulation_grid(frm));
}

async function configure_roll_formulation_grid(frm) {
	if (!frm.doc.bom_no || frm.doc.docstatus !== 0) {
		frm._qcmc_is_roll_bom = false;
		apply_roll_formulation_field_visibility(frm, false);
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
		is_roll_bom = is_roll_item_group(item_response?.message?.item_group);
	}
	if (!is_roll_bom || frm.doc.bom_no !== requested_bom) {
		frm._qcmc_is_roll_bom = false;
		apply_roll_formulation_field_visibility(frm, false);
		frm.remove_custom_button(__("Edit Formulation"), __("Roll Formulation"));
		return;
	}

	frm._qcmc_is_roll_bom = true;
	apply_roll_formulation_field_visibility(frm, true);

	const field = frm.get_field("required_items");
	if (!field) {
		console.warn("[QCMC Roll Formulation] Required Items grid was not found");
		return;
	}

	frm.set_df_property("required_items", "cannot_add_rows", false);
	frm.set_df_property("required_items", "cannot_delete_rows", false);

	const grid = field.grid;
	grid.df.cannot_add_rows = false;
	grid.df.cannot_delete_rows = false;
	grid.cannot_add_rows = false;
	grid.cannot_delete_rows = false;
	grid.update_docfield_property("item_code", "read_only", false);
	grid.update_docfield_property("custom_material_ratio_percent", "read_only", false);
	grid.update_docfield_property("required_qty", "read_only", true);
	grid.refresh();

	for (const grid_row of grid.grid_rows || []) {
		configure_roll_formulation_row(grid_row);
	}

	grid.wrapper
		.find(".grid-add-row, .grid-add-multiple-rows, .grid-remove-rows")
		.removeClass("hidden d-none");

	add_roll_formulation_controls(frm);

	console.info("[QCMC Roll Formulation] Roll Work Order patch active", {
		patch: QCMC_ROLL_FORMULATION_PATCH,
		work_order: frm.doc.name,
		bom: frm.doc.bom_no,
		required_items: (frm.doc.required_items || []).length,
		can_add_rows: !grid.cannot_add_rows && !grid.df.cannot_add_rows,
		can_delete_rows: !grid.cannot_delete_rows && !grid.df.cannot_delete_rows,
	});
}

function is_roll_item_group(item_group) {
	return (item_group || "").trim().toUpperCase() === "ROLLS";
}

function apply_roll_formulation_field_visibility(frm, show) {
	const grid = frm.get_field("required_items") && frm.get_field("required_items").grid;
	if (!grid) {
		return;
	}

	show = show ? true : false;
	if (frm._qcmc_work_order_roll_formulation_fields_visible === show) {
		return;
	}

	frm._qcmc_work_order_roll_formulation_fields_visible = show;
	grid.set_column_disp(get_roll_formulation_item_fields(), show);
}

function configure_roll_formulation_row(grid_row) {
	grid_row.toggle_editable("item_code", true);
	grid_row.toggle_editable("custom_material_ratio_percent", true);
	grid_row.toggle_editable("required_qty", false);
}

function add_roll_formulation_controls(frm) {
	frm.remove_custom_button(__("Edit Formulation"), __("Roll Formulation"));
	frm.add_custom_button(
		__("Edit Formulation"),
		() => open_roll_formulation_editor(frm),
		__("Roll Formulation")
	);
}

async function open_roll_formulation_editor(frm) {
	const response = await frappe.call({
		method: "qcmc_logic.customs.work_order_formulation.get_roll_formulation_editor_data",
		args: {
			doc: frm.doc,
		},
		freeze: true,
		freeze_message: __("Preparing Roll formulation..."),
	});
	const prepared = response.message;
	if (!prepared) {
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Edit Roll Formulation"),
		size: "extra-large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "category_targets",
				options: render_roll_formulation_categories(prepared.categories),
			},
			{
				fieldname: "formulation_table",
				fieldtype: "HTML",
			},
		],
		primary_action_label: __("Apply Formulation"),
		primary_action: async () => {
			await apply_roll_formulation_editor(
				frm,
				dialog,
				prepared,
				dialog._qcmc_formulation_rows
			);
		},
	});

	dialog.show();
	setup_roll_formulation_html_table(
		dialog,
		prepared.formulation_rows,
		prepared.categories
	);
}

function render_roll_formulation_categories(categories) {
	const rows = (categories || [])
		.map(
			(category) => `
				<tr>
					<td>${frappe.utils.escape_html(category.label || "")}</td>
					<td class="text-right">${format_number(
						category.target_ratio_percent,
						null,
						4
					)}%</td>
				</tr>
			`
		)
		.join("");

	return `
		<div class="mb-3">
			<div class="text-muted small mb-2">
				${__(
					"Materials may be split within each category, but each category must retain its BOM percentage."
				)}
			</div>
			<table class="table table-bordered table-sm">
				<thead>
					<tr>
						<th>${__("BOM Category")}</th>
						<th class="text-right">${__("Required Total")}</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
	`;
}

function setup_roll_formulation_html_table(dialog, source_rows, categories) {
	dialog._qcmc_formulation_categories = categories || [];
	dialog._qcmc_formulation_rows = (source_rows || []).map((row, index) => ({
		...row,
		_qcmc_key: `formulation-${index}-${frappe.utils.get_random(6)}`,
		_qcmc_qty_per_percent: flt(row.material_ratio_percent)
			? flt(row.required_qty) / flt(row.material_ratio_percent)
			: 0,
	}));

	render_roll_formulation_html_table(dialog);
}

function render_roll_formulation_html_table(dialog) {
	const wrapper = dialog.fields_dict.formulation_table.$wrapper;
	const rows = dialog._qcmc_formulation_rows || [];
	const body = rows.length
		? rows
				.map(
					(row) => `
						<tr data-row-key="${row._qcmc_key}">
							<td style="width: 3%" class="text-center">
								<input type="checkbox" class="qcmc-select-row">
							</td>
							<td style="width: 18%">
								<div class="qcmc-item-code-control"></div>
							</td>
							<td style="width: 27%" class="qcmc-item-name">
								${frappe.utils.escape_html(row.item_name || "")}
							</td>
							<td style="width: 22%" class="qcmc-category">
								${frappe.utils.escape_html(row.category || "")}
							</td>
							<td style="width: 13%">
								<input
									type="number"
									class="form-control input-xs qcmc-apply-percent"
									min="0"
									step="0.0001"
									value="${flt(row.material_ratio_percent)}"
								>
							</td>
							<td style="width: 15%" class="text-right qcmc-computed-qty">
								${format_number(flt(row.required_qty), null, 4)}
							</td>
							<td style="width: 5%" class="text-center">
								<button
									type="button"
									class="btn btn-xs btn-link text-danger qcmc-remove-row"
									title="${__("Remove")}"
								>
									${frappe.utils.icon("delete", "sm")}
								</button>
							</td>
						</tr>
					`
				)
				.join("")
		: `<tr><td colspan="7" class="text-center text-muted">${__(
				"No formulation materials"
		  )}</td></tr>`;

	wrapper.html(`
		<div class="form-group">
			<div class="d-flex justify-content-between align-items-end mb-2">
				<div>
					<label class="control-label mb-0">${__("Formulation Materials")}</label>
					<div class="text-muted small">
						${__("Category percentages are checked when the formulation is applied.")}
					</div>
				</div>
				<div>
					<button type="button" class="btn btn-xs btn-danger qcmc-delete-selected" disabled>
						${__("Delete")}
					</button>
					<button type="button" class="btn btn-xs btn-secondary qcmc-add-row">
						${__("Add row")}
					</button>
				</div>
			</div>
			<table class="table table-bordered table-sm mb-0">
				<thead>
					<tr>
						<th style="width: 3%" class="text-center">
							<input type="checkbox" class="qcmc-select-all">
						</th>
						<th>${__("Item Code")}</th>
						<th>${__("Item Name")}</th>
						<th>${__("BOM Category")}</th>
						<th>${__("Apply %")}</th>
						<th class="text-right">${__("Computed Qty")}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>${body}</tbody>
			</table>
		</div>
	`);

	for (const row of rows) {
		setup_roll_formulation_item_control(dialog, row);
	}

	wrapper.find(".qcmc-select-row").on("change", () => {
		update_roll_formulation_selection_controls(wrapper);
	});

	wrapper.find(".qcmc-select-all").on("change", function () {
		wrapper.find(".qcmc-select-row").prop("checked", this.checked);
		update_roll_formulation_selection_controls(wrapper);
	});

	wrapper.find(".qcmc-delete-selected").on("click", () => {
		const selected_keys = new Set();
		wrapper.find(".qcmc-select-row:checked").each(function () {
			selected_keys.add($(this).closest("tr").data("row-key"));
		});
		dialog._qcmc_formulation_rows = rows.filter(
			(row) => !selected_keys.has(row._qcmc_key)
		);
		render_roll_formulation_html_table(dialog);
	});

	wrapper.find(".qcmc-apply-percent").on("input", function () {
		const row = get_roll_formulation_dialog_row(dialog, this);
		row.material_ratio_percent = flt(this.value);
		row.required_qty = row._qcmc_qty_per_percent
			? row._qcmc_qty_per_percent * row.material_ratio_percent
			: 0;
		$(this)
			.closest("tr")
			.find(".qcmc-computed-qty")
			.text(format_number(row.required_qty, null, 4));
	});

	wrapper.find(".qcmc-remove-row").on("click", function () {
		const row = get_roll_formulation_dialog_row(dialog, this);
		dialog._qcmc_formulation_rows = rows.filter(
			(candidate) => candidate._qcmc_key !== row._qcmc_key
		);
		render_roll_formulation_html_table(dialog);
	});

	wrapper.find(".qcmc-add-row").on("click", () => {
		dialog._qcmc_formulation_rows.push({
			_qcmc_key: `formulation-new-${frappe.utils.get_random(6)}`,
			work_order_item_name: "",
			item_code: "",
			item_name: "",
			category: "",
			material_ratio_percent: 0,
			required_qty: 0,
			_qcmc_qty_per_percent: 0,
		});
		render_roll_formulation_html_table(dialog);
	});
}

function update_roll_formulation_selection_controls(wrapper) {
	const row_checks = wrapper.find(".qcmc-select-row");
	const selected_count = row_checks.filter(":checked").length;
	wrapper.find(".qcmc-delete-selected").prop("disabled", selected_count === 0);
	wrapper
		.find(".qcmc-select-all")
		.prop("checked", row_checks.length > 0 && selected_count === row_checks.length);
}

function setup_roll_formulation_item_control(dialog, row) {
	const table_row = dialog.fields_dict.formulation_table.$wrapper.find(
		`tr[data-row-key="${row._qcmc_key}"]`
	);
	const parent = table_row.find(".qcmc-item-code-control");
	const control = frappe.ui.form.make_control({
		parent,
		df: {
			fieldtype: "Link",
			fieldname: `item_code_${row._qcmc_key}`,
			options: "Item",
			placeholder: __("Item Code"),
			get_query: () => ({
				filters: {
					disabled: 0,
					is_stock_item: 1,
				},
			}),
		},
		render_input: true,
		only_input: true,
	});

	control.is_title_link = () => false;
	control.set_value(row.item_code || "");
	control.$input_area.addClass("overflow-visible");
	control.$wrapper.addClass("overflow-visible");
	control.$input.attr("autocomplete", "off");
	control.$input.on("change", async () => {
		const item_code = control.get_value();
		row.item_code = item_code;
		if (!item_code) {
			row.item_name = "";
			table_row.find(".qcmc-item-name").text("");
			return;
		}

		const response = await frappe.db.get_value(
			"Item",
			item_code,
			["item_name", "item_group", "custom_material_tag"]
		);
		if (row.item_code === item_code) {
			const item = response?.message || {};
			const category = (dialog._qcmc_formulation_categories || []).find(
				(candidate) =>
					(candidate.item_group || "") === (item.item_group || "") &&
					(candidate.material_tag || "") === (item.custom_material_tag || "")
			);
			const category_source = (dialog._qcmc_formulation_rows || []).find(
				(candidate) =>
					candidate.category === category?.label &&
					candidate._qcmc_qty_per_percent
			);

			row.item_name = item.item_name || "";
			row.category = category?.label || "";
			row._qcmc_qty_per_percent = category_source?._qcmc_qty_per_percent || 0;
			row.required_qty =
				row._qcmc_qty_per_percent * flt(row.material_ratio_percent);
			table_row.find(".qcmc-item-name").text(row.item_name);
			table_row.find(".qcmc-category").text(row.category);
			table_row
				.find(".qcmc-computed-qty")
				.text(format_number(row.required_qty, null, 4));
		}
	});
}

function get_roll_formulation_dialog_row(dialog, element) {
	const key = $(element).closest("tr").data("row-key");
	return dialog._qcmc_formulation_rows.find((row) => row._qcmc_key === key);
}

async function apply_roll_formulation_editor(frm, dialog, prepared, editor_rows) {
	const rows = (editor_rows || []).filter((row) => row.item_code);
	if (!rows.length) {
		frappe.msgprint(__("Add at least one formulation material."));
		return;
	}

	const source_rows = Object.fromEntries(
		(prepared.required_items || []).map((row) => [row.name, row])
	);
	const fixed_rows = (prepared.required_items || []).filter(
		(row) => !row.custom_bom_item_code
	);
	const formulation_rows = rows.map((row) => {
		const source = source_rows[row.work_order_item_name];
		const target = source
			? { ...source }
			: {
					doctype: "Work Order Item",
					parentfield: "required_items",
					parenttype: "Work Order",
					source_warehouse: frm.doc.source_warehouse || "",
			  };

		target.item_code = row.item_code;
		target.custom_material_ratio_percent = flt(row.material_ratio_percent);
		return target;
	});

	const draft = JSON.parse(JSON.stringify(frm.doc));
	draft.required_items = [...fixed_rows, ...formulation_rows];

	const response = await frappe.call({
		method: "qcmc_logic.customs.work_order_formulation.validate_roll_formulation_editor",
		args: {
			doc: draft,
		},
		freeze: true,
		freeze_message: __("Validating Roll formulation..."),
	});
	const result = response.message;
	if (!result) {
		return;
	}

	replace_required_items(frm, result.required_items);
	dialog.hide();
	schedule_roll_formulation_grid_config(frm);

	frappe.show_alert({
		message: __("Roll formulation applied. Save the Work Order to keep the changes."),
		indicator: "green",
	});
	console.info("[QCMC Roll Formulation] Editor formulation applied", {
		patch: QCMC_ROLL_FORMULATION_PATCH,
		work_order: frm.doc.name,
		rows: result.formulation_rows,
	});
}

function replace_required_items(frm, required_items) {
	const child_fields = frappe.meta.get_docfields("Work Order Item");

	frm.clear_table("required_items");
	for (const source of required_items || []) {
		const values = {};
		for (const field of child_fields) {
			if (Object.prototype.hasOwnProperty.call(source, field.fieldname)) {
				values[field.fieldname] = source[field.fieldname];
			}
		}
		frm.add_child("required_items", values);
	}

	frm.refresh_field("required_items");
	frm.dirty();
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
