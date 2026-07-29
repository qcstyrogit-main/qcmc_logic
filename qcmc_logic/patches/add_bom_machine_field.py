import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"BOM": [
				{
					"fieldname": "custom_machine",
					"label": "Machine",
					"fieldtype": "Link",
					"options": "Workstation",
					"insert_after": "custom_soph",
					"in_standard_filter": 1,
				},
			]
		},
		ignore_validate=True,
	)
	add_bom_search_field("custom_machine")
	frappe.clear_cache(doctype="BOM")


def add_bom_search_field(fieldname):
	search_fields = frappe.db.get_value("DocType", "BOM", "search_fields") or ""
	fields = [field.strip() for field in search_fields.split(",") if field.strip()]

	if fieldname not in fields:
		fields.append(fieldname)
		frappe.db.set_value(
			"DocType",
			"BOM",
			"search_fields",
			",".join(fields),
			update_modified=False,
		)
