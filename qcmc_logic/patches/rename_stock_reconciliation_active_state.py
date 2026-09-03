import frappe


WORKFLOW = "PC_WORKFLOW"
OLD_STATE = "Active"
NEW_STATE = "Close Inventory"


def execute():
	"""Rename only the final state/action of the Physical Count workflow."""
	ensure_workflow_state()
	ensure_workflow_action()

	frappe.db.set_value(
		"Workflow Document State",
		{"parent": WORKFLOW, "state": OLD_STATE},
		{"state": NEW_STATE, "update_value": NEW_STATE},
		update_modified=False,
	)
	frappe.db.set_value(
		"Workflow Transition",
		{"parent": WORKFLOW, "next_state": OLD_STATE},
		{"action": NEW_STATE, "next_state": NEW_STATE},
		update_modified=False,
	)

	# Preserve the correct final label on already submitted reconciliations.
	frappe.db.set_value(
		"Stock Reconciliation",
		{"workflow_state": OLD_STATE, "docstatus": 1},
		"workflow_state",
		NEW_STATE,
		update_modified=False,
	)
	frappe.clear_cache(doctype="Stock Reconciliation")


def ensure_workflow_state():
	if not frappe.db.exists("Workflow State", NEW_STATE):
		frappe.get_doc({
			"doctype": "Workflow State",
			"workflow_state_name": NEW_STATE,
		}).insert(ignore_permissions=True)


def ensure_workflow_action():
	if not frappe.db.exists("Workflow Action Master", NEW_STATE):
		frappe.get_doc({
			"doctype": "Workflow Action Master",
			"workflow_action_name": NEW_STATE,
		}).insert(ignore_permissions=True)
