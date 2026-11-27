"""Extend workflow validation and provision terminal states for automatic draft cancellation."""
import frappe
from frappe import _
from frappe.utils import cint
from frappe.workflow.doctype.workflow.workflow import Workflow
from qcmc_logic.customs.transaction_cancellation import enabled

DEFAULT_CANCEL_STATE = "Cancelled"
ALTERNATE_CANCEL_STATE = "Cancelled (Unsubmitted)"


def _signature(row):
    return (row.state, row.action, row.next_state, row.allowed, row.condition,
            cint(row.allow_self_approval), row.get("transition_tasks"))


def ensure_terminal_state(workflow):
    """Add a terminal state only if a submittable workflow has none."""
    if not frappe.get_meta(workflow.document_type).is_submittable:
        return None
    if any(cint(row.doc_status) == 2 for row in workflow.states):
        return None
    names = {row.state for row in workflow.states}
    state = DEFAULT_CANCEL_STATE if DEFAULT_CANCEL_STATE not in names else ALTERNATE_CANCEL_STATE
    if state in names:
        frappe.throw(_("Workflow {0} has conflicting cancellation state names.").format(workflow.name))
    if not frappe.db.exists("Workflow State", state):
        frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state,
                        "style": "Danger"}).insert(ignore_permissions=True)
    return workflow.append("states", {
        "state": state, "doc_status": "2", "allow_edit": "System Manager",
        "avoid_status_override": 0, "is_optional_state": 0,
    })


def ensure_active_workflows(doc=None, method=None):
    """Called when the setting is saved and after fixture synchronization."""
    if doc is not None and doc.doctype == "System Settings":
        if not cint(doc.get("custom_allow_cancellation_before_submission")):
            return
    elif not enabled():
        return
    for name in frappe.get_all("Workflow", filters={"is_active": 1}, pluck="name"):
        workflow = frappe.get_doc("Workflow", name, for_update=True)
        state = ensure_terminal_state(workflow)
        if state:
            # Persist only the missing terminal state. Do not change existing routes
            # or run Workflow.on_update's default-state backfill against transactions.
            state.db_insert()
            workflow.db_set("modified", frappe.utils.now_datetime(), update_modified=False)
            frappe.clear_cache(doctype=workflow.document_type)
    frappe.clear_cache(doctype="Workflow")
    frappe.cache.delete_key("workflow")


class CancellationWorkflow(Workflow):
    def validate_docstatus(self):
        if enabled():
            ensure_terminal_state(self)
        states = {}
        for row in self.states:
            value = str(row.doc_status)
            if value not in ("0", "1", "2"):
                frappe.throw(_("Invalid workflow document status."))
            if row.state in states and states[row.state] != value:
                frappe.throw(_("A workflow state cannot have conflicting document statuses."))
            states[row.state] = value
        old = self.get_doc_before_save()
        old_states = {row.state: str(row.doc_status) for row in old.states} if old else {}
        old_routes = {_signature(row) for row in old.transitions
                      if old_states.get(row.state) == "0" and old_states.get(row.next_state) == "2"} if old else set()
        normal = []
        for row in self.transitions:
            if states.get(row.state) == "0" and states.get(row.next_state) == "2":
                if not frappe.get_meta(self.document_type).is_submittable:
                    frappe.throw(_("Pre-submission cancellation requires a submittable DocType."))
                if row.get("transition_tasks"):
                    frappe.throw(_("Draft cancellation transitions cannot have transition tasks. Use before_discard/on_discard hooks instead."))
                if not enabled() and _signature(row) not in old_routes:
                    frappe.throw(_("Enable Allow Cancellation Before Submission in System Settings before adding this transition."))
            else:
                normal.append(row)
        original = self.transitions
        try:
            self.transitions = normal
            super().validate_docstatus()
        finally:
            self.transitions = original
