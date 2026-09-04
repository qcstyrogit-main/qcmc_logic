import frappe
from frappe.model.naming import make_autoname
from frappe.utils import flt


PARTS_FABRICATION = "PARTS FABRICATION"  # legacy request type
ITEM_FABRICATION_TYPES = frozenset({
    "FABRICATION - ITEM",
    "FABRICATION - MACHINE PART",
})
ASSET_FABRICATION_TYPES = frozenset({
    "FABRICATION - MOULD",
})
FABRICATION_REQUEST_TYPES = ITEM_FABRICATION_TYPES | ASSET_FABRICATION_TYPES
QUANTITY_PRODUCED_ROLES = frozenset({
    "Machine Shop User",
    "Machine Shop Foreman",
})
PARTS_INVENTORY_GROUP = "CMMS"

LOCATION_SERIES = {
    "Edsa - Motorpool":        "12MTP-.YY.-.####",
    "Edsa - Machine Shop":     "12JR-.YY.-.####",
    "MC - Motorpool":          "99MTP-.YY.-.####",
    "MC - Maintenance":        "99JR-.YY.-.####",
    "MC - Production":         "99MO-.YY.-.####",
    "Guyong - Production":     "35MO-.YY.-.####",
    "Guyong - Maintenance":    "35JR-.YY.-.####",
    "Guyong - Motorpool":      "35MTP-.YY.-.####",
    "Sta Clara - Production":  "33MO-.YY.-.####",
    "Sta Clara - Maintenance": "33JR-.YY.-.####",
    "Sta Clara - Motorpool":   "33MTP-.YY.-.####",
}

# Roles that can trigger workflow transitions on MSJR
REQUESTOR_ROLES = frozenset([
    "Machine Shop User",
    "Maintenance - MC",
    "Maintenance - SMB",
    "Fleet Manager",
    "Asset Maintenance User",
])

APPROVER_ROLES = frozenset([
    "Logistics Manager",
    "Plant Manager MC",
    "Plant Manager QC",
    "Machine Shop Supervisor",
])


# ---------------------------------------------------------------------------
# Job Request Section helpers
# ---------------------------------------------------------------------------

def _get_user_role_profiles(user):
    """Return the set of all Role Profile names assigned to *user*."""
    profiles = set()

    single = frappe.db.get_value("User", user, "role_profile_name") or ""
    if single:
        profiles.add(single)

    try:
        child_dt = frappe.get_meta("User").get_field("role_profiles").options
        if child_dt:
            for p in frappe.get_all(child_dt, filters={"parent": user}, pluck="role_profile"):
                if p:
                    profiles.add(p)
    except Exception:
        pass

    return profiles


def _get_user_locations(user=None):
    """Return sorted list of MSJR sections the user is authorised for via Job Request Section."""
    if not user:
        user = frappe.session.user

    if user == "Administrator":
        return sorted(LOCATION_SERIES.keys())

    profiles = _get_user_role_profiles(user)
    if not profiles:
        return []

    locations = set()
    for profile in profiles:
        jrs_name = frappe.db.get_value("Job Request Section", {"role_profile": profile}, "name")
        if not jrs_name:
            continue
        sections = frappe.get_all(
            "Job Request Section Detail",
            filters={"parent": jrs_name},
            pluck="section",
        )
        locations.update(s for s in sections if s)

    return sorted(locations)


@frappe.whitelist()
def get_user_locations():
    """Whitelist: returns authorised sections for the current user."""
    return _get_user_locations()


# ---------------------------------------------------------------------------
# Doctype hooks
# ---------------------------------------------------------------------------

def autoname(doc, method=None):
    if doc.job_type == "Preventive Maintenance":
        series = "PREVMA-.YY.-.####"
    else:
        series = LOCATION_SERIES.get(doc.section or "", "MSJR-.YY.-.####")

    doc.name = make_autoname(series, doc=doc)


def validate(doc, method=None):
    user = frappe.session.user

    # ── Section validation ────────────────────────────────────────────────
    if not doc.section:
        frappe.throw("Please select a Section before saving.", title="Section Required")

    if doc.section not in LOCATION_SERIES:
        frappe.throw(f"Invalid Section: '{doc.section}'.", title="Invalid Section")

    if doc.is_new() and user != "Administrator":
        authorized = set(_get_user_locations(user))
        if not authorized:
            frappe.throw(
                "Your Role Profile is not configured in Job Request Section. "
                "Please contact the system administrator.",
                title="Section Not Configured",
            )
        if doc.section not in authorized:
            frappe.throw(
                f"You are not authorised to create documents for section '{doc.section}'.",
                title="Unauthorised Section",
            )

    # ── Job Type validation ───────────────────────────────────────────────
    if doc.is_new() and not doc.job_type:
        doc.job_type = "Job Request"

    if doc.job_type == "Preventive Maintenance" and doc.section != "Edsa - Machine Shop":
        frappe.throw(
            "Preventive Maintenance is only available for the Edsa - Machine Shop section.",
            title="Invalid Job Type",
        )

    if not doc.is_new() and doc.job_type:
        old_job_type = frappe.db.get_value("Machine Shop Job Request", doc.name, "job_type")
        if old_job_type and old_job_type != doc.job_type:
            frappe.throw(
                "Job Type cannot be changed after the document has been created.",
                title="Job Type Locked",
            )

    request_type = _get_request_type(doc)
    _normalize_non_fabrication_quantity_produced(doc, request_type)
    _validate_quantity_produced_permission(doc, request_type)
    _validate_fabrication_request_quantities(doc, request_type)
    _validate_output_item(doc)

    # ── Workflow transition validation ────────────────────────────────────
    _validate_workflow_transition(doc)


def _get_request_type(doc):
    """Return the request master description used as the business request type."""
    if not doc.get("request"):
        return ""
    return (
        frappe.db.get_value("Machine Shop Request Code", doc.request, "description") or ""
    ).strip().upper()


def _is_parts_fabrication(doc):
    return _get_request_type(doc) in (ITEM_FABRICATION_TYPES | {PARTS_FABRICATION})


def _is_item_fabrication(doc):
    return _get_request_type(doc) in ITEM_FABRICATION_TYPES


def _is_asset_fabrication(doc):
    return _get_request_type(doc) in ASSET_FABRICATION_TYPES


def _validate_fabrication_request_quantities(doc, request_type=None):
    """Enforce the Item/Part request quantity without requiring a master record."""
    request_type = request_type or _get_request_type(doc)
    if request_type in ITEM_FABRICATION_TYPES and flt(doc.get("quantity_request")) <= 0:
        frappe.throw(
            "Quantity Request is required and must be greater than zero for Item/Part fabrication.",
            title="Quantity Request Required",
        )


def _normalize_non_fabrication_quantity_produced(doc, request_type=None):
    request_type = request_type or _get_request_type(doc)
    if request_type not in FABRICATION_REQUEST_TYPES and request_type != PARTS_FABRICATION:
        doc.quantity_produced = 0


def _validate_quantity_produced_permission(doc, request_type=None):
    request_type = request_type or _get_request_type(doc)
    if request_type not in FABRICATION_REQUEST_TYPES and request_type != PARTS_FABRICATION:
        return
    if frappe.session.user == "Administrator":
        return

    old_value = 0
    if not doc.is_new():
        old_value = flt(
            frappe.db.get_value("Machine Shop Job Request", doc.name, "quantity_produced")
        )
    if flt(doc.get("quantity_produced")) == old_value:
        return

    roles = set(frappe.get_roles(frappe.session.user))
    if not (roles & QUANTITY_PRODUCED_ROLES):
        frappe.throw(
            "Only Machine Shop User or Machine Shop Foreman can modify Quantity Produced.",
            title="Not Permitted",
        )


def _validate_output_item(doc):
    """Keep a selected parts-fabrication Item inside the CMMS inventory group."""
    item_code = doc.get("item_code")
    if not item_code:
        return

    if not _is_parts_fabrication(doc):
        return

    inventory_group = frappe.db.get_value("Item", item_code, "custom_inventory_group")
    if inventory_group != PARTS_INVENTORY_GROUP:
        frappe.throw(
            f"Item Code must belong to Inventory Group {PARTS_INVENTORY_GROUP}.",
            title="Invalid Inventory Group",
        )


def _validate_completion_output(doc):
    request_type = _get_request_type(doc)
    if (
        request_type in FABRICATION_REQUEST_TYPES or request_type == PARTS_FABRICATION
    ) and flt(doc.get("quantity_produced")) <= 0:
        frappe.throw(
            "Quantity Produced must be greater than zero before completing this fabrication request.",
            title="Quantity Produced Required",
        )

    if request_type in ITEM_FABRICATION_TYPES:
        if not doc.get("item_code"):
            frappe.throw(
                f"Item Code is required before completing {request_type}.",
                title="Item Code Required",
            )
        return

    if request_type in ASSET_FABRICATION_TYPES:
        if not doc.get("asset"):
            frappe.throw(
                f"Asset is required before completing {request_type}.",
                title="Asset Required",
            )
        return

    if doc.get("not_in_master_file"):
        if not (doc.get("proposed_output_code") or doc.get("output_description")):
            frappe.throw(
                "Enter a Proposed Output Code or Output Description for an output that is not yet in the master file.",
                title="Output Identification Required",
            )
        return

    if _is_parts_fabrication(doc):
        if not doc.get("item_code"):
            frappe.throw(
                "Item Code is required for PARTS FABRICATION before completing this request.",
                title="Item Code Required",
            )
    elif not doc.get("asset"):
        frappe.throw(
            "Asset is required before completing this request.",
            title="Asset Required",
        )


def _validate_linked_project_completed(doc):
    projects = frappe.get_all(
        "Machine Shop Repairs and Project",
        filters={"msjr_no": doc.name, "docstatus": ["!=", 2]},
        fields=["name", "workflow_state"],
    )
    if not projects:
        frappe.throw(
            "Generate and complete a Machine Shop Repairs and Project before completing this request.",
            title="Completed Project Required",
        )

    incomplete = [row.name for row in projects if row.workflow_state != "Completed"]
    if incomplete:
        frappe.throw(
            "Complete the linked Machine Shop Repairs and Project before completing this request: "
            + ", ".join(incomplete),
            title="Project Not Completed",
        )


def _validate_workflow_transition(doc):
    """Server-side enforcement of workflow transition rules beyond role checks."""
    if doc.is_new():
        return

    old_state = frappe.db.get_value("Machine Shop Job Request", doc.name, "workflow_state") or ""
    new_state = doc.workflow_state or ""

    if old_state == new_state:
        return

    if old_state == "Received" and new_state == "Completed":
        _validate_completion_output(doc)
        _validate_linked_project_completed(doc)

    if frappe.session.user == "Administrator":
        return

    roles = set(frappe.get_roles(frappe.session.user))
    section = doc.section or ""

    # Submitted → Approved:
    # Machine Shop Supervisor may only approve Edsa - Machine Shop documents.
    if old_state == "Submitted" and new_state == "Approved":
        if "Machine Shop Supervisor" in roles:
            broader_approver = roles & (APPROVER_ROLES - {"Machine Shop Supervisor"})
            if not broader_approver and section != "Edsa - Machine Shop":
                frappe.throw(
                    "Machine Shop Supervisor can only approve requests "
                    "from the 'Edsa - Machine Shop' section.",
                    title="Unauthorized Approval",
                )

    # Submitted → Cancelled:
    # User must belong to the same section as the document.
    if old_state == "Submitted" and new_state == "Cancelled":
        user_sections = set(_get_user_locations(frappe.session.user))
        if section not in user_sections:
            frappe.throw(
                "You can only cancel requests that belong to your assigned section.",
                title="Unauthorized Cancel",
            )


# ---------------------------------------------------------------------------
# Permission query conditions (list view)
# ---------------------------------------------------------------------------

SUPERVISOR_SECTION = "Edsa - Machine Shop"


def msjr_permission_query(user):
    """SQL WHERE clause controlling which MSJR documents appear in the list.

    Machine Shop Supervisor authority is hard-coded to SUPERVISOR_SECTION.
    When a user holds both a requestor role and Supervisor, Submitted+ docs from
    non-supervisor sections are hidden (those belong to each section's own approver).
    """
    if user == "Administrator":
        return ""

    roles = set(frappe.get_roles(user))
    if "System Manager" in roles:
        return ""

    t = "`tabMachine Shop Job Request`"
    escape = frappe.db.escape
    is_supervisor = "Machine Shop Supervisor" in roles
    user_sections = _get_user_locations(user)

    if not user_sections and not is_supervisor:
        return "1=0"

    conditions = []

    if user_sections:
        sec_in = ", ".join(escape(s) for s in user_sections)
        sec_filter = f"{t}.section IN ({sec_in})"

        if roles & REQUESTOR_ROLES:
            if is_supervisor:
                # Supervisor-requestors see ALL states for their supervisor section only;
                # for other JRS sections they only see Draft (own in-progress work).
                edsa = escape(SUPERVISOR_SECTION)
                conditions.append(f"{t}.section = {edsa}")
                other = [s for s in user_sections if s != SUPERVISOR_SECTION]
                if other:
                    other_in = ", ".join(escape(s) for s in other)
                    conditions.append(
                        f"({t}.section IN ({other_in}) AND {t}.workflow_state = 'Draft')"
                    )
            else:
                # Regular requestors: all states from all their sections
                conditions.append(sec_filter)

        # Plant Managers / Logistics Manager: Submitted only, restricted to their sections
        if roles & {"Logistics Manager", "Plant Manager MC", "Plant Manager QC"}:
            conditions.append(
                f"({sec_filter} AND {t}.workflow_state = 'Submitted')"
            )

        # Machine Shop Foreman: Approved/Acknowledge/Received in their sections
        if "Machine Shop Foreman" in roles:
            conditions.append(
                f"({sec_filter} AND {t}.workflow_state IN ('Approved', 'Acknowledge', 'Received'))"
            )

    # Machine Shop Supervisor:
    # - Submitted: ONLY Edsa - Machine Shop (can only approve their section)
    # - Approved / Acknowledge / Received: ALL sections
    if is_supervisor:
        edsa = escape(SUPERVISOR_SECTION)
        conditions.append(
            f"({t}.section = {edsa} AND {t}.workflow_state = 'Submitted')"
        )
        conditions.append(
            f"{t}.workflow_state IN ('Approved', 'Acknowledge', 'Received')"
        )

    if not conditions:
        return "1=0"

    return "(" + " OR ".join(conditions) + ")"


# ---------------------------------------------------------------------------
# Document-level permission check (form view / API)
# ---------------------------------------------------------------------------

def msjr_has_permission(doc, ptype=None, user=None):
    """Return True if *user* may access this specific document."""
    if not user:
        user = frappe.session.user
    if user == "Administrator":
        return True

    roles = set(frappe.get_roles(user))
    if "System Manager" in roles:
        return True

    if ptype == "create":
        return bool(_get_user_locations(user))

    is_supervisor = "Machine Shop Supervisor" in roles
    user_sections = set(_get_user_locations(user))
    section = doc.section or ""
    state = doc.workflow_state or ""

    if roles & REQUESTOR_ROLES and section in user_sections:
        if is_supervisor:
            # Supervisor-requestors: full access to their supervisor section;
            # Draft-only access to other JRS sections.
            if section == SUPERVISOR_SECTION or state == "Draft":
                return True
        else:
            return True

    # Plant Managers / Logistics Manager: Submitted docs in their sections only
    if roles & {"Logistics Manager", "Plant Manager MC", "Plant Manager QC"}:
        if section in user_sections and state == "Submitted":
            return True

    # Machine Shop Supervisor:
    # - Submitted: SUPERVISOR_SECTION only (can only approve their section)
    # - Approved / Acknowledge / Received: any section
    if is_supervisor:
        if section == SUPERVISOR_SECTION and state == "Submitted":
            return True
        if state in ("Approved", "Acknowledge", "Received"):
            return True

    # Machine Shop Foreman: Approved/Acknowledge/Received in their sections
    if "Machine Shop Foreman" in roles:
        if section in user_sections and state in ("Approved", "Acknowledge", "Received"):
            return True

    return False


# ---------------------------------------------------------------------------
# After-migrate hook — ensures DocPerm survives fixture re-imports
# ---------------------------------------------------------------------------

MSJR_PERMISSIONS = [
    # (role, create)
    ("Machine Shop User",       1),
    ("Maintenance - MC",        1),
    ("Maintenance - SMB",       1),
    ("Fleet Manager",           1),
    ("Asset Maintenance User",  1),
    ("Logistics Manager",       0),
    ("Plant Manager QC",        0),
    ("Plant Manager MC",        0),
    ("Machine Shop Supervisor", 0),
    ("Machine Shop Foreman",    0),
]


MSJR_OUTPUT_FIELDS = [
    {
        "fieldname": "output_details_section",
        "label": "Fabricated Output",
        "fieldtype": "Section Break",
        "insert_after": "work_instruction",
    },
    {
        "fieldname": "item_code",
        "label": "Item Code",
        "fieldtype": "Link",
        "options": "Item",
        "insert_after": "output_details_section",
        "description": "Item Master record for an Item/Part fabrication request.",
    },
    {
        "fieldname": "quantity_request",
        "label": "Quantity Request",
        "fieldtype": "Float",
        "non_negative": 1,
        "insert_after": "item_code",
    },
    {
        "fieldname": "quantity_produced",
        "label": "Quantity Produced",
        "fieldtype": "Float",
        "default": "0",
        "non_negative": 1,
        "insert_after": "item_code",
    },
    {
        "fieldname": "not_in_master_file",
        "label": "Not Yet in Master File",
        "fieldtype": "Check",
        "default": "0",
        "insert_after": "quantity_produced",
        "description": "Use when the fabricated output has no Item or Asset master record yet.",
    },
    {
        "fieldname": "proposed_output_code",
        "label": "Proposed Output Code",
        "fieldtype": "Data",
        "insert_after": "not_in_master_file",
        "depends_on": "eval:doc.not_in_master_file",
    },
    {
        "fieldname": "output_description",
        "label": "Output Description",
        "fieldtype": "Small Text",
        "insert_after": "proposed_output_code",
        "depends_on": "eval:doc.not_in_master_file",
    },
]


def _ensure_msjr_output_fields():
    obsolete_field = "Machine Shop Job Request-asset_quantity_request"
    if frappe.db.exists("Custom Field", obsolete_field):
        frappe.delete_doc("Custom Field", obsolete_field, ignore_permissions=True)

    for field in MSJR_OUTPUT_FIELDS:
        name = f"Machine Shop Job Request-{field['fieldname']}"
        if frappe.db.exists("Custom Field", name):
            updates = {
                key: field[key]
                for key in ("default", "non_negative", "reqd")
                if key in field
            }
            if updates:
                frappe.db.set_value("Custom Field", name, updates, update_modified=False)
            continue
        frappe.get_doc({
            "doctype": "Custom Field",
            "dt": "Machine Shop Job Request",
            **field,
        }).insert(ignore_permissions=True)


def _ensure_fabrication_request_codes():
    for description in sorted(FABRICATION_REQUEST_TYPES):
        if frappe.db.exists("Machine Shop Request Code", {"description": description}):
            continue
        frappe.get_doc({
            "doctype": "Machine Shop Request Code",
            "description": description,
            "measure": "DAY",
        }).insert(ignore_permissions=True)


def ensure_msjr_permissions():
    """Re-apply field layout, DocPerm, and JRS doctypes after every migrate."""
    import json, os

    # 1. Re-register Job Request Section doctypes
    for module, doctype in [
        ("QCMC Logics", "job_request_section_detail"),
        ("QCMC Logics", "job_request_section"),
    ]:
        frappe.reload_doc(module, "doctype", doctype, force=True)

    app_path = frappe.get_app_path("qcmc_logic")

    # 2. Sync MSJR field layout from fixture (migrate doesn't reliably apply it)
    doctype_fixture = os.path.join(app_path, "fixtures", "doctype.json")
    with open(doctype_fixture) as f:
        fixture_data = json.load(f)
    fixture_msjr = next(
        (d for d in fixture_data if d.get("name") == "Machine Shop Job Request"), None
    )
    if fixture_msjr:
        dt_doc = frappe.get_doc("DocType", "Machine Shop Job Request")
        dt_doc.set("fields", fixture_msjr["fields"])
        asset_field = next((f for f in dt_doc.fields if f.fieldname == "asset"), None)
        if asset_field:
            asset_field.reqd = 0
        dt_doc.flags.ignore_permissions = True
        dt_doc.save()

    _ensure_msjr_output_fields()
    _ensure_fabrication_request_codes()

    # 3. Sync MSJR workflow from fixture
    workflow_fixture = os.path.join(app_path, "fixtures", "workflow.json")
    with open(workflow_fixture) as f:
        wf_fixture_data = json.load(f)
    fixture_wf = next(
        (d for d in wf_fixture_data if d.get("name") == "MSJR"), None
    )
    if fixture_wf and frappe.db.exists("Workflow", "MSJR"):
        wf_doc = frappe.get_doc("Workflow", "MSJR")
        wf_doc.set("states", fixture_wf["states"])
        wf_doc.set("transitions", fixture_wf["transitions"])
        wf_doc.flags.ignore_permissions = True
        wf_doc.flags.ignore_links = True
        wf_doc.flags.ignore_validate = True
        wf_doc.save()

    dt = "Machine Shop Job Request"
    existing = {
        r.role
        for r in frappe.get_all("DocPerm", filters={"parent": dt}, fields=["role"])
    }

    for role, can_create in MSJR_PERMISSIONS:
        if role in existing:
            continue
        doc = frappe.get_doc({
            "doctype": "DocPerm",
            "parent": dt,
            "parenttype": "DocType",
            "parentfield": "permissions",
            "role": role,
            "permlevel": 0,
            "read": 1,
            "write": 1,
            "create": can_create,
            "delete": 0,
            "submit": 0,
            "cancel": 0,
            "print": 1,
            "email": 1,
            "report": 1,
            "export": 1,
            "share": 1,
        })
        doc.insert(ignore_permissions=True)

    frappe.clear_cache(doctype=dt)
