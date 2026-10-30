import frappe


def execute():
	"""Make existing draft production plans enter the new editable Active state."""
	frappe.db.sql(
		"""
		update `tabWeekly Production Plan`
		set workflow_state = 'Active'
		where docstatus = 0
			and coalesce(workflow_state, '') = ''
		"""
	)
