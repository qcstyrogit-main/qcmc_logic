import frappe


def execute():
	"""Create the Shift Type explicitly identified by the approved schedule template."""
	if frappe.db.exists("Shift Type", "Shift Type 1"):
		return

	frappe.get_doc(
		{
			"doctype": "Shift Type",
			"__newname": "Shift Type 1",
			"start_time": "06:00:00",
			"end_time": "18:00:00",
		}
	).insert(ignore_permissions=True)

