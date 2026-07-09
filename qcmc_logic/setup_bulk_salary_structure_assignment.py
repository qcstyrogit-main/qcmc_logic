import frappe


def execute():
	script_name = "Bulk Salary Structure Assignment Employee Column Fix"
	script = r"""
frappe.ui.form.on("Bulk Salary Structure Assignment", {
	setup(frm) {
		install_bulk_salary_structure_assignment_doctype_guard();
		install_bulk_salary_structure_assignment_column_patch(frm);
		install_bulk_salary_declared_income_patch(frm);
		apply_bulk_salary_role_scope(frm);
	},
	refresh(frm) {
		install_bulk_salary_structure_assignment_doctype_guard();
		install_bulk_salary_structure_assignment_column_patch(frm);
		install_bulk_salary_declared_income_patch(frm);
		apply_bulk_salary_role_scope(frm);
		setTimeout(() => ensure_declared_income_update_button(frm), 300);
		setTimeout(() => install_bulk_salary_assign_button_patch(frm), 300);
	},
	async salary_structure(frm) {
		await sync_bulk_salary_company_from_structure(frm);
		apply_bulk_salary_role_scope(frm);
	},
	handle_row_check(frm) {
		setTimeout(() => sync_declared_income_update_button(frm), 0);
	},
	render_update_button(frm) {
		setTimeout(() => sync_declared_income_update_button(frm), 0);
	},
});

function install_bulk_salary_structure_assignment_doctype_guard() {
	if (frappe.model.__qcmc_bulk_salary_with_doctype_guard) return;

	const original_with_doctype = frappe.model.with_doctype;
	const original_call = frappe.call;
	frappe.model.__qcmc_bulk_salary_with_doctype_guard = true;

	frappe.model.with_doctype = function(doctype, callback) {
		if (is_bulk_salary_structure_assignment_route() && is_ignored_bulk_salary_doctype(doctype)) {
			if (typeof callback === "function") callback();
			return Promise.resolve();
		}

		return original_with_doctype.apply(this, arguments);
	};

	frappe.call = function(opts) {
		const normalized_opts = get_bulk_salary_call_options(arguments);
		if (
			is_bulk_salary_structure_assignment_route() &&
			normalized_opts.method === "frappe.desk.form.load.getdoctype" &&
			is_ignored_bulk_salary_doctype(normalized_opts.args && normalized_opts.args.doctype)
		) {
			const response = { docs: [], message: null };
			if (typeof normalized_opts.callback === "function") {
				normalized_opts.callback(response);
			}
			if (typeof normalized_opts.always === "function") {
				normalized_opts.always(response);
			}
			return Promise.resolve(response);
		}

		return original_call.apply(this, arguments);
	};
}

function install_bulk_salary_structure_assignment_column_patch(frm) {
	if (frm.__qcmc_bulk_salary_columns_patched) return;
	const original = frm.events.get_employees_datatable_columns;
	if (!original) {
		setTimeout(() => install_bulk_salary_structure_assignment_column_patch(frm), 100);
		return;
	}

	frm.__qcmc_bulk_salary_columns_patched = true;

	frm.events.get_employees_datatable_columns = function() {
		const columns = original.apply(this, arguments);
		const patched_columns = (columns || []).slice();
		const has_declared_income = patched_columns.some((column) => (column.id || column.name) === "custom_declared_income");
		if (!has_declared_income) {
			const base_index = patched_columns.findIndex((column) => (column.id || column.name) === "base");
			patched_columns.splice(base_index >= 0 ? base_index + 1 : patched_columns.length, 0, {
				name: "custom_declared_income",
				id: "custom_declared_income",
				content: __("Declared Income"),
				dropdown: false,
				align: "left",
			});
		}

		return patched_columns.map((column) => {
			const fieldname = column.id || column.name;
			return {
				...column,
				docfield: {
					fieldname,
					fieldtype: get_bulk_salary_column_fieldtype(fieldname),
					label: column.content || column.name || fieldname,
					options: "",
				},
			};
		});
	};
}

function get_bulk_salary_column_fieldtype(fieldname) {
	if (["base", "variable", "custom_declared_income"].includes(fieldname)) return "Currency";
	return "Data";
}

function install_bulk_salary_declared_income_patch(frm) {
	if (frm.__qcmc_bulk_salary_declared_income_patched) return;
	if (!frm.events.get_employees_datatable_columns) {
		setTimeout(() => install_bulk_salary_declared_income_patch(frm), 100);
		return;
	}

	frm.__qcmc_bulk_salary_declared_income_patched = true;

	frm.events.render_employees_datatable = function(frm, employees) {
		frm.checked_rows_indexes = [];

		const columns = frm.events.get_employees_datatable_columns();
		const no_data_message = __(
			frm.doc.from_date
				? "There are no employees without a Salary Structure Assignment on this date based on the given filters."
				: "Please select From Date.",
		);
		const get_editor = (colIndex, rowIndex, value, parent, column) => {
			if (!["base", "variable", "custom_declared_income"].includes(column.name)) return;
			const $input = document.createElement("input");
			$input.className = "dt-input h-100";
			$input.type = "number";
			$input.min = 0;
			parent.appendChild($input);
			return {
				initValue(value) {
					$input.focus();
					$input.value = value;
				},
				setValue(value) {
					$input.value = value;
				},
				getValue() {
					return Number($input.value);
				},
			};
		};
		const events = {
			onCheckRow() {
				frm.trigger("handle_row_check");
			},
		};

		hrms.render_employees_datatable(
			frm,
			columns,
			employees,
			no_data_message,
			get_editor,
			events,
		);
	};

	frm.events.render_update_button = function(frm) {
		[
			{ label: "Base", fieldname: "base" },
			{ label: "Declared Income", fieldname: "custom_declared_income" },
			{ label: "Variable", fieldname: "variable" },
		].forEach((field) =>
			frm.add_custom_button(
				__(field.label),
				function() {
					const dialog = new frappe.ui.Dialog({
						title: __("Set {0} for selected employees", [__(field.label)]),
						fields: [
							{
								label: __(field.label),
								fieldname: field.fieldname,
								fieldtype: "Currency",
							},
						],
						primary_action_label: __("Update"),
						primary_action(values) {
							const column = frm.employees_datatable.datamanager.columns.find(
								(col) => col.id === field.fieldname,
							);
							if (!column) return;

							frm.checked_rows_indexes.forEach((row_idx) => {
								frm.employees_datatable.cellmanager.updateCell(
									column.colIndex,
									row_idx,
									values[field.fieldname],
									true,
								);
							});
							dialog.hide();
						},
					});
					dialog.show();
				},
				__("Update"),
			),
		);
		frm.update_button_rendered = true;
	};

	frm.events.handle_row_check = function(frm) {
		frm.checked_rows_indexes = frm.employees_datatable.rowmanager.getCheckedRows();
		const labels = ["Base", "Declared Income", "Variable"];
		if (!frm.checked_rows_indexes.length && frm.update_button_rendered) {
			labels.forEach((label) => frm.remove_custom_button(__(label), __("Update")));
			frm.__qcmc_declared_income_button_added = false;
			frm.update_button_rendered = false;
		} else if (frm.checked_rows_indexes.length && !frm.update_button_rendered) {
			frm.trigger("render_update_button");
		} else if (frm.checked_rows_indexes.length) {
			ensure_declared_income_update_button(frm);
		}
	};

	frm.events.assign_structure = function(frm) {
		return qcmc_bulk_salary_assign_structure(frm);
	};
}

function install_bulk_salary_assign_button_patch(frm) {
	if (!frm.page || !frm.employees_datatable) return;

	frm.page.set_primary_action(__("Assign Structure"), () => {
		qcmc_bulk_salary_assign_structure(frm);
	});
}

function qcmc_bulk_salary_assign_structure(frm) {
	const checked_rows_content = get_selected_bulk_salary_rows(frm);
	const employees_with_base_zero = checked_rows_content
		.filter((row) => !Number(row.base))
		.map((row) => `<b>${row.employee}</b>`);

	hrms.validate_mandatory_fields(frm, checked_rows_content);
	if (employees_with_base_zero.length) {
		return frm.events.validate_base_zero(
			frm,
			employees_with_base_zero,
			checked_rows_content,
		);
	}

	return frm.events.show_confirm_dialog(frm, checked_rows_content);
}

function get_selected_bulk_salary_rows(frm) {
	const rows = frm.employees_datatable.getRows();
	const checked_rows = frm.employees_datatable.rowmanager.getCheckedRows();

	return checked_rows.map((idx) => {
		const row_content = {};
		rows[idx].forEach((cell) => {
			const fieldname = get_bulk_salary_cell_fieldname(cell);
			if (["employee", "base", "custom_declared_income", "variable"].includes(fieldname)) {
				row_content[fieldname] = cell.content;
			}
		});
		if (row_content.custom_declared_income === undefined) {
			row_content.custom_declared_income = row_content.base || 0;
		}
		return row_content;
	});
}

function get_bulk_salary_cell_fieldname(cell) {
	const column = cell.column || {};
	const value = column.id || column.name || column.content || "";
	const normalized = String(value).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
	if (normalized === "declared_income") return "custom_declared_income";
	return normalized;
}

function sync_declared_income_update_button(frm) {
	if (!frm.employees_datatable) return;
	frm.checked_rows_indexes = frm.employees_datatable.rowmanager.getCheckedRows();

	if (!frm.checked_rows_indexes.length) {
		frm.remove_custom_button(__("Declared Income"), __("Update"));
		frm.__qcmc_declared_income_button_added = false;
		return;
	}

	ensure_declared_income_update_button(frm);
}

function ensure_declared_income_update_button(frm) {
	if (!frm.employees_datatable || !frm.checked_rows_indexes || !frm.checked_rows_indexes.length) return;
	if (frm.__qcmc_declared_income_button_added) return;

	frm.__qcmc_declared_income_button_added = true;
	frm.add_custom_button(
		__("Declared Income"),
		function() {
			const dialog = new frappe.ui.Dialog({
				title: __("Set Declared Income for selected employees"),
				fields: [
					{
						label: __("Declared Income"),
						fieldname: "custom_declared_income",
						fieldtype: "Currency",
					},
				],
				primary_action_label: __("Update"),
				primary_action(values) {
					const column = frm.employees_datatable.datamanager.columns.find(
						(col) => col.id === "custom_declared_income",
					);
					if (!column) return;

					frm.checked_rows_indexes.forEach((row_idx) => {
						frm.employees_datatable.cellmanager.updateCell(
							column.colIndex,
							row_idx,
							values.custom_declared_income,
							true,
						);
					});
					dialog.hide();
				},
			});
			dialog.show();
		},
		__("Update"),
	);
}

function is_bulk_salary_structure_assignment_route() {
	const route = frappe.get_route ? frappe.get_route() : [];
	return route && route[0] === "Form" && route[1] === "Bulk Salary Structure Assignment";
}

function is_ignored_bulk_salary_doctype(doctype) {
	return !doctype || ["None", "undefined", "null", "DocType"].includes(String(doctype));
}

function get_bulk_salary_call_options(args) {
	if (typeof args[0] === "string") {
		return {
			method: args[0],
			args: args[1] || {},
			callback: args[2],
		};
	}

	return args[0] || {};
}

function apply_bulk_salary_role_scope(frm) {
	const scope = get_bulk_salary_role_scope(frm);
	if (!scope) return;

	setup_bulk_salary_role_queries(frm, scope);
	apply_bulk_salary_default_values(frm, scope);
	apply_bulk_salary_field_locks(frm, scope);
}

function setup_bulk_salary_role_queries(frm, scope) {
	frm.set_query("salary_structure", () => ({
		filters: {
			company: ["in", scope.companies],
			payroll_frequency: ["in", scope.payroll_frequencies],
			docstatus: 1,
			is_active: "Yes",
		},
	}));

	frm.set_query("company", () => ({
		filters: {
			name: ["in", scope.companies],
		},
	}));

	if (scope.branch_restricted) {
		frm.set_query("branch", () => ({
			filters: {
				name: ["in", scope.branches],
			},
		}));
	}
}

async function apply_bulk_salary_default_values(frm, scope) {
	const salary_structures = await get_allowed_bulk_salary_structures(scope);
	const salary_structure_names = salary_structures.map((row) => row.name);

	if (frm.doc.salary_structure && !salary_structure_names.includes(frm.doc.salary_structure)) {
		await frm.set_value("salary_structure", "");
	}

	if (salary_structure_names.length === 1 && frm.doc.salary_structure !== salary_structure_names[0]) {
		await frm.set_value("salary_structure", salary_structure_names[0]);
	}

	await sync_bulk_salary_company_from_structure(frm);

	if (scope.companies.length === 1 && frm.doc.company !== scope.companies[0]) {
		frm.set_value("company", scope.companies[0]);
	}

	if (scope.branch_restricted && scope.branches.length === 1 && frm.doc.branch !== scope.branches[0]) {
		frm.set_value("branch", scope.branches[0]);
	}

	if (
		scope.branch_restricted &&
		scope.branches.length > 1 &&
		frm.doc.branch &&
		!scope.branches.includes(frm.doc.branch)
	) {
		frm.set_value("branch", "");
	}

	if (scope.employment_types.length === 1 && frm.doc.employment_type !== scope.employment_types[0]) {
		frm.set_value("employment_type", scope.employment_types[0]);
	}

	const employment_field = frm.get_field("employment_type");
	if (employment_field) {
		employment_field.df.options = scope.employment_types.join("\n");
		employment_field.refresh();
	}
}

function apply_bulk_salary_field_locks(frm, scope) {
	frm.set_df_property("salary_structure", "read_only", 0);
	frm.set_df_property("company", "read_only", scope.companies.length === 1 ? 1 : 0);
	frm.set_df_property("branch", "read_only", scope.branch_restricted && scope.branches.length === 1 ? 1 : 0);
	frm.set_df_property("employment_type", "read_only", scope.employment_types.length === 1 ? 1 : 0);
}

function get_bulk_salary_role_scope(frm) {
	if (frappe.session && frappe.session.user === "Administrator") return null;
	if (!frappe.user || !frappe.user.has_role) return null;

	const rules = get_bulk_salary_role_rules().filter((rule) => frappe.user.has_role(rule.role));
	if (!rules.length) return null;

	const current_payroll_type = get_bulk_salary_payroll_type(frm.doc.salary_structure);
	const matching_rules = current_payroll_type
		? rules.filter((rule) => rule.payroll_type === current_payroll_type)
		: rules;
	const effective_rules = matching_rules.length ? matching_rules : rules;
	const branch_restricted = effective_rules.every((rule) => (rule.branches || []).length);

	return {
		companies: unique_values(effective_rules.map((rule) => rule.company)),
		payroll_frequencies: unique_values(effective_rules.map((rule) => get_salary_structure_payroll_frequency(rule.payroll_type))),
		branches: branch_restricted
			? unique_values(effective_rules.flatMap((rule) => rule.branches || []))
			: [],
		branch_restricted,
		employment_types: unique_values(effective_rules.flatMap((rule) => rule.employment_types || [])),
	};
}

function get_bulk_salary_role_rules() {
	const regular = ["Regular", "Probation", "Probationary"];
	const provincial = [
		"Bacolod", "Cebu", "Cagayan De Oro", "Iloilo", "Davao", "Zamboanga",
		"La Union", "Pampanga", "Laguna", "Quezon"
	];

	return [
		{ role: "Monthly QC", company: "QC Styropackaging Corporation", payroll_type: "Monthly", employment_types: regular },
		{ role: "Monthly MC", company: "Multiplast Corporation", payroll_type: "Monthly", employment_types: regular },
		{ role: "Monthly SMB", company: "QC Styropackaging Corporation", payroll_type: "Monthly", branches: ["Guyong", "Sta. Clara"], employment_types: regular },
		{ role: "Monthly VAL", company: "Multiplast Corporation", payroll_type: "Monthly", branches: ["Valenzuela"], employment_types: regular },
		{ role: "MC Prov Merch", company: "Multiplast Corporation", payroll_type: "Monthly", employment_types: ["Provincial Merchandise"] },
		{ role: "Weekly QC EDSA", company: "QC Styropackaging Corporation", payroll_type: "Weekly", branches: ["QC Edsa"], employment_types: regular },
		{ role: "Weekly MC EDSA", company: "Multiplast Corporation", payroll_type: "Weekly", branches: ["QC Edsa"], employment_types: regular },
		{ role: "Weekly QC Agency", company: "QC Styropackaging Corporation", payroll_type: "Weekly", branches: ["QC Edsa"], employment_types: ["Agency"] },
		{ role: "Weekly QC SMB", company: "QC Styropackaging Corporation", payroll_type: "Weekly", branches: ["Guyong", "Sta. Clara"], employment_types: regular },
		{ role: "Weekly MC VAL", company: "Multiplast Corporation", payroll_type: "Weekly", branches: ["Valenzuela"], employment_types: regular },
		{ role: "Weekly QC Prov", company: "QC Styropackaging Corporation", payroll_type: "Weekly", branches: provincial, employment_types: regular },
		{ role: "Weekly MC Prov", company: "Multiplast Corporation", payroll_type: "Weekly", branches: provincial, employment_types: regular },
		{ role: "Weekly MC Prov Agency", company: "Multiplast Corporation", payroll_type: "Weekly", branches: provincial, employment_types: ["Agency"] },
	];
}

function get_bulk_salary_payroll_type(salary_structure) {
	const value = String(salary_structure || "").toLowerCase();
	if (value.includes("weekly")) return "Weekly";
	if (value.includes("semi") || value.includes("month")) return "Monthly";
	return "";
}

function get_salary_structure_payroll_frequency(payroll_type) {
	return payroll_type === "Weekly" ? "Weekly" : "Bimonthly";
}

function get_allowed_bulk_salary_structures(scope) {
	return frappe.db.get_list("Salary Structure", {
		fields: ["name", "company", "payroll_frequency"],
		filters: {
			company: ["in", scope.companies],
			payroll_frequency: ["in", scope.payroll_frequencies],
			docstatus: 1,
			is_active: "Yes",
		},
		limit: 50,
	});
}

async function sync_bulk_salary_company_from_structure(frm) {
	if (!frm.doc.salary_structure) return;

	const result = await frappe.db.get_value(
		"Salary Structure",
		frm.doc.salary_structure,
		["company", "currency"],
	);
	const values = result && result.message;
	if (!values) return;

	if (values.company && frm.doc.company !== values.company) {
		await frm.set_value("company", values.company);
	}
	if (values.currency && frm.doc.currency !== values.currency) {
		await frm.set_value("currency", values.currency);
	}
}

function unique_values(values) {
	return Array.from(new Set((values || []).filter(Boolean)));
}
"""

	if frappe.db.exists("Client Script", script_name):
		doc = frappe.get_doc("Client Script", script_name)
		doc.enabled = 1
		doc.dt = "Bulk Salary Structure Assignment"
		doc.view = "Form"
		doc.script = script
		doc.save()
	else:
		frappe.get_doc(
			{
				"doctype": "Client Script",
				"name": script_name,
				"dt": "Bulk Salary Structure Assignment",
				"view": "Form",
				"enabled": 1,
				"script": script,
			}
		).insert()

	frappe.db.commit()
