import frappe


WORKFLOW_NAME = "Sales Order"
STATE = "To Deliver and Bill"
ACTION = "Cancel"
NEXT_STATE = "Cancelled"
TRANSITION_ROLES = (
	"Sales Coordinator",
	"Provincial Stock User",
)


def execute():
	ensure_cancel_action()
	ensure_workflow_transitions()
	ensure_provincial_stock_user_permission()
	frappe.clear_cache(doctype="Sales Order")
	frappe.cache.hdel("workflow", "Sales Order")


def ensure_cancel_action():
	if not frappe.db.exists("Workflow Action Master", ACTION):
		frappe.get_doc(
			{
				"doctype": "Workflow Action Master",
				"workflow_action_name": ACTION,
			}
		).insert(ignore_permissions=True)


def ensure_workflow_transitions():
	workflow = frappe.get_doc("Workflow", WORKFLOW_NAME)
	changed = False

	for role in TRANSITION_ROLES:
		if has_cancel_transition(workflow, role):
			continue
		workflow.append(
			"transitions",
			{
				"state": STATE,
				"action": ACTION,
				"next_state": NEXT_STATE,
				"allowed": role,
				"allow_self_approval": 1,
				"workflow_builder_id": None,
				"condition": None,
				"transition_tasks": None,
			},
		)
		changed = True

	if changed:
		workflow.save(ignore_permissions=True)


def has_cancel_transition(workflow, role):
	return any(
		transition.state == STATE
		and transition.action == ACTION
		and transition.next_state == NEXT_STATE
		and transition.allowed == role
		for transition in workflow.transitions
	)


def ensure_provincial_stock_user_permission():
	values = {
		"read": 1,
		"cancel": 1,
		"create": 0,
		"write": 0,
		"submit": 0,
		"amend": 0,
		"delete": 0,
		"export": 0,
		"share": 0,
	}
	name = frappe.db.get_value(
		"Custom DocPerm",
		{"parent": "Sales Order", "role": "Provincial Stock User", "permlevel": 0},
		"name",
	)
	if name:
		frappe.db.set_value("Custom DocPerm", name, values, update_modified=False)
		return

	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": "Sales Order",
			"role": "Provincial Stock User",
			"permlevel": 0,
			**values,
		}
	).insert(ignore_permissions=True)
