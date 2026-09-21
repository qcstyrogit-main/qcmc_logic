import re

import frappe

from qcmc_logic.qcmc_logics.doctype.storage_location.storage_location import (
	refresh_storage_location_paths,
)


def execute():
	"""Replace the former Column label in Storage Location display names."""
	if not frappe.db.table_exists("Storage Location"):
		return

	locations = frappe.get_all(
		"Storage Location",
		filters=[["location_name", "like", "%Column%"]],
		fields=["name", "location_name"],
		limit_page_length=0,
	)

	for location in locations:
		location_name = re.sub(
			r"\bcolumn\b",
			"CUBE",
			location.location_name,
			flags=re.IGNORECASE,
		)
		if location_name != location.location_name:
			frappe.db.set_value(
				"Storage Location",
				location.name,
				"location_name",
				location_name,
				update_modified=False,
			)

	if locations:
		refresh_storage_location_paths()
