"""Sales revisions for schedule-linked unnumbered draft Delivery Notes."""

import frappe
from frappe import _


def revise_delivery_note_item(delivery_note, dn_detail, new_qty, destination_date, expected_modified, edit_token=None, remarks=None):
    from qcmc_logic.api import delivery_workbench_collaboration as collaboration
    from qcmc_logic.api import delivery_confirmation_service as confirmation
    from qcmc_logic.api.delivery_schedule_service import revise_draft_delivery_note_item

    confirmation._validate_sales_approval_role()
    doc = confirmation._get_locked_delivery_note(delivery_note)
    _validate_v2_sales_edit_draft(doc)
    collaboration.bind_edit(doc, edit_token)
    if str(doc.modified) != str(expected_modified):
        frappe.throw(_("Delivery Note changed. Refresh before editing."), frappe.TimestampMismatchError)
    item = next((row for row in doc.items if row.name == dn_detail), None)
    if not item:
        frappe.throw(_("Delivery Note item was not found."))
    result = revise_draft_delivery_note_item(doc, item, new_qty, destination_date, remarks=remarks)
    collaboration.notify_change(doc)
    return result


def move_delivery_note_date(delivery_note, destination_date, expected_modified, edit_token=None, remarks=None):
    from qcmc_logic.api import delivery_workbench_collaboration as collaboration
    from qcmc_logic.api import delivery_confirmation_service as confirmation
    from qcmc_logic.api.delivery_schedule_service import move_draft_delivery_note

    confirmation._validate_sales_approval_role()
    doc = confirmation._get_locked_delivery_note(delivery_note)
    _validate_v2_sales_edit_draft(doc)
    collaboration.bind_edit(doc, edit_token)
    if str(doc.modified) != str(expected_modified):
        frappe.throw(_("Delivery Note changed. Reopen the preview before moving it."), frappe.TimestampMismatchError)
    if not destination_date:
        frappe.throw(_("Select a destination date."))
    result = move_draft_delivery_note(doc, destination_date, remarks=remarks)
    collaboration.notify_change(doc)
    return result


def _validate_v2_sales_edit_draft(doc):
	"""Schedule edits are operational authorization, separate from direct DN write permission."""
	if "Sales Coordinator" not in frappe.get_roles():
		frappe.throw(_("Sales Coordinator permission is required."), frappe.PermissionError)
	if doc.docstatus != 0 or doc.workflow_state != "Draft" or doc.get("custom_dr_number"):
		frappe.throw(_("Only an unnumbered, schedule-linked Draft Delivery Note can be revised or moved."))
	if not doc.items or any(not row.get("custom_so_delivery_schedule") for row in doc.items):
		frappe.throw(_("Every Delivery Note item must link to an SO Delivery Schedule; reconcile historical records first."))
	if any(not row.get("so_detail") or not row.get("against_sales_order") for row in doc.items):
		frappe.throw(_("Every Delivery Note row must retain its Sales Order Item reference."))
	if not frappe.has_permission("Delivery Note", "read", doc=doc):
		frappe.throw(_("You are not allowed to read this Delivery Note."), frappe.PermissionError)
	detail_names = [row.name for row in doc.items]
	if detail_names:
		active_invoice = frappe.db.sql("""
			SELECT si.name FROM  sii
			JOIN  si ON si.name = sii.parent
			WHERE sii.dn_detail IN %(details)s AND si.docstatus < 2 LIMIT 1
		""", {"details": tuple(detail_names)})
		if active_invoice:
			frappe.throw(_("A Delivery Note with an active Sales Invoice cannot be revised or moved."))