import frappe
from frappe.model.naming import make_autoname


DOCTYPE = "Maintenance Job Order"
BREAKDOWN_LIST_DOCTYPE = "Breakdown List"
REQUESTOR_ROLES = (
    "Machine Shop User",
    "Maintenance - MC",
    "Maintenance - SMB",
    "Fleet Manager",
    "Asset Maintenance User",
)
PLANT_MANAGER_ROLES = (
    "Plant Manager",
    "Plant Manager MC",
    "Plant Manager QC",
)
def autoname(doc, method=None):
    doc.name = make_autoname("MJO-.YY.-.####", doc=doc)


def validate(doc, method=None):
    if not doc.document_date:
        doc.document_date = frappe.utils.today()


def _field(fieldname, label, fieldtype, **kwargs):
    return {"fieldname": fieldname, "label": label, "fieldtype": fieldtype, **kwargs}


def _permission(role, *, create=0, delete=0, submit=0, cancel=0, amend=0):
    """Return a complete permission row so reused DocPerm rows retain no stale flags."""
    return {
        "role": role,
        "read": 1,
        "write": 1,
        "create": create,
        "delete": delete,
        "submit": submit,
        "cancel": cancel,
        "amend": amend,
        "select": 0,
        "import": 0,
        "print": 1,
        "email": 1,
        "report": 1,
        "export": 1,
        "share": 1,
    }


def ensure_maintenance_job_order():
    """Create/update the non-fabrication maintenance request form and workflow."""
    _ensure_breakdown_list()

    fields = [
        _field("naming_series", "Series", "Select", options="MJO-.YY.-.####", hidden=1),
        _field("section", "Section", "Link", options="Job Request Section", reqd=1, in_list_view=1),
        _field("document_date", "Document Date", "Date", read_only=1),
        _field("company", "Company", "Link", options="Company"),
        _field("item", "Item", "Link", options="Item"),
        _field("item_name", "Item Name", "Read Only", fetch_from="item.item_name"),
        _field("requested_by", "Requested By", "Data", reqd=1),
        _field("workflow_state", "Workflow State", "Data", hidden=1),
        _field("details_column", None, "Column Break"),
        _field("failure_date", "Failure Date", "Datetime", reqd=1),
        _field("date_needed", "Date Needed", "Datetime", reqd=1),
        _field("breakdown_code", "Breakdown Code", "Link", options=BREAKDOWN_LIST_DOCTYPE, reqd=1),
        _field("work_instruction", "Work Instruction", "Text"),
        _field("amended_from", "Amended From", "Link", options=DOCTYPE, read_only=1, no_copy=1),
    ]
    permissions = [
        _permission(
            "System Manager", create=1, delete=1, submit=1, cancel=1, amend=1
        ),
        *[_permission(role, create=1) for role in REQUESTOR_ROLES],
        *[_permission(role) for role in PLANT_MANAGER_ROLES],
    ]

    if frappe.db.exists("DocType", DOCTYPE):
        doctype = frappe.get_doc("DocType", DOCTYPE)
        doctype.set("fields", fields)
        doctype.set("permissions", permissions)
    else:
        doctype = frappe.new_doc("DocType")
        doctype.update({
            "name": DOCTYPE, "module": "Assets", "custom": 1,
            "autoname": "naming_series:", "naming_rule": 'By "Naming Series" field',
            "is_submittable": 1, "track_changes": 1,
        })
        doctype.set("fields", fields)
        doctype.set("permissions", permissions)
    doctype.save(ignore_permissions=True)

    _ensure_workflow()
    frappe.clear_cache(doctype=DOCTYPE)


def _ensure_breakdown_list():
    fields = [
        _field("breakdown_code", "Breakdown Code", "Data", reqd=1, unique=1,
               in_list_view=1),
        _field("description", "Description", "Data", in_list_view=1),
        _field("measure", "Measure", "Int"),
        _field("duration", "Duration", "Select", options="Day\nHour"),
        _field("status", "Status", "Select", options="Active\nInactive"),
    ]
    permissions = [
        _permission(
            "System Manager", create=1, delete=1, submit=0, cancel=0, amend=0
        )
    ]

    if frappe.db.exists("DocType", BREAKDOWN_LIST_DOCTYPE):
        doctype = frappe.get_doc("DocType", BREAKDOWN_LIST_DOCTYPE)
    else:
        doctype = frappe.new_doc("DocType")
        doctype.name = BREAKDOWN_LIST_DOCTYPE
    doctype.update({
        "module": "Assets",
        "custom": 1,
        "autoname": "field:breakdown_code",
        "naming_rule": "By fieldname",
        "title_field": "breakdown_code",
        "show_title_field_in_link": 1,
    })
    doctype.set("fields", fields)
    doctype.set("permissions", permissions)
    doctype.save(ignore_permissions=True)
    frappe.clear_cache(doctype=BREAKDOWN_LIST_DOCTYPE)


def _ensure_workflow():
    workflow_name = "Maintenance Job Order Approval"
    if frappe.db.exists("Workflow", workflow_name):
        workflow = frappe.get_doc("Workflow", workflow_name)
    else:
        workflow = frappe.new_doc("Workflow")
        workflow.workflow_name = workflow_name

    workflow.document_type = DOCTYPE
    workflow.workflow_state_field = "workflow_state"
    workflow.is_active = 1
    workflow.override_status = 0
    workflow.send_email_alert = 0
    workflow.set("states", [])
    for role in REQUESTOR_ROLES:
        workflow.append("states", {"state": "Draft", "doc_status": "0", "allow_edit": role})
        workflow.append("states", {"state": "Submitted", "doc_status": "0", "allow_edit": role})
    for role in PLANT_MANAGER_ROLES:
        workflow.append("states", {"state": "Submitted", "doc_status": "0", "allow_edit": role})
        workflow.append("states", {"state": "Approved", "doc_status": "1", "allow_edit": role})

    workflow.set("transitions", [])
    for role in REQUESTOR_ROLES:
        workflow.append("transitions", {
            "state": "Draft", "action": "Submit", "next_state": "Submitted",
            "allowed": role, "allow_self_approval": 1,
        })
    for role in PLANT_MANAGER_ROLES:
        workflow.append("transitions", {
            "state": "Submitted", "action": "Approve", "next_state": "Approved",
            "allowed": role, "allow_self_approval": 1,
        })
    workflow.save(ignore_permissions=True)
