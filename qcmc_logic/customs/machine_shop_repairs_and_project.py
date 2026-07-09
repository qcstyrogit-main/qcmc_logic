import frappe
from frappe.utils import add_days, getdate, now_datetime

from qcmc_logic.customs.machine_shop_job_request import REQUESTOR_ROLES

MSRP_DT = "Machine Shop Repairs and Project"
REWORK_LOG_DT = "MSRP Rework Log"
WORKFLOW_NAME = "MS Repair & Project"

DEFAULT_ACCEPTANCE_PERIOD_DAYS = 5
COMPLETION_ROLES = frozenset(["Machine Shop Foreman", "Machine Shop Supervisor"])
BACK_JOB_REASON_OPTIONS = "\nIncomplete Work\nQuality Issue\nWrong Specification\nOther"

OWNER_MATCH_CONDITION = (
    'frappe.session.user == frappe.db.get_value('
    '"Machine Shop Job Request", doc.msjr_no, "owner")'
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_msjr_company(msjr_no):
    return frappe.db.get_value("Machine Shop Job Request", msjr_no, "company") if msjr_no else None


def _get_msjr_owner(msjr_no):
    return frappe.db.get_value("Machine Shop Job Request", msjr_no, "owner") if msjr_no else None


def _compute_acceptance_due_date(served_date, msjr_no):
    company = _get_msjr_company(msjr_no)

    period_days = None
    holiday_dates = set()
    if company:
        period_days = frappe.db.get_value("Company", company, "back_job_acceptance_period_days")
        holiday_list = frappe.db.get_value("Company", company, "default_holiday_list")
        if holiday_list:
            holiday_dates = set(
                frappe.get_all("Holiday", filters={"parent": holiday_list}, pluck="holiday_date")
            )
    period_days = period_days or DEFAULT_ACCEPTANCE_PERIOD_DAYS

    current = getdate(served_date)
    counted = 0
    while counted < period_days:
        current = add_days(current, 1)
        if current.weekday() < 5 and current not in holiday_dates:
            counted += 1
    return current


# ---------------------------------------------------------------------------
# Doctype hooks
# ---------------------------------------------------------------------------

def validate(doc, method=None):
    if doc.is_new():
        return

    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    is_admin = user == "Administrator"

    old = frappe.db.get_value(
        MSRP_DT, doc.name, ["workflow_state", "served_date"], as_dict=True
    ) or {}
    old_state = old.get("workflow_state") or ""
    new_state = doc.workflow_state or ""

    # Served Date is only ever writable by Foreman/Supervisor, regardless of transition.
    if doc.served_date != old.get("served_date") and not is_admin and not (roles & COMPLETION_ROLES):
        frappe.throw(
            "Served Date can only be set by Machine Shop Foreman or Machine Shop Supervisor.",
            title="Not Permitted",
        )

    if old_state == new_state:
        return

    # Active -> Awaiting Requestor Confirmation ("Mark as Completed")
    if old_state == "Active" and new_state == "Awaiting Requestor Confirmation":
        if not doc.served_date:
            frappe.throw(
                "Served Date is required before marking this job as completed.",
                title="Served Date Required",
            )
        doc.acceptance_due_date = _compute_acceptance_due_date(doc.served_date, doc.msjr_no)

    # Awaiting Requestor Confirmation -> Completed ("Confirm Completion")
    if old_state == "Awaiting Requestor Confirmation" and new_state == "Completed":
        if not is_admin and user != _get_msjr_owner(doc.msjr_no):
            frappe.throw(
                "Only the MSJR requestor can confirm completion of this job.",
                title="Unauthorized",
            )

    # Awaiting Requestor Confirmation -> Approved ("File Back Job")
    if old_state == "Awaiting Requestor Confirmation" and new_state == "Approved":
        if not is_admin and user != _get_msjr_owner(doc.msjr_no):
            frappe.throw(
                "Only the MSJR requestor can file back this job.",
                title="Unauthorized",
            )
        if not doc.back_job_reason:
            frappe.throw("Back Job Reason is required to file back this job.", title="Reason Required")
        if doc.back_job_reason == "Other" and not doc.back_job_remarks:
            frappe.throw("Back Job Remarks are required when reason is 'Other'.", title="Remarks Required")

        doc.append("rework_history", {
            "cycle_no": len(doc.rework_history or []) + 1,
            "served_date": doc.served_date,
            "back_job_reason": doc.back_job_reason,
            "back_job_remarks": doc.back_job_remarks,
            "filed_by": user,
            "filed_on": now_datetime(),
        })

    # Approved -> Active ("Acknowledge Again")
    if old_state == "Approved" and new_state == "Active":
        for row in reversed(doc.rework_history or []):
            if not row.acknowledged_by:
                row.acknowledged_by = user
                row.acknowledged_on = now_datetime()
                break
        doc.served_date = None
        doc.acceptance_due_date = None


# ---------------------------------------------------------------------------
# Permission query conditions (list view) / document-level permission
#
# The requestor discovers and monitors their MSRP the same way they already do
# for their own Machine Shop Job Request: it simply appears in their list once
# Foreman/Supervisor tags it Active, filtered to their own MSJR. No push
# notification is sent — visibility + these permission checks are the whole
# mechanism.
# ---------------------------------------------------------------------------

READ_LIKE_PTYPES = frozenset(["read", "select", "print", "email", "report", None])
WRITE_LIKE_PTYPES = frozenset(["write", "submit"])


def msrp_permission_query(user):
    if user == "Administrator":
        return ""

    roles = set(frappe.get_roles(user))
    if "System Manager" in roles or (roles & COMPLETION_ROLES):
        return ""

    if roles & REQUESTOR_ROLES:
        return (
            f"`tab{MSRP_DT}`.msjr_no IN ("
            f"SELECT name FROM `tabMachine Shop Job Request` WHERE owner = {frappe.db.escape(user)}"
            f") AND `tab{MSRP_DT}`.workflow_state != 'Draft'"
        )

    return "1=0"


def msrp_has_permission(doc, ptype=None, user=None):
    if not user:
        user = frappe.session.user
    if user == "Administrator":
        return True

    roles = set(frappe.get_roles(user))
    if "System Manager" in roles or (roles & COMPLETION_ROLES):
        return True

    if roles & REQUESTOR_ROLES:
        if user != _get_msjr_owner(doc.msjr_no):
            return False
        if ptype in READ_LIKE_PTYPES:
            return doc.workflow_state != "Draft"
        if ptype in WRITE_LIKE_PTYPES:
            # The workflow engine sets doc.workflow_state to the *target* state
            # before calling doc.save(), so by the time this runs during a
            # Confirm Completion / File Back Job transition, doc.workflow_state
            # is already "Completed"/"Approved" rather than the state the user
            # acted from. Check the committed DB state instead.
            state = (
                doc.workflow_state if doc.is_new()
                else frappe.db.get_value(MSRP_DT, doc.name, "workflow_state")
            )
            return state == "Awaiting Requestor Confirmation"
        return False  # create / delete / cancel / amend

    return False


# ---------------------------------------------------------------------------
# One-time / idempotent setup (run once, then kept in sync via ensure_msrp_permissions)
# ---------------------------------------------------------------------------

def _add_company_setting_field():
    name = "Company-back_job_acceptance_period_days"
    if frappe.db.exists("Custom Field", name):
        return
    frappe.get_doc({
        "doctype": "Custom Field",
        "dt": "Company",
        "fieldname": "back_job_acceptance_period_days",
        "label": "Back Job Acceptance Period (Days)",
        "fieldtype": "Int",
        "default": str(DEFAULT_ACCEPTANCE_PERIOD_DAYS),
        "non_negative": 1,
        "insert_after": "country",
        "description": (
            "Working days the MSJR requestor has to Confirm Completion or File Back Job on a "
            "Machine Shop Repairs and Project, counted from Served Date against this Company's "
            f"Holiday List. Falls back to {DEFAULT_ACCEPTANCE_PERIOD_DAYS} if left blank."
        ),
    }).insert(ignore_permissions=True)


def _add_msrp_rework_log_doctype():
    if frappe.db.exists("DocType", REWORK_LOG_DT):
        return
    frappe.get_doc({
        "doctype": "DocType",
        "name": REWORK_LOG_DT,
        "module": "Assets",
        "custom": 1,
        "istable": 1,
        "editable_grid": 1,
        "fields": [
            {"fieldname": "cycle_no", "label": "Cycle", "fieldtype": "Int",
             "read_only": 1, "in_list_view": 1, "columns": 1},
            {"fieldname": "served_date", "label": "Served Date", "fieldtype": "Date",
             "read_only": 1, "in_list_view": 1, "columns": 2},
            {"fieldname": "back_job_reason", "label": "Reason", "fieldtype": "Select",
             "options": BACK_JOB_REASON_OPTIONS, "read_only": 1, "in_list_view": 1, "columns": 2},
            {"fieldname": "back_job_remarks", "label": "Remarks", "fieldtype": "Small Text",
             "read_only": 1, "in_list_view": 1, "columns": 3},
            {"fieldname": "filed_by", "label": "Filed By", "fieldtype": "Link", "options": "User",
             "read_only": 1, "in_list_view": 1, "columns": 2},
            {"fieldname": "filed_on", "label": "Filed On", "fieldtype": "Datetime",
             "read_only": 1, "in_list_view": 1, "columns": 2},
            {"fieldname": "acknowledged_by", "label": "Acknowledged By", "fieldtype": "Link",
             "options": "User", "read_only": 1, "in_list_view": 1, "columns": 2},
            {"fieldname": "acknowledged_on", "label": "Acknowledged On", "fieldtype": "Datetime",
             "read_only": 1, "in_list_view": 1, "columns": 2},
        ],
        "permissions": [
            {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
        ],
    }).insert(ignore_permissions=True)


def _add_msrp_custom_fields():
    fields = [
        {"fieldname": "section_break_confirmation", "label": "Completion Confirmation",
         "fieldtype": "Section Break", "insert_after": "process"},
        {"fieldname": "served_date", "label": "Served Date", "fieldtype": "Date",
         "insert_after": "section_break_confirmation", "permlevel": 1,
         "description": "Set by Machine Shop Foreman or Machine Shop Supervisor when marking the job completed."},
        {"fieldname": "acceptance_due_date", "label": "Acceptance Due Date", "fieldtype": "Date",
         "read_only": 1, "insert_after": "served_date",
         "description": "Served Date + the Company's Back Job Acceptance Period (Days)."},
        {"fieldname": "column_break_confirmation", "fieldtype": "Column Break",
         "insert_after": "acceptance_due_date"},
        {"fieldname": "back_job_reason", "label": "Back Job Reason", "fieldtype": "Select",
         "options": BACK_JOB_REASON_OPTIONS, "insert_after": "column_break_confirmation"},
        {"fieldname": "back_job_remarks", "label": "Back Job Remarks", "fieldtype": "Small Text",
         "insert_after": "back_job_reason",
         "mandatory_depends_on": 'eval:doc.back_job_reason=="Other"'},
        {"fieldname": "section_break_rework", "label": "Rework History", "fieldtype": "Section Break",
         "insert_after": "back_job_remarks", "collapsible": 1},
        {"fieldname": "rework_history", "fieldtype": "Table", "options": REWORK_LOG_DT,
         "read_only": 1, "insert_after": "section_break_rework"},
    ]
    for f in fields:
        name = f"{MSRP_DT}-{f['fieldname']}"
        if frappe.db.exists("Custom Field", name):
            continue
        f = dict(f, doctype="Custom Field", dt=MSRP_DT)
        frappe.get_doc(f).insert(ignore_permissions=True)


MSRP_PERMISSIONS = [
    # (role, create, write, submit)
    ("Machine Shop Foreman", 1, 1, 0),
    ("Machine Shop Supervisor", 1, 1, 0),
    ("Machine Shop User", 0, 1, 1),
    ("Maintenance - MC", 0, 1, 1),
    ("Maintenance - SMB", 0, 1, 1),
    ("Fleet Manager", 0, 1, 1),
    ("Asset Maintenance User", 0, 1, 1),
]


def _add_msrp_docperm():
    """Machine Shop Repairs and Project already has 'Custom DocPerm' rows from earlier
    Role Permission Manager customization. Frappe's get_valid_perms() ignores a
    doctype's own embedded DocPerm entirely once ANY Custom DocPerm row exists for it
    (see frappe.permissions.get_valid_perms), so permissions here must be managed as
    Custom DocPerm, not plain DocPerm."""
    existing = {
        r.role: r.name
        for r in frappe.get_all("Custom DocPerm", filters={"parent": MSRP_DT}, fields=["name", "role"])
    }
    for role, can_create, can_write, can_submit in MSRP_PERMISSIONS:
        values = {
            "read": 1,
            "write": can_write,
            "create": can_create,
            "delete": 0,
            "submit": can_submit,
            "cancel": 0,
            "print": 1,
            "email": 1,
            "report": 1,
            "export": 1,
            "share": 1,
        }
        if role in existing:
            frappe.db.set_value("Custom DocPerm", existing[role], values)
        else:
            frappe.get_doc({
                "doctype": "Custom DocPerm",
                "parent": MSRP_DT,
                "parenttype": "DocType",
                "parentfield": "permissions",
                "role": role,
                "permlevel": 0,
                **values,
            }).insert(ignore_permissions=True)

    _add_msrp_permlevel1_docperm()


# Fields the Foreman/Supervisor own — never editable by the requestor, even though
# the requestor gets real document-level write access during Awaiting Requestor
# Confirmation (needed for the workflow engine to save Confirm Completion / File
# Back Job). permlevel is what actually locks these out; write=1 at permlevel 0
# alone would let a requestor edit any field.
MSRP_FOREMAN_OWNED_FIELDS = [
    "served_date", "start_date", "commitment_date", "priority_level",
    "percentage_completed", "status", "miss_reason", "process",
]

# (role, read, write) at permlevel 1
MSRP_PERMLEVEL1_PERMISSIONS = [
    ("Machine Shop Foreman", 1, 1),
    ("Machine Shop Supervisor", 1, 1),
    ("System Manager", 1, 1),
    ("Machine Shop User", 1, 0),
    ("Maintenance - MC", 1, 0),
    ("Maintenance - SMB", 1, 0),
    ("Fleet Manager", 1, 0),
    ("Asset Maintenance User", 1, 0),
]


def _add_msrp_permlevel1_docperm():
    existing = {
        r.role: r.name
        for r in frappe.get_all(
            "Custom DocPerm", filters={"parent": MSRP_DT, "permlevel": 1}, fields=["name", "role"]
        )
    }
    for role, can_read, can_write in MSRP_PERMLEVEL1_PERMISSIONS:
        values = {"read": can_read, "write": can_write}
        if role in existing:
            frappe.db.set_value("Custom DocPerm", existing[role], values)
        else:
            frappe.get_doc({
                "doctype": "Custom DocPerm",
                "parent": MSRP_DT,
                "parenttype": "DocType",
                "parentfield": "permissions",
                "role": role,
                "permlevel": 1,
                "create": 0, "delete": 0, "submit": 0, "cancel": 0,
                "print": 1, "email": 1, "report": 1, "export": 1, "share": 1,
                **values,
            }).insert(ignore_permissions=True)


def _add_msrp_field_permlevels():
    """Custom Field: served_date."""
    frappe.db.set_value("Custom Field", f"{MSRP_DT}-served_date", "permlevel", 1)

    """Native DocType fields: everything else the Foreman/Supervisor own."""
    dt_doc = frappe.get_doc("DocType", MSRP_DT)
    changed = False
    lock_fieldnames = set(MSRP_FOREMAN_OWNED_FIELDS) - {"served_date"}
    for field in dt_doc.fields:
        if field.fieldname in lock_fieldnames and field.permlevel != 1:
            field.permlevel = 1
            changed = True
    if changed:
        dt_doc.flags.ignore_permissions = True
        dt_doc.save()


def _ensure_workflow_state(name):
    if not frappe.db.exists("Workflow State", name):
        frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": name}).insert(ignore_permissions=True)


def _ensure_workflow_action(name):
    if not frappe.db.exists("Workflow Action Master", name):
        frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": name}).insert(ignore_permissions=True)


def _update_msrp_workflow():
    _ensure_workflow_state("Awaiting Requestor Confirmation")
    for action in (
        "Tag To Active", "Mark as Completed", "Cancel", "Revert to Draft",
        "Confirm Completion", "File Back Job", "Acknowledge Again",
    ):
        _ensure_workflow_action(action)

    wf = frappe.get_doc("Workflow", WORKFLOW_NAME)

    existing_states = {s.state for s in wf.states}
    for s in (
        {"state": "Awaiting Requestor Confirmation", "doc_status": "0", "allow_edit": "All",
         "update_field": "workflow_state", "update_value": "Awaiting Requestor Confirmation"},
        {"state": "Approved", "doc_status": "0", "allow_edit": "All",
         "update_field": "workflow_state", "update_value": "Approved"},
    ):
        if s["state"] not in existing_states:
            wf.append("states", s)

    # the old direct Active -> Completed transition is replaced by the confirmation loop
    wf.transitions = [
        t for t in wf.transitions
        if not (t.state == "Active" and t.next_state == "Completed" and t.action == "Mark as Completed")
    ]

    new_transitions = [
        {"state": "Active", "action": "Mark as Completed", "next_state": "Awaiting Requestor Confirmation",
         "allowed": "Machine Shop Foreman", "allow_self_approval": 1},
        {"state": "Active", "action": "Mark as Completed", "next_state": "Awaiting Requestor Confirmation",
         "allowed": "Machine Shop Supervisor", "allow_self_approval": 1},
        {"state": "Approved", "action": "Acknowledge Again", "next_state": "Active",
         "allowed": "Machine Shop Foreman", "allow_self_approval": 1},
        {"state": "Approved", "action": "Acknowledge Again", "next_state": "Active",
         "allowed": "Machine Shop Supervisor", "allow_self_approval": 1},
    ]
    for role in REQUESTOR_ROLES:
        new_transitions.append({
            "state": "Awaiting Requestor Confirmation", "action": "Confirm Completion",
            "next_state": "Completed", "allowed": role, "allow_self_approval": 1,
            "condition": OWNER_MATCH_CONDITION,
        })
        new_transitions.append({
            "state": "Awaiting Requestor Confirmation", "action": "File Back Job",
            "next_state": "Approved", "allowed": role, "allow_self_approval": 1,
            "condition": OWNER_MATCH_CONDITION,
        })

    existing_keys = {(t.state, t.action, t.next_state, t.allowed) for t in wf.transitions}
    for t in new_transitions:
        key = (t["state"], t["action"], t["next_state"], t["allowed"])
        if key not in existing_keys:
            wf.append("transitions", t)

    wf.flags.ignore_permissions = True
    wf.save()


def setup():
    """One-time setup for the MSRP completion-confirmation workflow. Idempotent."""
    _add_company_setting_field()
    _add_msrp_rework_log_doctype()
    _add_msrp_custom_fields()
    _add_msrp_docperm()
    _add_msrp_field_permlevels()
    _update_msrp_workflow()
    frappe.clear_cache(doctype=MSRP_DT)


def ensure_msrp_permissions():
    """Re-apply MSRP field layout, workflow and DocPerm after every migrate."""
    import json as _json
    import os

    app_path = frappe.get_app_path("qcmc_logic")

    doctype_fixture = os.path.join(app_path, "fixtures", "doctype.json")
    with open(doctype_fixture) as f:
        fixture_data = _json.load(f)
    fixture_msrp = next((d for d in fixture_data if d.get("name") == MSRP_DT), None)
    if fixture_msrp:
        dt_doc = frappe.get_doc("DocType", MSRP_DT)
        dt_doc.set("fields", fixture_msrp["fields"])
        dt_doc.flags.ignore_permissions = True
        dt_doc.save()

    workflow_fixture = os.path.join(app_path, "fixtures", "workflow.json")
    with open(workflow_fixture) as f:
        wf_fixture_data = _json.load(f)
    fixture_wf = next((d for d in wf_fixture_data if d.get("name") == WORKFLOW_NAME), None)
    if fixture_wf and frappe.db.exists("Workflow", WORKFLOW_NAME):
        wf_doc = frappe.get_doc("Workflow", WORKFLOW_NAME)
        wf_doc.set("states", fixture_wf["states"])
        wf_doc.set("transitions", fixture_wf["transitions"])
        wf_doc.flags.ignore_permissions = True
        wf_doc.flags.ignore_links = True
        wf_doc.flags.ignore_validate = True
        wf_doc.save()

    _add_msrp_docperm()
    _add_msrp_field_permlevels()
    frappe.clear_cache(doctype=MSRP_DT)
