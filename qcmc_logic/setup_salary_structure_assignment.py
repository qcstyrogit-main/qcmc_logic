import frappe


SCRIPT_NAME = "Salary Structure Assignment Role Scope"


SCRIPT = r"""frappe.ui.form.on("Salary Structure Assignment", {
	setup(frm) {
		apply_salary_assignment_role_scope(frm);
	},
	refresh(frm) {
		apply_salary_assignment_role_scope(frm);
	},
	salary_structure(frm) {
		sync_salary_assignment_from_structure(frm).then(() => {
			apply_salary_assignment_role_scope(frm);
		});
	},
	company(frm) {
		apply_salary_assignment_role_scope(frm);
	},
});

function apply_salary_assignment_role_scope(frm) {
	const scope = get_salary_assignment_role_scope(frm);
	if (!scope) return;

	setup_salary_assignment_queries(frm, scope);
	apply_salary_assignment_defaults(frm, scope);
	apply_salary_assignment_locks(frm, scope);
}

function setup_salary_assignment_queries(frm, scope) {
	frm.set_query("company", () => ({
		filters: {
			name: ["in", scope.companies],
		},
	}));

	frm.set_query("salary_structure", () => ({
		filters: {
			company: ["in", scope.companies],
			payroll_frequency: ["in", scope.payroll_frequencies],
			docstatus: 1,
			is_active: "Yes",
		},
	}));

	frm.set_query("employee", () => ({
		query: "erpnext.controllers.queries.employee_query",
		filters: get_salary_assignment_employee_filters(frm, scope),
	}));
}

function get_salary_assignment_employee_filters(frm, scope) {
	const filters = {};
	if (scope.companies.length) filters.company = ["in", scope.companies];
	if (scope.payroll_types.length) filters.custom_payroll_type = ["in", scope.payroll_types];
	if (scope.branch_restricted && scope.branches.length) filters.branch = ["in", scope.branches];
	if (scope.employment_types.length) filters.employment_type = ["in", scope.employment_types];
	return filters;
}

async function apply_salary_assignment_defaults(frm, scope) {
	if (scope.companies.length === 1 && frm.doc.company !== scope.companies[0]) {
		await frm.set_value("company", scope.companies[0]);
	}

	if (frm.doc.salary_structure) {
		await sync_salary_assignment_from_structure(frm);
	}
}

function apply_salary_assignment_locks(frm, scope) {
	frm.set_df_property("company", "read_only", scope.companies.length === 1 ? 1 : 0);
}

async function sync_salary_assignment_from_structure(frm) {
	if (!frm.doc.salary_structure) return;

	const result = await frappe.db.get_value(
		"Salary Structure",
		frm.doc.salary_structure,
		["company", "currency"]
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

function get_salary_assignment_role_scope(frm) {
	if (frappe.session && frappe.session.user === "Administrator") return null;
	if (!frappe.user || !frappe.user.has_role) return null;

	const rules = get_salary_assignment_role_rules().filter((rule) => frappe.user.has_role(rule.role));
	if (!rules.length) return null;

	const payroll_type = get_salary_assignment_payroll_type(frm.doc.salary_structure);
	const matching_rules = payroll_type ? rules.filter((rule) => rule.payroll_type === payroll_type) : rules;
	const effective_rules = matching_rules.length ? matching_rules : rules;
	const branch_restricted = effective_rules.every((rule) => (rule.branches || []).length);

	return {
		companies: unique_salary_assignment_values(effective_rules.map((rule) => rule.company)),
		payroll_types: unique_salary_assignment_values(effective_rules.map((rule) => rule.payroll_type)),
		payroll_frequencies: unique_salary_assignment_values(
			effective_rules.map((rule) => rule.payroll_type === "Weekly" ? "Weekly" : "Bimonthly")
		),
		branches: branch_restricted
			? unique_salary_assignment_values(effective_rules.flatMap((rule) => rule.branches || []))
			: [],
		branch_restricted,
		employment_types: unique_salary_assignment_values(
			effective_rules.flatMap((rule) => rule.employment_types || [])
		),
	};
}

function get_salary_assignment_role_rules() {
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

function get_salary_assignment_payroll_type(salary_structure) {
	const value = String(salary_structure || "").toLowerCase();
	if (value.includes("weekly")) return "Weekly";
	if (value.includes("semi") || value.includes("month")) return "Monthly";
	return "";
}

function unique_salary_assignment_values(values) {
	return Array.from(new Set((values || []).filter(Boolean)));
}
"""


def execute():
	doc = (
		frappe.get_doc("Client Script", SCRIPT_NAME)
		if frappe.db.exists("Client Script", SCRIPT_NAME)
		else frappe.new_doc("Client Script")
	)
	doc.update(
		{
			"name": SCRIPT_NAME,
			"dt": "Salary Structure Assignment",
			"view": "Form",
			"enabled": 1,
			"script": SCRIPT,
		}
	)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
