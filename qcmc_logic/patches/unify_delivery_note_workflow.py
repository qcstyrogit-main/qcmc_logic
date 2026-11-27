"""Production-capable transition to a single Head Office Delivery Note workflow.

Run with dry_run=True before migration. No fulfillment or stock posting.
The legacy states are deliberately reset to Draft, not auto-approved.
"""
import frappe
from frappe import _
from frappe.utils import cint

RETIRED = {"For Stock Confirmation", "For DR Printing"}
RELEASE = ("Draft", "Submit for Delivery", "To Deliver and Bill", "Invoicing Clerk")
RELEASE_CONDITION = "doc.items and doc.custom_dr_number"
PROVINCIAL = ("Draft", "Tag To Active", "Completed", "Provincial Stock User")
KNOWN = {
    RELEASE, PROVINCIAL,
    ("Draft", "Submit for Stock Confirmation", "For Stock Confirmation", "Head Office Sales User"),
    ("For Stock Confirmation", "Submit For DR Printing", "For DR Printing", "Sales Coordinator"),
    ("For DR Printing", "Submit for Delivery", "To Deliver and Bill", "Head Office Sales User"),
    ("To Deliver and Bill", "Tag To Active", "Completed", "Stock Confirm User"),
    ("Completed", "Cancel", "Cancelled", "Stock Confirm User"),
    ("Completed", "Cancel", "Cancelled", "Provincial Stock User"),
}
REQUIRED = KNOWN - {r for r in KNOWN if r[0] in RETIRED or r[2] in RETIRED or r == RELEASE}


def signature(row):
    return (row.state, row.action, row.next_state, row.allowed)


def inspect_workflow():
    active = frappe.get_all("Workflow", filters={"document_type": "Delivery Note", "is_active": 1}, pluck="name")
    if active != ["Delivery Note"]:
        frappe.throw(_("Expected the single active Delivery Note workflow; review configuration before proceeding."))
    workflow = frappe.get_doc("Workflow", "Delivery Note")
    if workflow.workflow_state_field != "workflow_state":
        frappe.throw(_("Unexpected Delivery Note workflow state field."))
    routes = [signature(row) for row in workflow.transitions]
    normalized = [RELEASE if r == ("Draft", "Release for Delivery", "To Deliver and Bill", "Invoicing Clerk") else r for r in routes]
    if len(set(normalized)) != len(normalized) or set(normalized) - KNOWN or not REQUIRED.issubset(normalized):
        frappe.throw(_("Unexpected Delivery Note workflow transitions. No migration was performed."))
    expected_states = {"Draft": 0, "For Stock Confirmation": 0, "For DR Printing": 0,
                       "To Deliver and Bill": 0, "Completed": 1, "Cancelled": 2}
    if any(row.state not in expected_states or cint(row.doc_status) != expected_states[row.state] for row in workflow.states):
        frappe.throw(_("Unexpected Delivery Note workflow state or docstatus."))
    if not {"Draft", "To Deliver and Bill", "Completed", "Cancelled"}.issubset({row.state for row in workflow.states}):
        frappe.throw(_("Required Delivery Note workflow states are missing."))
    return workflow


def _legacy_rows(lock=False):
    sql = """
        SELECT name, company, workflow_state, docstatus, status, custom_dr_number
        FROM {0}tabDelivery Note{0}
        WHERE workflow_state IN ('For Stock Confirmation', 'For DR Printing')
        ORDER BY name
    """.format(chr(96))
    if lock:
        sql += " FOR UPDATE"
    return frappe.db.sql(sql, as_dict=True)


def _report(rows):
    has_schedule_link = frappe.db.has_column("Delivery Note Item", "custom_so_delivery_schedule")
    result = {"site": frappe.local.site, "legacy_drafts": len(rows), "schedule_link_installed": bool(has_schedule_link), "by_state": {},
              "by_company": {}, "requires_schedule_review": [], "documents": [], "changed": 0}
    for row in rows:
        if cint(row.docstatus) != 0:
            frappe.throw(_("Non-draft Delivery Note {0} has a retired state. Resolve it before migration.").format(row.name))
        result["by_state"][row.workflow_state] = result["by_state"].get(row.workflow_state, 0) + 1
        result["by_company"][row.company] = result["by_company"].get(row.company, 0) + 1
        fields = ["against_sales_order", "so_detail"] + (["custom_so_delivery_schedule"] if has_schedule_link else [])
        items = frappe.get_all("Delivery Note Item", filters={"parent": row.name}, fields=fields)
        if any((i.against_sales_order or i.so_detail) and not i.get("custom_so_delivery_schedule") for i in items):
            result["requires_schedule_review"].append(row.name)
        result["documents"].append({"name": row.name, "company": row.company, "from": row.workflow_state,
            "to": "Draft", "has_dr_number": bool((row.custom_dr_number or "").strip())})
    return result


def _update_workflow(workflow):
    transitions = []
    found = False
    for row in workflow.transitions:
        route = signature(row)
        if row.state in RETIRED or row.next_state in RETIRED:
            continue
        if route in (RELEASE, ("Draft", "Release for Delivery", "To Deliver and Bill", "Invoicing Clerk")):
            row.action = RELEASE[1]
            row.condition = RELEASE_CONDITION
            found = True
        transitions.append(row)
    if not found:
        transitions.append(dict(state=RELEASE[0], action=RELEASE[1], next_state=RELEASE[2],
            allowed=RELEASE[3], allow_self_approval=1, condition=RELEASE_CONDITION))
    workflow.set("states", [row for row in workflow.states if row.state not in RETIRED])
    workflow.set("transitions", transitions)
    if workflow.meta.has_field("workflow_data"):
        workflow.workflow_data = None
    workflow.save(ignore_permissions=True)


def execute(dry_run=False):
    if type(dry_run) is not bool:
        frappe.throw(_("dry_run must be True or False."))
    if not frappe.flags.in_migrate and frappe.session.user != "Administrator":
        frappe.throw(_("Administrator is required for this migration."), frappe.PermissionError)
    for field in ("workflow_state", "custom_dr_number"):
        if not frappe.db.has_column("Delivery Note", field):
            frappe.throw(_("Delivery Note schema is not ready."))
    if not dry_run and not frappe.db.has_column("Delivery Note Item", "custom_so_delivery_schedule"):
        frappe.throw(_("Install the Delivery Schedule schema first through the registered prerequisite patch."))
    workflow = inspect_workflow()
    rows = _legacy_rows(lock=not dry_run)
    result = _report(rows)
    result["dry_run"] = dry_run
    if dry_run:
        return result
    # The normal migration/bench execute transaction owns commit. Do not commit here.
    for row in rows:
        frappe.db.set_value("Delivery Note", row.name, {"workflow_state": "Draft", "status": "Draft"})
        frappe.get_doc("Delivery Note", row.name).add_comment("Info",
            _("Workflow migration: {0} returned to Draft. DR number, items, invoice links and posting date preserved; no approval or submission performed.").format(row.workflow_state))
        result["changed"] += 1
    _update_workflow(workflow)
    frappe.clear_cache(doctype="Workflow")
    frappe.clear_cache(doctype="Delivery Note")
    if _legacy_rows():
        frappe.throw(_("Retired workflow states remain after migration."))
    return result
