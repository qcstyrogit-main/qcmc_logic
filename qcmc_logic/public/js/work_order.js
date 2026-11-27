const QCMC_ROLL_FORMULATION_PATCH = "2026.06.25.10";

console.info(
	`[QCMC Roll Formulation] Client patch ${QCMC_ROLL_FORMULATION_PATCH} loaded`
);

frappe.ui.form.on("Work Order", {
	setup(frm) {
		apply_manufacturing_warehouse_queries(frm);
	},

	refresh(frm) {
		apply_manufacturing_warehouse_queries(frm);
		schedule_roll_formulation_grid_config(frm);
		schedule_roll_formulation_preview(frm);
		add_next_job_card_button(frm);
		if (!frm.is_new()) {
			frm.add_custom_button(__("Manufacturing History"), () => show_manufacturing_history(frm), __("View"));
		}
		install_job_order_print_handler(frm);
	},

	company(frm) {
		apply_manufacturing_warehouse_queries(frm);
	},

	production_item(frm) {
		apply_manufacturing_warehouse_queries(frm);
	},

	bom_no(frm) {
		schedule_roll_formulation_grid_config(frm);
		schedule_roll_formulation_preview(frm);
		apply_eps_sales_order_item_filters(frm);
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

function install_job_order_print_handler(frm) {
	frm.print_doc = () => open_job_order_print(frm);
	if (frm.toolbar) {
		frm.toolbar.print_me = () => open_job_order_print(frm);
	}
}

async function open_job_order_print(frm) {
	const print_window = window.open("", "_blank");
	if (!print_window) {
		frappe.msgprint(__("Please allow pop-ups to print this Job Order."));
		return;
	}

	try {
		const response = await frappe.call({
			method: "qcmc_logic.customs.work_order_print_format.get_work_order_print_format",
			args: { work_order: frm.doc.name },
		});
		const result = response.message || {};
		if (!result.print_format) {
			print_window.close();
			frappe.msgprint(
				__("No Job Order print format is assigned to workstation {0}.", [
					result.workstation || __("None"),
				])
			);
			return;
		}

		print_window.location = frappe.urllib.get_full_url(
			"/printview?" +
				$.param({
					doctype: frm.doc.doctype,
					name: frm.doc.name,
					format: result.print_format,
					no_letterhead: 0,
					lang: frappe.boot.lang || "en",
				})
		);
	} catch (error) {
		print_window.close();
		console.error("[QCMC Job Order Print]", error);
		frappe.msgprint(__("Unable to determine the Job Order print format."));
	}
}

function add_next_job_card_button(frm) {
	frm.remove_custom_button(__("Create Next Job Card"));

	const remaining_qty = flt(frm.doc.qty) - flt(frm.doc.produced_qty);
	const blocked_statuses = ["Completed", "Closed", "Stopped", "Cancelled"];
	if (
		frm.doc.docstatus !== 1 ||
		remaining_qty <= 0 ||
		blocked_statuses.includes(frm.doc.status) ||
		!(frm.doc.operations || []).length
	) {
		return;
	}

	const options = frm.doc.operations
		.filter((row) => flt(row.completed_qty) < flt(frm.doc.qty))
		.map((row) => ({ value: row.name, label: `${row.idx}. ${row.operation}` }));
	if (!options.length) return;

	frm.add_custom_button(__("Create Next Job Card"), () => {
		frappe.prompt([{
			fieldname: "operation_id", fieldtype: "Select", label: __("Operation"),
			options, default: options.at(-1).value, reqd: 1,
		}], async ({ operation_id }) => {
			const { message } = await frappe.call({
				method: "qcmc_logic.api.work_order_job_card.create_next_job_card",
				args: { work_order: frm.doc.name, operation_id },
				freeze: true,
			});
			if (message?.job_card) frappe.set_route("Form", "Job Card", message.job_card);
		}, __("Create Next Job Card"), __("Continue"));
	});
}

function apply_manufacturing_warehouse_queries(frm) {
	frm.set_query("bom_no", () => ({
		query: "qcmc_logic.customs.manufacturing_warehouse_access.bom_query",
		filters: {
			item: frm.doc.production_item,
			company: frm.doc.company,
		},
	}));
}

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

function get_roll_formulation_item_fields() {
	return [
		"custom_include_in_formulation",
		"custom_apply_roll_trimming",
		"custom_material_ratio_percent",
		"custom_bom_item_code",
		"custom_bom_item_group",
		"custom_bom_material_tag",
	];
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
			item_group: "",
			material_tag: "",
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
			onchange: () => update_roll_formulation_item_details(dialog, row, table_row, control),
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
	control.$input.on("awesomplete-selectcomplete change blur", () => {
		update_roll_formulation_item_details(dialog, row, table_row, control);
	});

	if (row.item_code && (!row.category || !row.item_group)) {
		update_roll_formulation_item_details(dialog, row, table_row, control);
	}
}

async function update_roll_formulation_item_details(dialog, row, table_row, control) {
	const item_code = control.get_value();
	if (row._qcmc_fetching_item_code === item_code) {
		return;
	}

	row.item_code = item_code;
	if (!item_code) {
		row.item_name = "";
		row.item_group = "";
		row.material_tag = "";
		row.category = "";
		row._qcmc_qty_per_percent = 0;
		row.required_qty = 0;
		refresh_roll_formulation_dialog_row(table_row, row);
		return;
	}

	row._qcmc_fetching_item_code = item_code;
	const response = await frappe.db.get_value(
		"Item",
		item_code,
		["item_name", "item_group", "custom_material_tag"]
	);
	if (row.item_code !== item_code) {
		return;
	}

	row._qcmc_fetching_item_code = null;
	const item = response?.message || {};
	const category = find_roll_formulation_category(
		dialog,
		item.item_group,
		item.custom_material_tag
	);
	const category_source = find_roll_formulation_category_source(
		dialog,
		category,
		row
	);

	row.item_name = item.item_name || "";
	row.item_group = item.item_group || "";
	row.material_tag = item.custom_material_tag || "";
	row.category = category?.label || "";
	row._qcmc_qty_per_percent = category_source?._qcmc_qty_per_percent || 0;
	row.required_qty = row._qcmc_qty_per_percent * flt(row.material_ratio_percent);
	refresh_roll_formulation_dialog_row(table_row, row);
}

function find_roll_formulation_category(dialog, item_group, material_tag) {
	return (dialog._qcmc_formulation_categories || []).find(
		(candidate) =>
			(candidate.item_group || "") === (item_group || "") &&
			(candidate.material_tag || "") === (material_tag || "")
	);
}

function find_roll_formulation_category_source(dialog, category, current_row) {
	if (!category) {
		return null;
	}

	return (dialog._qcmc_formulation_rows || []).find(
		(candidate) =>
			candidate._qcmc_key !== current_row._qcmc_key &&
			(candidate.item_group || "") === (category.item_group || "") &&
			(candidate.material_tag || "") === (category.material_tag || "") &&
			candidate._qcmc_qty_per_percent
	);
}

function refresh_roll_formulation_dialog_row(table_row, row) {
	table_row.find(".qcmc-item-name").text(row.item_name || "");
	table_row.find(".qcmc-category").text(row.category || "");
	table_row
		.find(".qcmc-computed-qty")
		.text(format_number(row.required_qty, null, 4));
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
		target.custom_bom_item_group = row.item_group || target.custom_bom_item_group;
		target.custom_bom_material_tag = row.material_tag || target.custom_bom_material_tag;
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

async function show_manufacturing_history(frm) {
	const { message: history } = await frappe.call({
		method: "qcmc_logic.api.process_card_services.get_work_order_manufacturing_history",
		type: "GET",
		args: { work_order: frm.doc.name },
		freeze: true,
	});
	const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
	const link = (doctype, name) => `<a href="${escape(frappe.utils.get_form_link(doctype, name))}">${escape(name)}</a>`;
	const list = (rows) => rows.length ? `<ul>${rows.map((row) => `<li>${row}</li>`).join("")}</ul>` : "";
	const section = (title, rows) => rows.length ? `<h5>${escape(__(title))}</h5>${list(rows)}` : "";
	const html = section("Operations", history.operations.map((row) =>
		`${escape(row.operation)} · ${escape(row.completed_qty)} · ${escape(row.status)}`))
		+ section("Job Cards", history.job_cards.map((row) =>
			`${link("Job Card", row.name)} · ${escape(row.operation)} · ${escape(row.total_completed_qty)}`))
		+ section("Process Cards", history.process_cards.map((shift) => link("Process Card", shift.name)
			+ " · " + escape(shift.workstation) + " · " + escape(shift.shift_type) + " · " + escape(shift.shift_start) + " – " + escape(shift.shift_end)
			+ (shift.section_access && Object.values(shift.section_access).includes(false) ? "<p class=\"text-muted\">" + escape(__("Some sections are restricted by your permissions.")) + "</p>" : "")
			+ section("Output Intervals", shift.output.flatMap((job) => job.entries.map((row) =>
				`${link("Job Card", job.job_card)} · ${escape(row.from_time)} – ${escape(row.to_time)} · ${escape(row.good_qty)} ${__("good")} / ${escape(row.rejected_qty)} ${__("rejected")} · ${row.confirmed ? __("Confirmed") : __("Declared")}`)))
			+ section("Employee Participation", shift.participation.map((row) =>
				`${link("Employee", row.employee) + " · " + escape(row.employee_name)} · ${link("Job Card", row.job_card)} · ${escape(row.pay_mode)} · ${escape(row.from_time)} – ${escape(row.to_time)}`))
			+ section("Quality Inspections", shift.qa.map((row) =>
				`${link("Quality Inspection", row.name)} · ${escape(row.status)} · ${escape(row.qa_start)} – ${escape(row.qa_end)} · ${escape(row.qa_rejected_qty)} ${__("rejected")}`))
			+ section("Product Weight / Measurements", (shift.measurements || []).map((row) =>
				link("Quality Inspection", row.quality_inspection) + " · " + escape(row.specification) + " · " + escape(row.reading_value || (row.readings || []).filter(value => value != null && value !== "").join(", ")) + " " + escape(row.uom) + " · " + escape(row.result)))
			+ section("QA Rejections", shift.qa_rejections.map((row) =>
				`${link("Quality Inspection", row.quality_inspection)} · ${escape(row.reject_reason)} · ${escape(row.rejected_qty)}`))
			+ section("Downtime", shift.downtime.map((row) =>
				`${link("Downtime Entry", row.name)} · ${escape(row.stop_reason)} · ${escape(row.from_time)} – ${escape(row.to_time)}`))
			+ section("Asset Repairs", shift.repairs.map((row) =>
				`${link("Asset Repair", row.name)} · ${escape(row.asset)} · ${escape(row.repair_status)}`))))
		+ section("Submitted Stock Entries", history.stock_entries.map((entry) =>
			`${link("Stock Entry", entry.name)} · ${escape(entry.purpose)} · ${escape(entry.posting_date)}`
			+ (entry.job_card ? " · " + link("Job Card", entry.job_card) : "")
			+ list([...new Set(entry.items.map(row => row.material_request).filter(Boolean))].map(name => link("Material Request", name)))
			+ list(entry.items.map((row) =>
				`${escape(row.item_code)} · ${escape(row.qty)} ${escape(row.uom)} · ${escape(row.from_warehouse)} → ${escape(row.to_warehouse)}`))
			+ list(entry.allocations.map((row) =>
				`${link("Process Card", row.process_card)} · ${escape(row.time_log)} · ${escape(row.qty)}`))));
	const dialog = new frappe.ui.Dialog({
		title: __("Manufacturing History"),
		size: "extra-large",
		fields: [{ fieldname: "history", fieldtype: "HTML" }],
	});
	dialog.fields_dict.history.$wrapper.html(html || escape(__("No manufacturing activity recorded.")));
	dialog.show();
}
