import frappe
from frappe.model.naming import make_autoname


DOCTYPE = "Maintenance Job Order"
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
FABRICATION_REQUEST_TYPES = {
    "PARTS FABRICATION",
    "FABRICATION - ITEM",
    "FABRICATION - MACHINE PART",
    "FABRICATION - MOULD",
}


def autoname(doc, method=None):
    doc.name = make_autoname("MJO-.YY.-.####", doc=doc)


def validate(doc, method=None):
    if not doc.document_date:
        doc.document_date = frappe.utils.today()

    request_type = (
        frappe.db.get_value("Machine Shop Request Code", doc.request, "description")
        if doc.request
        else None
    )
    if (request_type or doc.request or "").strip().upper() in FABRICATION_REQUEST_TYPES:
        frappe.throw(
            "Fabrication request types are not allowed in a Maintenance Job Order.",
            title="Fabrication Not Allowed",
        )


@frappe.whitelist()
def get_non_fabrication_requests(doctype, txt, searchfield, start, page_len, filters):
    """Link-field query that omits every fabrication request code."""
    title_field = "description"
    table = "`tabMachine Shop Request Code`"
    like = f"%{txt}%"
    excluded = tuple(sorted(FABRICATION_REQUEST_TYPES))
    return frappe.db.sql(
        f"""SELECT name, `{title_field}`
            FROM {table}
            WHERE (name LIKE %(like)s OR `{title_field}` LIKE %(like)s)
              AND UPPER(COALESCE(`{title_field}`, name)) NOT IN %(excluded)s
            ORDER BY `{title_field}`
            LIMIT %(start)s, %(page_len)s""",
        {"like": like, "excluded": excluded, "start": start, "page_len": page_len},
    )


def _field(fieldname, label, fieldtype, **kwargs):
    return {"fieldname": fieldname, "label": label, "fieldtype": fieldtype, **kwargs}


def ensure_maintenance_job_order():
    """Create/update the non-fabrication maintenance request form and workflow."""
    fields = [
        _field("naming_series", "Series", "Select", options="MJO-.YY.-.####", hidden=1),
        _field("section", "Section", "Link", options="Job Request Section", reqd=1, in_list_view=1),
        _field("document_date", "Document Date", "Date", read_only=1),
        _field("company", "Company", "Link", options="Company"),
        _field("asset", "Asset", "Link", options="Asset"),
        _field("asset_name", "Asset Name", "Read Only", fetch_from="asset.asset_name"),
        _field("requested_by", "Requested By", "Data", reqd=1),
        _field("workflow_state", "Workflow State", "Data", hidden=1),
        _field("details_column", None, "Column Break"),
        _field("failure_date", "Failure Date", "Datetime", reqd=1),
        _field("date_needed", "Date Needed", "Datetime", reqd=1),
        _field("request", "Request", "Link", options="Machine Shop Request Code", reqd=1),
        _field("work_instruction", "Work Instruction", "Text"),
        _field("amended_from", "Amended From", "Link", options=DOCTYPE, read_only=1, no_copy=1),
    ]
    permissions = [
        {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1,
         "submit": 1, "cancel": 1, "amend": 1, "print": 1, "email": 1, "report": 1,
         "export": 1, "share": 1},
        *[
            {"role": role, "read": 1, "write": 1, "create": 1, "print": 1,
             "email": 1, "report": 1, "export": 1, "share": 1}
            for role in REQUESTOR_ROLES
        ],
        *[
            {"role": role, "read": 1, "write": 1, "print": 1, "email": 1,
             "report": 1, "export": 1, "share": 1}
            for role in PLANT_MANAGER_ROLES
        ],
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
