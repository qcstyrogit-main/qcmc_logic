import frappe


def execute():
	"""Rename the Storage Location type without changing location identifiers."""
	if not frappe.db.table_exists("Storage Location"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabStorage Location`
		SET location_type = 'Cube'
		WHERE location_type = 'Column'
		"""
	)
