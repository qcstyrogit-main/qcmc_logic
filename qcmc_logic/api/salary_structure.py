import frappe


@frappe.whitelist()
def get_salary_components(component_type: str, company: str) -> list[str]:
	"""Return enabled Salary Components available to a company, without duplicates."""
	frappe.has_permission("Salary Component", ptype="read", throw=True)

	component = frappe.qb.DocType("Salary Component")
	account = frappe.qb.DocType("Salary Component Account")
	rows = (
		frappe.qb.from_(component)
		.left_join(account)
		.on(account.parent == component.name)
		.select(component.name, account.company)
		.where((component.type == component_type) & (component.disabled == 0))
		.orderby(component.name)
	).run(as_dict=True)

	return list(
		dict.fromkeys(
			row.name for row in rows if not row.company or row.company == company
		)
	)
