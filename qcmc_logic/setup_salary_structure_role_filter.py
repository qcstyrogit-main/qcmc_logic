import frappe


SCRIPT_NAME = "Salary Structure Payroll Role Filter"

SCRIPT = r"""
frappe.listview_settings["Salary Structure"] = {
	onload(listview) {
		add_salary_structure_bulk_assignment_button(listview);
		apply_salary_structure_role_filter(listview);
	},
	refresh(listview) {
		apply_salary_structure_role_filter(listview);
	},
};

function add_salary_structure_bulk_assignment_button(listview) {
	if (listview.__qcmc_bulk_assignment_button_added) return;

	listview.__qcmc_bulk_assignment_button_added = true;
	listview.page.add_inner_button(__("Bulk Salary Structure Assignment"), function() {
		frappe.set_route("Form", "Bulk Salary Structure Assignment");
	});
}

function apply_salary_structure_role_filter(listview) {
	const scope = get_salary_structure_role_scope();
	if (!scope || listview.__qcmc_salary_structure_role_filtering) return;

	const filters = [];
	if (scope.companies.length) {
		filters.push(["Salary Structure", "company", "in", scope.companies]);
	}
	if (scope.payroll_frequencies.length) {
		filters.push(["Salary Structure", "payroll_frequency", "in", scope.payroll_frequencies]);
	}

	if (!filters.length || salary_structure_filters_exist(listview, filters)) return;

	listview.__qcmc_salary_structure_role_filtering = true;
	remove_salary_structure_role_filters(listview).then(function() {
		return listview.filter_area.add(filters);
	}).then(function() {
		listview.__qcmc_salary_structure_role_filtering = false;
	}).catch(function() {
		listview.__qcmc_salary_structure_role_filtering = false;
	});
}

function remove_salary_structure_role_filters(listview) {
	remove_all_salary_structure_filters_for_field(listview, "company");
	remove_all_salary_structure_filters_for_field(listview, "payroll_frequency");
	return Promise.resolve();
}

function remove_all_salary_structure_filters_for_field(listview, fieldname) {
	const fields_dict = listview.filter_area && listview.filter_area.list_view
		? listview.filter_area.list_view.page.fields_dict
		: {};
	if (fields_dict && fields_dict[fieldname]) {
		fields_dict[fieldname].set_value("");
	}

	const filter_list = listview.filter_area && listview.filter_area.filter_list;
	if (!filter_list || !filter_list.filters) return;

	filter_list.filters.slice().forEach(function(filter) {
		if (filter.field && filter.field.df && filter.field.df.fieldname === fieldname) {
			filter.remove(true);
		}
	});
	filter_list.filters = filter_list.filters.filter(function(filter) {
		return !(filter.field && filter.field.df && filter.field.df.fieldname === fieldname);
	});
	filter_list.update_filter_button();
}

function salary_structure_filters_exist(listview, filters) {
	const current_filters = (listview.filter_area && listview.filter_area.get()) || [];
	return filters.every(function(required_filter) {
		return current_filters.some(function(filter) {
			return (
				filter[0] === required_filter[0] &&
				filter[1] === required_filter[1] &&
				filter[2] === required_filter[2] &&
				same_salary_structure_filter_value(filter[3], required_filter[3])
			);
		});
	});
}

function same_salary_structure_filter_value(left, right) {
	const normalize = function(value) {
		if (Array.isArray(value)) return value.slice().sort().join("|");
		return String(value || "").split(",").map((item) => item.trim()).filter(Boolean).sort().join("|");
	};
	return normalize(left) === normalize(right);
}

function get_salary_structure_role_scope() {
	if (frappe.session && frappe.session.user === "Administrator") return null;
	if (!frappe.user || !frappe.user.has_role) return null;

	const rules = get_salary_structure_role_rules().filter((rule) => frappe.user.has_role(rule.role));
	if (!rules.length) return null;

	return {
		companies: unique_salary_structure_values(rules.map((rule) => rule.company)),
		payroll_frequencies: unique_salary_structure_values(
			rules.map((rule) => (rule.payroll_type === "Weekly" ? "Weekly" : "Bimonthly"))
		),
	};
}

function get_salary_structure_role_rules() {
	return [
		{ role: "Monthly QC", company: "QC Styropackaging Corporation", payroll_type: "Monthly" },
		{ role: "Monthly MC", company: "Multiplast Corporation", payroll_type: "Monthly" },
		{ role: "Monthly SMB", company: "QC Styropackaging Corporation", payroll_type: "Monthly" },
		{ role: "Monthly VAL", company: "Multiplast Corporation", payroll_type: "Monthly" },
		{ role: "MC Prov Merch", company: "Multiplast Corporation", payroll_type: "Monthly" },
		{ role: "Weekly QC EDSA", company: "QC Styropackaging Corporation", payroll_type: "Weekly" },
		{ role: "Weekly MC EDSA", company: "Multiplast Corporation", payroll_type: "Weekly" },
		{ role: "Weekly QC Agency", company: "QC Styropackaging Corporation", payroll_type: "Weekly" },
		{ role: "Weekly QC SMB", company: "QC Styropackaging Corporation", payroll_type: "Weekly" },
		{ role: "Weekly MC VAL", company: "Multiplast Corporation", payroll_type: "Weekly" },
		{ role: "Weekly QC Prov", company: "QC Styropackaging Corporation", payroll_type: "Weekly" },
		{ role: "Weekly MC Prov", company: "Multiplast Corporation", payroll_type: "Weekly" },
		{ role: "Weekly MC Prov Agency", company: "Multiplast Corporation", payroll_type: "Weekly" },
	];
}

function unique_salary_structure_values(values) {
	return Array.from(new Set((values || []).filter(Boolean)));
}
"""


def execute():
	doc = frappe.db.exists("Client Script", SCRIPT_NAME)
	if doc:
		client_script = frappe.get_doc("Client Script", SCRIPT_NAME)
	else:
		client_script = frappe.new_doc("Client Script")
		client_script.name = SCRIPT_NAME

	client_script.update(
		{
			"dt": "Salary Structure",
			"view": "List",
			"enabled": 1,
			"script": SCRIPT,
		}
	)
	client_script.save(ignore_permissions=True)
	frappe.db.commit()
	return SCRIPT_NAME
