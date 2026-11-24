"""Atomic Sales revisions for a draft Delivery Note and its SO allocation."""

import frappe
from frappe import _


def revise_delivery_note_item(delivery_note, dn_detail, new_qty, destination_date, expected_modified, edit_token=None, remarks=None):
	from qcmc_logic.api import delivery_workbench_collaboration as collaboration
	from qcmc_logic.api import sales_order_schedule_split as split
	from qcmc_logic.api import delivery_confirmation_service as confirmation

	confirmation._validate_sales_approval_role()
	doc = confirmation._get_locked_delivery_note(delivery_note)
	item = next((row for row in doc.items if row.name == dn_detail), None)
	if not item:
		frappe.throw(_("Delivery Note item was not found."))
	if not item.so_detail or not item.against_sales_order:
		frappe.throw(_("This Delivery Note item is not linked to a Sales Order schedule."))
	is_v2 = bool(item.get("custom_so_delivery_schedule"))
	if is_v2:
		_validate_v2_sales_edit_draft(doc)
	else:
		confirmation._validate_sales_review_delivery_note(doc, require_transact=True)
		doc.check_permission("write")
	collaboration.bind_edit(doc, edit_token)
	if str(doc.modified) != str(expected_modified):
		frappe.throw(_("Delivery Note changed. Refresh before editing."), frappe.TimestampMismatchError)
	if is_v2:
		from qcmc_logic.api.delivery_schedule_service import revise_draft_delivery_note_item
		result = revise_draft_delivery_note_item(doc, item, new_qty, destination_date, remarks=remarks)
		collaboration.notify_change(doc)
		return result
	new_qty = frappe.utils.flt(new_qty, item.precision("qty"))
	old_qty = frappe.utils.flt(item.qty, item.precision("qty"))
	if new_qty < 0 or new_qty >= old_qty:
		frappe.throw(_("Enter a quantity from zero up to, but not including, the current DR quantity."))
	if new_qty > confirmation._get_logistics_committed_qty(item):
		frappe.throw(_("Sales quantity cannot exceed Logistics commitment."))
	if new_qty == 0 and len(doc.items) == 1:
		frappe.throw(_("Moving the last item requires moving the whole Delivery Note."))
	if not destination_date:
		frappe.throw(_("Select a destination date for the deferred quantity."))

	so = frappe.get_doc("Sales Order", item.against_sales_order, for_update=True)
	so.check_permission("write")
	source = next((row for row in so.items if row.name == item.so_detail), None)
	if not source:
		frappe.throw(_("Sales Order schedule could not be found."))
	deferred = old_qty - new_qty
	retained_schedule_qty = frappe.utils.flt(source.qty) - deferred
	if retained_schedule_qty < 0:
		frappe.throw(_("The Sales Order schedule no longer contains the quantity being deferred."))

	sp = "sales_delivery_revision"
	frappe.db.savepoint(sp)
	try:
		if new_qty:
			item.qty = new_qty
			item.custom_sales_final_qty = new_qty
			item.custom_sales_move_date = destination_date
		else:
			doc.remove(item)
		if not doc.items:
			frappe.throw(_("A Delivery Note cannot be left without items."))
		doc.run_method("calculate_taxes_and_totals")
		doc.save()

		preview = split.preview_split(
			source_so_detail=source.name,
			retained_quantity=retained_schedule_qty,
			delivery_date=destination_date,
		)
		split.split_schedule(
			source_so_detail=source.name,
			retained_quantity=retained_schedule_qty,
			delivery_date=destination_date,
			reason=_("Sales revised Delivery Note {0}").format(doc.name),
			expected_state=preview["state"],
		)
		doc.add_comment("Info", _(
			"Sales changed Delivery Note item {0} quantity from {1} to {2}; {3} was deferred to {4}."
		).format(item.item_code, old_qty, new_qty, deferred, destination_date))
		collaboration.notify_change(doc)
		return {"saved": True, "delivery_note": doc.name, "deferred_qty": deferred,
			"destination_date": str(destination_date), "sales_order": so.name}
	except Exception:
		frappe.db.rollback(save_point=sp)
		raise


def move_delivery_note_date(delivery_note, destination_date, expected_modified, edit_token=None, remarks=None):
	from qcmc_logic.api import delivery_workbench_collaboration as collaboration
	from qcmc_logic.api import sales_order_schedule_split as split
	from qcmc_logic.api import delivery_confirmation_service as confirmation

	confirmation._validate_sales_approval_role()
	doc = confirmation._get_locked_delivery_note(delivery_note)
	has_v2 = any(row.get("custom_so_delivery_schedule") for row in doc.items)
	if has_v2:
		_validate_v2_sales_edit_draft(doc)
	else:
		confirmation._validate_sales_review_delivery_note(doc, require_transact=True)
		doc.check_permission("write")
	collaboration.bind_edit(doc, edit_token)
	if str(doc.modified) != str(expected_modified):
		frappe.throw(_("Delivery Note changed. Reopen the preview before moving it."), frappe.TimestampMismatchError)
	if not destination_date:
		frappe.throw(_("Select a destination date."))
	if not doc.items or any(not row.so_detail or not row.against_sales_order for row in doc.items):
		frappe.throw(_("Every DR item must be linked to a Sales Order schedule."))
	if any(isinstance(row.get("custom_so_delivery_schedule"), str) and row.get("custom_so_delivery_schedule") for row in doc.items):
		if any(not isinstance(row.get("custom_so_delivery_schedule"), str) or not row.get("custom_so_delivery_schedule") for row in doc.items):
			frappe.throw(_("A Delivery Note cannot mix schedule-linked and unlinked items."))
		from qcmc_logic.api.delivery_schedule_service import move_draft_delivery_note
		result = move_draft_delivery_note(doc, destination_date, remarks=remarks)
		collaboration.notify_change(doc)
		return result

	date = frappe.utils.getdate(destination_date)
	item_sources = {}
	for item in doc.items:
		so = frappe.get_doc("Sales Order", item.against_sales_order, for_update=True)
		so.check_permission("write")
		source = next((row for row in so.items if row.name == item.so_detail), None)
		if not source:
			frappe.throw(_("Sales Order schedule for item {0} could not be found.").format(item.item_code))
		if frappe.utils.getdate(source.get("custom_next_scheduling_date") or source.delivery_date) == date:
			continue
		entry = item_sources.setdefault(source.name, {"qty": source.qty, "items": []})
		entry["items"].append(item)
	if not item_sources:
		frappe.throw(_("The Delivery Note is already scheduled for that date."))

	sp = "whole_delivery_note_date_move"
	frappe.db.savepoint(sp)
	try:
		# Temporarily release the old draft allocations in this transaction so the
		# authoritative split service can validate and move exactly these quantities.
		for entry in item_sources.values():
			for item in entry["items"]:
				item.so_detail = None
				item.against_sales_order = None
		doc.save()

		for source_name, entry in item_sources.items():
			items = entry["items"]
			deferred_qty = sum(frappe.utils.flt(item.qty) for item in items)
			retained = frappe.utils.flt(entry["qty"]) - deferred_qty
			if retained < 0:
				frappe.throw(_("The Delivery Note quantity exceeds its Sales Order schedule."))
			preview = split.preview_split(source_name, retained_quantity=retained, delivery_date=date)
			result = split.split_schedule(source_name, retained_quantity=retained, delivery_date=date,
				reason=_("Whole Delivery Note {0} moved by Sales").format(doc.name), expected_state=preview["state"])
			for item in items:
				item.against_sales_order = so.name
				item.so_detail = result["destination"]
				if item.meta.has_field("delivery_date"):
					item.delivery_date = date
				for field in ("custom_logistics_reason", "custom_logistics_remarks", "custom_logistics_proposed_qty", "custom_logistics_proposed_date"):
					if item.meta.has_field(field):
						item.set(field, None)
				item.custom_sales_final_qty = item.qty
				item.custom_sales_move_date = date
				item.custom_sales_remove = 0
		doc.save()
		doc.add_comment("Info", _("Whole Delivery Note moved to {0}; Logistics confirmation is required again.").format(date))
		collaboration.notify_change(doc)
		return {"saved": True, "delivery_note": doc.name, "delivery_date": str(date)}
	except Exception:
		frappe.db.rollback(save_point=sp)
		raise


def _validate_v2_sales_edit_draft(doc):
	"""V2 schedule edits are operational authorization, separate from legacy DN write permission."""
	if "Sales Coordinator" not in frappe.get_roles():
		frappe.throw(_("Sales Coordinator permission is required."), frappe.PermissionError)
	if doc.docstatus != 0 or doc.workflow_state != "Draft" or doc.get("custom_dr_number"):
		frappe.throw(_("Only an unnumbered V2 Draft Delivery Note can be revised or moved."))
	if not doc.items or any(not row.get("custom_so_delivery_schedule") for row in doc.items):
		frappe.throw(_("A V2 Delivery Note edit cannot include legacy schedule rows."))
	if any(not row.get("so_detail") or not row.get("against_sales_order") for row in doc.items):
		frappe.throw(_("Every V2 Delivery Note row must retain its Sales Order Item reference."))
	if not frappe.has_permission("Delivery Note", "read", doc=doc):
		frappe.throw(_("You are not allowed to read this Delivery Note."), frappe.PermissionError)
	detail_names = [row.name for row in doc.items]
	if detail_names:
		active_invoice = frappe.db.sql("""
			SELECT si.name FROM `tabSales Invoice Item` sii
			JOIN `tabSales Invoice` si ON si.name = sii.parent
			WHERE sii.dn_detail IN %(details)s AND si.docstatus < 2 LIMIT 1
		""", {"details": tuple(detail_names)})
		if active_invoice:
			frappe.throw(_("A Delivery Note with an active Sales Invoice cannot be revised or moved."))
