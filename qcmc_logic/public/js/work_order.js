const QCMC_ROLL_FORMULATION_PATCH = "2026.06.25.10";

console.info(
	`[QCMC Roll Formulation] Client patch ${QCMC_ROLL_FORMULATION_PATCH} loaded`
);

frappe.ui.form.on("Work Order", {
	refresh(frm) {
		schedule_roll_formulation_grid_config(frm);
		schedule_roll_formulation_preview(frm);
		add_eps_sales_order_item_controls(frm);
		apply_eps_sales_order_item_filters(frm);
		hide_custom_print_button(frm);
		install_workstation_print_handler(frm);
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

frappe.ui.form.on("EPS Work Order Sales Order Item", {
	sales_order(frm) {
		apply_eps_sales_order_item_filters(frm);
	},

	item_code(frm) {
		apply_eps_sales_order_item_filters(frm);
	},
});

function add_eps_sales_order_item_controls(frm) {
	if (frm.doc.docstatus !== 0) {
		return;
	}

	frm.remove_custom_button(__("Add Sales Order Items"), __("EPS"));
	frm.add_custom_button(
		__("Add Sales Order Items"),
		() => open_eps_sales_order_item_picker(frm),
		__("EPS")
	);
}

function apply_eps_sales_order_item_filters(frm) {
	frm.set_query("sales_order_item", "custom_eps_sales_order_items", (doc, cdt, cdn) => {
		const row = locals[cdt][cdn];
		const filters = {};
		if (row.sales_order) {
			filters.parent = row.sales_order;
		}
		if (row.item_code) {
			filters.item_code = row.item_code;
		}
		return { filters };
	});
}

async function open_eps_sales_order_item_picker(frm) {
	if (!frm.doc.bom_no) {
		frappe.msgprint(__("Select a BOM before adding EPS Sales Order Items."));
		return;
	}

	const bom_outputs = await get_eps_bom_secondary_outputs(frm.doc.bom_no);
	if (!bom_outputs.length) {
		frappe.msgprint(__("This BOM has no Secondary Items to match against Sales Order Items."));
		return;
	}

	const output_item_codes = [...new Set(bom_outputs.map((row) => row.item_code).filter(Boolean))];
	const dialog = new frappe.ui.Dialog({
		title: __("Add EPS Sales Order Items"),
		size: "extra-large",
		fields: [
			{
				fieldtype: "Link",
				fieldname: "sales_order",
				label: __("Sales Order"),
				options: "Sales Order",
				get_query: () => ({
					filters: {
						docstatus: 1,
						status: ["not in", ["Closed", "On Hold"]],
					},
				}),
			},
			{
				fieldtype: "Link",
				fieldname: "item_code",
				label: __("Item"),
				options: "Item",
				get_query: () => ({
					filters: [["Item", "name", "in", output_item_codes]],
				}),
			},
			{
				fieldtype: "Button",
				fieldname: "load_items",
				label: __("Load"),
				click: () => load_eps_sales_order_items(frm, dialog, bom_outputs),
			},
			{
				fieldtype: "HTML",
				fieldname: "items",
			},
		],
		primary_action_label: __("Insert Selected"),
		primary_action: () => add_selected_eps_sales_order_items(frm, dialog, bom_outputs),
	});

	dialog.show();
	await load_eps_sales_order_items(frm, dialog, bom_outputs);
}

async function get_eps_bom_secondary_outputs(bom_no) {
	const response = await frappe.call({
		method: "qcmc_logic.api.work_order_sales_order_items.get_bom_secondary_outputs",
		args: { bom_no },
		freeze: true,
		freeze_message: __("Reading BOM secondary items..."),
	});
	return response.message || [];
}

async function load_eps_sales_order_items(frm, dialog, bom_outputs) {
	const values = dialog.get_values() || {};
	const allowed_items = new Set(bom_outputs.map((row) => row.item_code).filter(Boolean));
	const response = await frappe.call({
		method: "qcmc_logic.api.work_order_sales_order_items.get_sales_order_items_for_work_order",
		args: {
			sales_order: values.sales_order,
			item_code: values.item_code,
		},
		freeze: true,
		freeze_message: __("Loading Sales Order Items..."),
	});
	const rows = (response.message || []).filter((row) => allowed_items.has(row.item_code));
	dialog._qcmc_eps_so_items = rows;
	render_eps_sales_order_items(dialog, rows);
}

function render_eps_sales_order_items(dialog, rows) {
	const wrapper = dialog.get_field("items").$wrapper;
	if (!rows.length) {
		wrapper.html(`<p class="text-muted">${__("No matching open Sales Order Items found.")}</p>`);
		return;
	}

	const html = rows
		.map(
			(row, index) => `
			<tr>
				<td class="text-center">
					<input type="checkbox" class="qcmc-eps-so-item" data-index="${index}">
				</td>
				<td>${frappe.utils.escape_html(row.sales_order || "")}</td>
				<td>${frappe.utils.escape_html(row.item_code || "")}</td>
				<td>${frappe.utils.escape_html(row.item_name || "")}</td>
				<td class="text-right">${format_number(row.pending_qty, null, 4)}</td>
				<td>${frappe.utils.escape_html(row.stock_uom || row.uom || "")}</td>
				<td>${frappe.utils.escape_html(row.delivery_date || "")}</td>
				<td>${frappe.utils.escape_html(row.customer_name || row.customer || "")}</td>
			</tr>`
		)
		.join("");

	wrapper.html(`
		<div class="table-responsive" style="max-height: 420px; overflow: auto;">
			<table class="table table-bordered table-hover">
				<thead>
					<tr>
						<th style="width: 36px;"></th>
						<th>${__("Sales Order")}</th>
						<th>${__("Item")}</th>
						<th>${__("Item Name")}</th>
						<th class="text-right">${__("Pending Qty")}</th>
						<th>${__("UOM")}</th>
						<th>${__("Delivery Date")}</th>
						<th>${__("Customer")}</th>
					</tr>
				</thead>
				<tbody>${html}</tbody>
			</table>
		</div>
	`);
}

function add_selected_eps_sales_order_items(frm, dialog, bom_outputs) {
	const selected_indexes = dialog
		.get_field("items")
		.$wrapper.find(".qcmc-eps-so-item:checked")
		.map((_, input) => cint($(input).data("index")))
		.get();
	const rows = selected_indexes.map((index) => dialog._qcmc_eps_so_items[index]).filter(Boolean);
	if (!rows.length) {
		frappe.msgprint(__("Select at least one Sales Order Item."));
		return;
	}

	for (const source of rows) {
		if (has_eps_sales_order_item(frm, source.sales_order_item)) {
			continue;
		}

		const output = bom_outputs.find((row) => row.item_code === source.item_code) || {};
		const target = frm.add_child("custom_eps_sales_order_items");
		target.item_code = source.item_code;
		target.item_name = source.item_name;
		target.type = output.type || "Co-Product";
		target.qty = source.pending_qty;
		target.stock_uom = source.stock_uom || source.uom;
		target.sales_order = source.sales_order;
		target.sales_order_item = source.sales_order_item;
		target.customer_name = source.customer_name || source.customer;
		target.delivery_date = source.delivery_date;
		target.bom_secondary_item = output.name;
	}

	frm.refresh_field("custom_eps_sales_order_items");
	frm.dirty();
	dialog.hide();
}

function has_eps_sales_order_item(frm, sales_order_item) {
	return (frm.doc.custom_eps_sales_order_items || []).some(
		(row) => row.sales_order_item === sales_order_item
	);
}

function hide_custom_print_button(frm) {
	const hide = () => frm.remove_custom_button(__("Print"));

	// Client Scripts run separately and may add the button after this handler.
	setTimeout(hide, 0);
	frappe.after_ajax(hide);
}

function install_workstation_print_handler(frm) {
	frm.print_doc = () => print_with_workstation_format(frm);

	if (frm.toolbar) {
		frm.toolbar.print_me = () => print_with_workstation_format(frm);
	}
}

async function print_with_workstation_format(frm) {
	let workstation = null;
	const operations = frm.doc.operations || [];
	const last_operation = [...operations].reverse().find((row) => row.workstation);
	workstation = last_operation?.workstation;

	if (!workstation && frm.doc.bom_no) {
		const response = await frappe.db.get_list("BOM Operation", {
			filters: { parent: frm.doc.bom_no, parenttype: "BOM" },
			fields: ["workstation", "idx"],
			order_by: "idx desc",
			limit: 50,
		});
		workstation = response.find((row) => row.workstation)?.workstation;
	}

	if (!workstation) {
		frappe.msgprint(__("No workstation was found for this Job Order."));
		return;
	}

	const response = await frappe.db.get_value(
		"Workstation",
		workstation,
		"custom_print_format"
	);
	const print_format = response?.message?.custom_print_format;
	if (!print_format) {
		frappe.msgprint(
			__("No print format is assigned to workstation {0}.", [workstation])
		);
		return;
	}

	window.open(
		frappe.urllib.get_full_url(
			"/printview?" +
				$.param({
					doctype: frm.doc.doctype,
					name: frm.doc.name,
					format: print_format,
					no_letterhead: 0,
					lang: frappe.boot.lang || "en",
				})
		),
		"_blank"
	);
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
