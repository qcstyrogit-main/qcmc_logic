import frappe
from frappe.model.naming import make_autoname


DOCTYPE = "Maintenance Job Order"
BREAKDOWN_LIST_DOCTYPE = "Breakdown List"
WORKFLOW_NAME = "Maintenance Job Order Approval"
MAINTENANCE_ROLES = {"SMB": "Maintenance - SMB", "STCLA": "Maintenance - STCLA", "MC": "Maintenance - MC"}
SECTION_ROUTES = {
    "GUYONG - PRODUCTION": ("SMB", "Production Encoder - SMB", "Production Foreman - SMB"),
    "STA CLARA - PRODUCTION": ("STCLA", "Production Encoder - STCLA", "Production Foreman - STCLA"),
    "MC - PRODUCTION": ("MC", "Production Foreman - MC", "Production Foreman - MC"),
    "MC - RM": ("MC", "RM - MC", "RM - MC"),
    "GUYONG - RM": ("SMB", "RM - SMB", "RM - SMB"),
    "STA CLARA - RM": ("STCLA", "RM - STCLA", "RM - STCLA"),
}
STATES = ("Draft", "Submitted", "Approved", "Active")
ACTIONS = ("Submit", "Approve", "Activate")
APPROVED_FIELDS = {"work_instruction", "breakdown_code"}


def state_roles(section):
    route = SECTION_ROUTES.get((section or "").strip().upper())
    if not route:
        frappe.throw("Select a supported Maintenance Job Order section.", frappe.PermissionError)
    location, draft, submitted = route
    return (draft, submitted, MAINTENANCE_ROLES[location], MAINTENANCE_ROLES[location])


def autoname(doc, method=None):
    doc.name = make_autoname("MJO-.YY.-.####", doc=doc)


def validate(doc, method=None):
    old = doc.get_doc_before_save()
    current = (old.get("workflow_state") if old else None) or "Draft"
    target = doc.get("workflow_state") or "Draft"
    roles = state_roles(old.section if old else doc.section)
    if current not in STATES or target not in STATES:
        frappe.throw("Invalid workflow state.", frappe.PermissionError)
    if roles[STATES.index(current)] not in frappe.get_roles():
        frappe.throw("Only {0} may edit or advance this state.".format(roles[STATES.index(current)]), frappe.PermissionError)
    if not old and (target != "Draft" or doc.docstatus != 0):
        frappe.throw("New jobs must start in Draft.", frappe.PermissionError)
    if old and (old.section != doc.section or old.docstatus != doc.docstatus):
        frappe.throw("Section and document status cannot be changed. Use workflow actions.", frappe.PermissionError)
    if current != target and STATES.index(target) != STATES.index(current) + 1:
        frappe.throw("Only the next forward transition is allowed.", frappe.PermissionError)
    if old and (current == "Approved" or target == "Approved"):
        allowed = APPROVED_FIELDS if current == target == "Approved" else set()
        changed = []
        for field in doc.meta.fields:
            name = field.fieldname
            if field.fieldtype in ("Section Break", "Column Break", "Tab Break", "HTML", "Button"):
                continue
            if name == "workflow_state" and current != target:
                continue
            before, after = old.get(name), doc.get(name)
            if field.fieldtype in ("Table", "Table MultiSelect"):
                def values(rows):
                    return [{key: value for key, value in row.as_dict().items()
                             if key not in {"modified", "modified_by"}} for row in (rows or [])]
                before, after = values(before), values(after)
            if name not in allowed and before != after:
                changed.append(name)
        for name in ("name", "owner", "creation", "idx"):
            if old.get(name) != doc.get(name):
                changed.append(name)
        if changed:
            frappe.throw("Approved jobs allow only Work Instruction (work done) and Breakdown Code edits. Blocked: "
                         + ", ".join(changed), frappe.PermissionError)
    if not old and not doc.document_date:
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
        _field("section", "Section", "Select", options="\n".join(SECTION_ROUTES), reqd=1, in_list_view=1),
        _field("document_date", "Document Date", "Date", read_only=1),
        _field("company", "Company", "Link", options="Company"),
        _field("item", "Item", "Link", options="Item"),
        _field("item_name", "Item Name", "Read Only", fetch_from="item.item_name"),
        _field("requested_by", "Requested By", "Data", reqd=1),
        _field("workflow_state", "Workflow State", "Data", hidden=1, allow_on_submit=1),
        _field("details_column", None, "Column Break"),
        _field("failure_date", "Failure Date", "Datetime", reqd=1),
        _field("date_needed", "Date Needed", "Datetime", reqd=1),
        _field("breakdown_code", "Breakdown Code", "Link", options=BREAKDOWN_LIST_DOCTYPE, reqd=1, allow_on_submit=1),
        _field("work_instruction", "Work Instruction", "Text", allow_on_submit=1),
        _field("amended_from", "Amended From", "Link", options=DOCTYPE, read_only=1, no_copy=1),
    ]
    roles = sorted({role for section in SECTION_ROUTES for role in state_roles(section)})
    creators = {route[1] for route in SECTION_ROUTES.values()}
    for role in roles:
        if not frappe.db.exists("Role", role):
            frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1, "is_custom": 1}).insert(ignore_permissions=True)
    permissions = [_permission(role, create=int(role in creators)) for role in roles]
    breakdown = frappe.get_doc("DocType", BREAKDOWN_LIST_DOCTYPE)
    for role in roles:
        if not any(row.role == role for row in breakdown.permissions):
            breakdown.append("permissions", {"role": role, "read": 1, "select": 1})
    breakdown.save(ignore_permissions=True)
    frappe.clear_cache(doctype=BREAKDOWN_LIST_DOCTYPE)

    if frappe.db.exists("DocType", DOCTYPE):
        doctype = frappe.get_doc("DocType", DOCTYPE)
        for field in fields:
            existing = next((row for row in doctype.fields if row.fieldname == field["fieldname"]), None)
            if existing:
                if field["fieldname"] == "section":
                    historical = frappe.get_all(DOCTYPE, pluck="section", distinct=True)
                    existing.fieldtype = "Select"
                    existing.options = "\n".join(dict.fromkeys([*SECTION_ROUTES, *[value for value in historical if value]]))
                if field["fieldname"] in APPROVED_FIELDS | {"workflow_state"}:
                    existing.allow_on_submit = 1
            else:
                doctype.append("fields", field)
        for permission in permissions:
            existing = next((row for row in doctype.permissions if row.role == permission["role"] and not row.permlevel), None)
            if existing:
                existing.update(permission)
            else:
                doctype.append("permissions", permission)
        for permission in doctype.permissions:
            permission.delete = 0
            permission.cancel = 0
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
        _field("category", "Category", "Link", options="Breakdown Class"),
        _field("measure", "Measure", "Select", options="Day\nHour"),
        _field("duration", "Duration", "Int"),
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
        "title_field": "description",
        "show_title_field_in_link": 1,
    })
    doctype.set("fields", fields)
    doctype.set("permissions", permissions)
    doctype.save(ignore_permissions=True)
    frappe.clear_cache(doctype=BREAKDOWN_LIST_DOCTYPE)


def _ensure_workflow():
    # Reuse the existing workflow; Frappe supports one active workflow per DocType.
    for doctype, fieldname, names in (
        ("Workflow State", "workflow_state_name", STATES),
        ("Workflow Action Master", "workflow_action_name", ACTIONS),
    ):
        for name in names:
            if not frappe.db.exists(doctype, name):
                frappe.get_doc({"doctype": doctype, fieldname: name}).insert(ignore_permissions=True)
    workflow = (frappe.get_doc("Workflow", WORKFLOW_NAME) if frappe.db.exists("Workflow", WORKFLOW_NAME)
                else frappe.new_doc("Workflow"))
    workflow.update({"workflow_name": WORKFLOW_NAME, "document_type": DOCTYPE,
                     "workflow_state_field": "workflow_state", "is_active": 1,
                     "override_status": 0, "send_email_alert": 0, "workflow_data": None})
    workflow.set("states", [])
    workflow.set("transitions", [])
    for section in SECTION_ROUTES:
        roles = state_roles(section)
        for state, role in zip(STATES, roles):
            if not any(row.state == state and row.allow_edit == role for row in workflow.states):
                workflow.append("states", {"state": state, "doc_status": "0", "allow_edit": role})
        for index, action in enumerate(ACTIONS):
            workflow.append("transitions", {"state": STATES[index], "action": action,
                "next_state": STATES[index + 1], "allowed": roles[index], "allow_self_approval": 1,
                "condition": "doc.section.strip().upper() == " + repr(section)})
    workflow.save(ignore_permissions=True)


def apply_workflow(doc, action):
    """Preserve legacy submitted docstatus while applying the section's action."""
    data = frappe.parse_json(doc) if isinstance(doc, str) else doc
    current = frappe.get_doc(DOCTYPE, data.get("name"))
    current.check_permission("write")
    state = current.get("workflow_state") or "Draft"
    index = STATES.index(state) if state in STATES else -1
    if index < 0 or index >= len(ACTIONS) or action != ACTIONS[index]:
        frappe.throw("Only the next forward workflow action is allowed.", frappe.PermissionError)
    if state_roles(current.section)[index] not in frappe.get_roles():
        frappe.throw("You do not own this workflow state.", frappe.PermissionError)
    current.workflow_state = STATES[index + 1]
    current.save()
    current.add_comment("Workflow", current.workflow_state)
    return current
