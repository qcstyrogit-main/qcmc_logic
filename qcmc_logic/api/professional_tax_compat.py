import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


@frappe.whitelist()
def install_salary_component_type_field():
	create_custom_field(
		"Salary Component",
		{
			"fieldname": "component_type",
			"label": "Component Type",
			"fieldtype": "Select",
			"options": "\nProfessional Tax",
			"insert_after": "type",
			"description": "Compatibility field used by the HRMS Professional Tax Deductions report.",
			"allow_on_submit": 1,
		},
		ignore_validate=True,
	)

	frappe.clear_cache(doctype="Salary Component")
	frappe.db.commit()
	return "Salary Component component_type compatibility field installed."
