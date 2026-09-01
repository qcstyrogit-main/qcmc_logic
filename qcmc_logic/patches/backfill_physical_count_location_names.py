import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	"""Populate the display name without changing the canonical Location ID."""
	frappe.reload_doc("qcmc_logics", "doctype", "qcmc_physical_count_result")
	# Location is an Inventory Dimension Custom Field placed in its own section.
	# Make Location Name a Custom Field too so it appears directly below Location
	# instead of much earlier among the child DocType's standard fields.
	create_custom_fields(
		{
			"QCMC Physical Count Result": [
				{
					"fieldname": "location_name",
					"label": "Location Name",
					"fieldtype": "Data",
					"insert_after": "location",
					"read_only": 1,
				}
			]
		},
		update=True,
		ignore_validate=True,
	)
	frappe.db.sql(
		"""
		update `tabQCMC Physical Count Result` result
		left join `tabStorage Location` location
			on location.name = coalesce(
				nullif(result.location, ''),
				nullif(result.inventory_location, '')
			)
		set result.location_name = coalesce(
			nullif(location.location_name, ''),
			location.name,
			result.location
		)
		where ifnull(result.location_name, '') = ''
		"""
	)
