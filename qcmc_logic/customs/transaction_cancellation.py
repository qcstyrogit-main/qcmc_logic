"""Permission-checked draft cancellation using native Frappe discard.

The site setting enables automatic, permission-checked draft cancellation from
active workflow states. Submitted cancellation remains native.
"""
import frappe
from frappe import _
from frappe.utils import cint, escape_html
from frappe.model import workflow as wf

FIELD = "custom_allow_cancellation_before_submission"
FLAG = "qcmc_authorized_draft_discard"


def enabled():
    if not frappe.get_meta("System Settings").has_field(FIELD):
        return False
    return bool(cint(frappe.db.get_single_value("System Settings", FIELD, cache=False)))


def extend_bootinfo(bootinfo):
    bootinfo.qcmc_allow_cancellation_before_submission = enabled()


def _state(workflow, transition):
    rows = [row for row in workflow.states if row.state == transition.next_state]
    if not rows or len({str(row.doc_status) for row in rows}) != 1:
        frappe.throw(_("Invalid cancellation workflow target state."))
    return rows[0]


def _is_draft_cancel(doc, workflow, transition):
    return cint(doc.docstatus) == 0 and cint(_state(workflow, transition).doc_status) == 2


def _terminal_state(workflow):
    rows = [row for row in workflow.states if cint(row.doc_status) == 2]
    return next((row for row in rows if row.state == "Cancelled"), rows[0] if rows else None)


def _is_legacy_cancel(doc, workflow, transition):
    # Legacy business-state cancellation is promoted to native discard only
    # for an explicitly named cancellation action and destination.
    return (cint(doc.docstatus) == 0 and transition.action.casefold() == "cancel"
            and cint(_state(workflow, transition).doc_status) == 0
            and transition.next_state.casefold().startswith(("cancelled", "canceled")))


def _draft_routes(doc, workflow, allowed):
    """Return authorized cancellation actions without changing workflow transitions."""
    if not enabled() or cint(doc.docstatus) != 0 or not _has_permissions(doc):
        return []
    state = doc.get(workflow.workflow_state_field)
    if not state or state.casefold().startswith(("cancelled", "canceled", "rejected")):
        return []
    current_states = [row for row in workflow.states if row.state == state and cint(row.doc_status) == 0]
    if not current_states:
        return []
    # If administrators explicitly configured cancellation from this state,
    # preserve the configured role, condition and self-approval rules. Do not
    # provide a fallback that defeats a denied explicit route.
    configured = [t for t in workflow.transitions if t.state == state
                  and (_is_draft_cancel(doc, workflow, t) or _is_legacy_cancel(doc, workflow, t))]
    terminal = _terminal_state(workflow)
    if configured:
        routes = []
        for t in allowed:
            if not (_is_draft_cancel(doc, workflow, t) or _is_legacy_cancel(doc, workflow, t)):
                continue
            if t.get("transition_tasks") or not wf.has_approval_access(frappe.session.user, doc, t):
                continue
            route = frappe._dict(t)
            if _is_legacy_cancel(doc, workflow, t):
                if not terminal:
                    continue
                route.next_state = terminal.state
            route["_qcmc_draft_cancel"] = 1
            routes.append(route)
        return routes
    if not terminal:
        return []
    # An unrelated action named Cancel is not overridden.
    if any(t.state == state and t.action.casefold() == "cancel" for t in workflow.transitions):
        return []
    roles = set(frappe.get_roles())
    role = next((row.allow_edit for row in current_states if row.allow_edit in roles), None)
    if not role:
        return []
    return [frappe._dict(state=state, action="Cancel", next_state=terminal.state,
        allowed=role, allow_self_approval=1, condition=None,
        _qcmc_draft_cancel=1, _qcmc_automatic_cancel=1)]


def _has_permissions(doc):
    return (doc.meta.is_submittable and not doc.meta.istable and not doc.meta.issingle
            and doc.has_permission("read") and doc.has_permission("write") and doc.has_permission("cancel"))


def _require_enabled(doc):
    if not enabled():
        frappe.throw(_("Cancellation before submission is disabled in System Settings."))
    if not _has_permissions(doc):
        frappe.throw(_("Read, write and cancel permissions on a submittable transaction are required."), frappe.PermissionError)
    if cint(doc.docstatus) != 0 or doc.is_new():
        frappe.throw(_("Only a saved draft can be cancelled before submission."))


def _reason(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 2000:
        frappe.throw(_("Enter a cancellation reason (1 to 2000 characters)."))
    return value.strip()


def _check_modified(doc, modified):
    if not modified or str(doc.modified) != str(modified):
        frappe.throw(_("The document changed. Reload it before cancelling."), frappe.TimestampMismatchError)


def _block_dependency(doc, doctype, name):
    if (doctype == doc.doctype and name == doc.name) or doctype == "Workflow Action":
        return
    # Actual parent docstatus is authoritative even on older child rows.
    meta = frappe.get_meta(doctype)
    if meta.issingle:
        active = True
    else:
        value = frappe.db.get_value(doctype, name, "docstatus")
        active = value is not None and cint(value) != 2
    if active:
        if frappe.has_permission(doctype, "read", doc=name):
            frappe.throw(_("Resolve the active linked {0} {1} before cancelling.").format(
                escape_html(doctype), escape_html(name)), frappe.LinkExistsError)
        frappe.throw(_("Resolve an active linked transaction before cancelling."), frappe.LinkExistsError)


def _check_dependencies(doc):
    from frappe.model.delete_doc import get_linked_docs, get_dynamic_linked_docs
    # Delete-mode link discovery finds both draft and submitted references;
    # unlike deletion, we preserve cancelled references and audit records.
    for link in get_linked_docs(doc, method="Delete") + get_dynamic_linked_docs(doc, method="Delete"):
        _block_dependency(doc, link["reference_doctype"], link["reference_docname"])

    if doc.doctype == "Delivery Note":
        # Some ERPNext/custom links are Data fields and are invisible to link discovery.
        details = [row.name for row in doc.items]
        names = set(frappe.get_all("Sales Invoice Item", filters={"delivery_note": doc.name}, pluck="parent"))
        if details:
            names.update(frappe.get_all("Sales Invoice Item", filters={"dn_detail": ["in", details]}, pluck="parent"))
        for name in sorted(names):
            _block_dependency(doc, "Sales Invoice", name)
        for row in doc.items:
            if row.get("against_pick_list"):
                _block_dependency(doc, "Pick List", row.against_pick_list)
        from qcmc_logic.delivery_note_return_allocation import linked_allocations
        for allocation in linked_allocations(doc.name):
            _block_dependency(doc, "Storage Allocation", allocation.name)
        from qcmc_logic.api.delivery_workbench_collaboration import guard_edit
        guard_edit(doc, "before_discard")
    if doc.doctype == "Material Request" and doc.get("material_request_type") == "Purchase":
        from qcmc_logic.customs.purchase_request_workflow import TERMINAL_STATES
        if doc.get("workflow_state") in TERMINAL_STATES:
            frappe.throw(_("This Purchase Request is already terminal."))
        if doc.get("workflow_state") == "Draft" and doc.owner != frappe.session.user and frappe.session.user != "Administrator":
            frappe.throw(_("Only the creator may cancel a draft Purchase Request."), frappe.PermissionError)


def before_discard(doc, method=None):
    # Applies to direct whitelisted Document.discard calls, not just Desk.
    _require_enabled(doc)
    context = frappe.flags.get(FLAG)
    if not context or context.get("key") != (doc.doctype, doc.name):
        frappe.throw(_("Use the authorized Cancel action and enter a cancellation reason."), frappe.PermissionError)
    # Recheck active workflow and current transition after obtaining the row lock.
    if (wf.get_workflow_name(doc.doctype) or "") != context.get("workflow_name"):
        frappe.throw(_("Workflow changed. Reload the document before cancelling."))
    if doc.doctype in ("Delivery Note", "Sales Order"):
        from qcmc_logic.api.sales_order_schedule_split import lock_order_references
        lock_order_references(doc, "before_cancel")
    _check_dependencies(doc)


def _sync_child_status(doc):
    for field in doc.meta.get_table_fields():
        if not field.options or field.get("is_virtual") or frappe.get_meta(field.options).is_virtual:
            continue
        frappe.db.set_value(field.options, {"parent": doc.name, "parenttype": doc.doctype,
            "parentfield": field.fieldname}, "docstatus", 2, update_modified=False)


def _discard(doc, reason, workflow=None, transition=None):
    _require_enabled(doc)
    reason = _reason(reason)
    previous_state = doc.get(workflow.workflow_state_field) if workflow else None
    updates = {}
    if workflow:
        target = _state(workflow, transition)
        if transition.get("transition_tasks"):
            frappe.throw(_("Draft cancellation transitions cannot have transition tasks."))
        field = workflow.workflow_state_field
        updates[field] = target.state
        if target.update_field:
            fieldname = target.update_field
            meta_field = doc.meta.get_field(fieldname)
            if not meta_field or meta_field.get("is_virtual") or fieldname in (
                    "name", "doctype", "docstatus", "owner", "creation", "modified", "modified_by"):
                frappe.throw(_("Invalid workflow cancellation update field."))
            if meta_field.fieldtype in ("Table", "Table MultiSelect"):
                frappe.throw(_("Workflow cancellation cannot update child tables."))
            # Native workflow evaluates expressions against the destination state.
            doc.set(field, target.state)
            try:
                updates[fieldname] = wf.evaluate_workflow_value(
                    target.update_value, target.evaluate_as_expression, doc)
            finally:
                doc.set(field, previous_state)
            if fieldname == field and updates[fieldname] != target.state:
                frappe.throw(_("Workflow update value conflicts with the cancellation state."))
    prior = frappe.flags.get(FLAG)
    frappe.flags[FLAG] = {"key": (doc.doctype, doc.name), "workflow_name": workflow.name if workflow else ""}
    try:
        doc.discard()
        if cint(frappe.db.get_value(doc.doctype, doc.name, "docstatus")) != 2:
            frappe.throw(_("Native discard did not cancel the document."))
        _sync_child_status(doc)
        if updates:
            frappe.db.set_value(doc.doctype, doc.name, updates, update_modified=False)
        doc.reload()
        doc.add_comment("Info", _("Cancelled before submission by {0}. Previous state: {1}. Reason: {2}").format(
            escape_html(frappe.session.user), escape_html(previous_state or "Draft"), escape_html(reason)))
        if workflow:
            # Terminal state: no approval tasks should remain actionable.
            frappe.db.set_value("Workflow Action", {"reference_doctype": doc.doctype,
                "reference_name": doc.name, "status": "Open"},
                {"status": "Completed", "completed_by": frappe.session.user,
                 "completed_by_role": transition.allowed})
            from frappe.desk.notifications import clear_doctype_notifications
            clear_doctype_notifications("Workflow Action")
            doc.add_comment("Workflow", _(updates[workflow.workflow_state_field]))
        if doc.doctype in ("Delivery Note", "Sales Order"):
            from qcmc_logic.api.delivery_workbench_collaboration import notify_change
            notify_change(doc, "on_discard")
        return doc
    finally:
        frappe.flags[FLAG] = prior


@frappe.whitelist()
def get_draft_cancel_availability(doctype, name):
    """Desk eligibility for saved documents without a workflow.

    Read the current setting and actual server permissions, not cached boot
    data or client-side draft permissions. Execution independently rechecks.
    """
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")
    return {"available": bool(enabled() and cint(doc.docstatus) == 0
                and _has_permissions(doc) and not wf.get_workflow_name(doctype))}


@frappe.whitelist(methods=["POST", "PUT"])
def discard(doctype, name, reason=None, modified=None):
    doc = frappe.get_doc(doctype, name, for_update=True)
    _require_enabled(doc)
    _check_modified(doc, modified)
    if wf.get_workflow_name(doctype):
        frappe.throw(_("Cancel this document using its configured Workflow action."), frappe.PermissionError)
    result = _discard(doc, reason)
    return {"name": result.name, "docstatus": cint(result.docstatus)}


@frappe.whitelist()
def get_transitions(doc, workflow=None, raise_exception=False):
    # Never trust caller-supplied workflow configuration.
    data = frappe.parse_json(doc) if isinstance(doc, str) else doc
    if data.get("__islocal") or not data.get("name"):
        return []
    current = frappe.get_doc(data["doctype"], data["name"])
    configured = wf.get_workflow(current.doctype)
    if cint(current.docstatus) == 2:
        current.check_permission("read")
        return []
    transitions = wf.get_transitions(current, configured, cint(raise_exception))
    if cint(current.docstatus) != 0 or not current.meta.is_submittable:
        return transitions
    routes = _draft_routes(current, configured, transitions)
    result = [t for t in transitions if not _is_draft_cancel(current, configured, t)
              and not (enabled() and _is_legacy_cancel(current, configured, t))]
    return result + routes


@frappe.whitelist(methods=["POST", "PUT"])
def apply_workflow(doc, action):
    # Preserve existing DN final posting, Purchase Request reasons and maintenance routing.
    from qcmc_logic.customs.purchase_request_workflow import apply_workflow as existing
    data = frappe.parse_json(doc) if isinstance(doc, str) else doc
    if wf.get_workflow_name(data["doctype"]) and cint(frappe.db.get_value(data["doctype"], data["name"], "docstatus")) == 0:
        current = frappe.get_doc(data["doctype"], data["name"], for_update=True)
        current.check_permission("read")
        workflow = wf.get_workflow(current.doctype)
        allowed = wf.get_transitions(current, workflow)
        candidates = [t for t in allowed if t.action == action]
        routes = [t for t in _draft_routes(current, workflow, allowed) if t.action == action]
        if routes:
            if (len({t.next_state for t in routes}) != 1
                    or any(not (_is_draft_cancel(current, workflow, t) or _is_legacy_cancel(current, workflow, t))
                           for t in candidates)):
                frappe.throw(_("Ambiguous cancellation workflow action. Contact MIS."))
            _require_enabled(current)
            _check_modified(current, data.get("modified"))
            return _discard(current, data.get("_qcmc_draft_cancel_reason"), workflow, routes[0])
        if any(_is_draft_cancel(current, workflow, t) or (enabled() and current.meta.is_submittable
               and _is_legacy_cancel(current, workflow, t)) for t in candidates):
            frappe.throw(_("This cancellation action is not permitted or has been disabled."), frappe.PermissionError)
        if data.get("_qcmc_draft_cancel_reason") is not None:
            frappe.throw(_("Cancellation is not available for this workflow state or user."), frappe.PermissionError)
    return existing(doc, action)
