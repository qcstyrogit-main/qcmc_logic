import frappe


REGULAR_EMPLOYMENT_TYPES = ("Regular", "Probation", "Probationary")
PROVINCIAL_BRANCHES = (
	"Bacolod",
	"Cebu",
	"Cagayan De Oro",
	"Iloilo",
	"Davao",
	"Zamboanga",
	"La Union",
	"Pampanga",
	"Laguna",
	"Quezon",
)


PAYROLL_ROLE_RULES = (
	{
		"role": "Monthly QC",
		"company": "QC Styropackaging Corporation",
		"payroll_type": "Monthly",
		"employment_types": REGULAR_EMPLOYMENT_TYPES,
	},
	{
		"role": "Monthly MC",
		"company": "Multiplast Corporation",
		"payroll_type": "Monthly",
		"employment_types": REGULAR_EMPLOYMENT_TYPES,
	},
	{
		"role": "Monthly SMB",
		"company": "QC Styropackaging Corporation",
		"payroll_type": "Monthly",
		"branches": ("Guyong", "Sta. Clara"),
		"employment_types": REGULAR_EMPLOYMENT_TYPES,
	},
	{
		"role": "Monthly VAL",
		"company": "Multiplast Corporation",
		"payroll_type": "Monthly",
		"branches": ("Valenzuela",),
		"employment_types": REGULAR_EMPLOYMENT_TYPES,
	},
	{
		"role": "MC Prov Merch",
		"company": "Multiplast Corporation",
		"payroll_type": "Monthly",
		"employment_types": ("Provincial Merchandise",),
		"payroll_period_mode": "calendar_bimonthly",
	},
	{
		"role": "Weekly QC EDSA",
		"company": "QC Styropackaging Corporation",
		"payroll_type": "Weekly",
		"branches": ("QC Edsa",),
		"employment_types": REGULAR_EMPLOYMENT_TYPES,
	},
	{
		"role": "Weekly MC EDSA",
		"company": "Multiplast Corporation",
		"payroll_type": "Weekly",
		"branches": ("QC Edsa",),
		"employment_types": REGULAR_EMPLOYMENT_TYPES,
	},
	{
		"role": "Weekly QC Agency",
		"company": "QC Styropackaging Corporation",
		"payroll_type": "Weekly",
		"branches": ("QC Edsa",),
		"employment_types": ("Agency",),
	},
	{
		"role": "Weekly QC SMB",
		"company": "QC Styropackaging Corporation",
		"payroll_type": "Weekly",
		"branches": ("Guyong", "Sta. Clara"),
		"employment_types": REGULAR_EMPLOYMENT_TYPES,
	},
	{
		"role": "Weekly MC VAL",
		"company": "Multiplast Corporation",
		"payroll_type": "Weekly",
		"branches": ("Valenzuela",),
		"employment_types": REGULAR_EMPLOYMENT_TYPES,
	},
	{
		"role": "Weekly QC Prov",
		"company": "QC Styropackaging Corporation",
		"payroll_type": "Weekly",
		"branches": PROVINCIAL_BRANCHES,
		"employment_types": REGULAR_EMPLOYMENT_TYPES,
	},
	{
		"role": "Weekly MC Prov",
		"company": "Multiplast Corporation",
		"payroll_type": "Weekly",
		"branches": PROVINCIAL_BRANCHES,
		"employment_types": REGULAR_EMPLOYMENT_TYPES,
	},
	{
		"role": "Weekly MC Prov Agency",
		"company": "Multiplast Corporation",
		"payroll_type": "Weekly",
		"branches": PROVINCIAL_BRANCHES,
		"employment_types": ("Agency",),
	},
)


def get_payroll_role_rules(user=None, payroll_type=None):
	user = user or frappe.session.user
	if user == "Administrator":
		return []

	user_roles = set(frappe.get_roles(user))
	rules = [rule for rule in PAYROLL_ROLE_RULES if rule["role"] in user_roles]
	if payroll_type:
		rules = [rule for rule in rules if rule.get("payroll_type") == payroll_type]
	return rules


def get_payroll_role_scope(user=None, payroll_type=None):
	rules = get_payroll_role_rules(user=user, payroll_type=payroll_type)
	if not rules:
		return None

	return {
		"companies": _unique(rule.get("company") for rule in rules),
		"payroll_types": _unique(rule.get("payroll_type") for rule in rules),
		"branches": _unique(branch for rule in rules for branch in rule.get("branches", ())),
		"employment_types": _unique(
			employment_type
			for rule in rules
			for employment_type in rule.get("employment_types", ())
		),
		"rules": rules,
	}


def employee_matches_payroll_role_scope(employee, rules):
	if frappe.session.user == "Administrator" or not rules:
		return True

	for rule in rules:
		if employee.get("company") != rule.get("company"):
			continue
		if employee.get("custom_payroll_type") != rule.get("payroll_type"):
			continue
		if rule.get("branches") and employee.get("branch") not in rule.get("branches"):
			continue
		if (
			rule.get("employment_types")
			and employee.get("employment_type") not in rule.get("employment_types")
		):
			continue
		return True

	return False


def get_payroll_type_from_salary_structure(salary_structure):
	if not salary_structure:
		return None

	name = salary_structure.lower()
	if "weekly" in name:
		return "Weekly"
	if "semi" in name or "month" in name:
		return "Monthly"
	return None


def _unique(values):
	result = []
	for value in values:
		if value and value not in result:
			result.append(value)
	return result
