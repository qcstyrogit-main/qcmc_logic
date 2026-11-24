"""Mark legacy schedule rows for reconciliation without inventing original values."""

import frappe


def execute():
	# Existing mutable delivery_date/planned_qty values are not reliable originals.
	# Keep them intact and prevent new V2 approvals until a reviewed reconciliation.
	frappe.db.sql("""
		UPDATE `tabSO Delivery Schedule`
		SET history_status = 'Unreconciled'
		WHERE IFNULL(history_status, '') = ''
	""")
