"""Shared Delivery Note Printing workbench services and deprecated report data."""

import frappe
from frappe import _
from frappe.utils import flt

from qcmc_logic.utils import (
	_get_effective_warehouse_access_names,
	get_user_allowed_warehouses,
)


def execute(filters=None):
	_validate_invoicing_role()
	filters = frappe._dict(filters or {})
	columns = [
		{"label": _("Delivery Note"), "fieldname": "delivery_note", "fieldtype": "Link", "options": "Delivery Note", "width": 160},
		{"label": _("DR Number"), "fieldname": "dr_number", "fieldtype": "Data", "width": 120},
		{"label": _("Invoice Number"), "fieldname": "invoice_number", "fieldtype": "Link", "options": "Sales Invoice", "width": 140},
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 150},
		{"label": _("Customer"), "fieldname": "customer_name", "fieldtype": "Data", "width": 210},
		{"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 210},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 180},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 90},
		{"label": _("Scheduled Date"), "fieldname": "delivery_date", "fieldtype": "Date", "width": 125},
	]
	if not filters.get("company") or not filters.get("delivery_date"):
		return columns, [], _("Select a company and delivery date."), None, []

	conditions = ["dn.company = %(company)s", "((dni.custom_so_delivery_schedule IS NULL AND soi.delivery_date <= %(delivery_date)s) OR (dni.custom_so_delivery_schedule IS NOT NULL AND operational_schedule.delivery_date <= %(delivery_date)s))"]
	values = {"company": filters.company, "delivery_date": filters.delivery_date}
	permitted_docs = frappe.get_list(
		"Delivery Note",
		filters={"company": filters.company, "docstatus": 0},
		pluck="name",
		page_length=0,
	)
	if not permitted_docs:
		return columns, [], _("No Delivery Notes are available for this filter."), None, []
	conditions.append("dn.name IN %(permitted_delivery_notes)s")
	values["permitted_delivery_notes"] = tuple(permitted_docs)
	if filters.get("warehouse"):
		conditions.append("dni.warehouse = %(warehouse)s")
		values["warehouse"] = filters.warehouse
	_apply_warehouse_scope(conditions, values)

	rows = frappe.db.sql("""
		SELECT dni.name AS dn_detail, dn.name AS delivery_note,
			dn.custom_dr_number AS dr_number, si.name AS invoice_number,
			dni.against_sales_order AS sales_order,
			dn.customer_name, dni.item_code, dni.item_name, dni.warehouse, dni.qty,
			COALESCE(operational_schedule.delivery_date, soi.delivery_date) AS delivery_date,
		dni.custom_so_delivery_schedule AS schedule_id
		FROM `tabDelivery Note` dn
		JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		JOIN `tabSales Order Item` soi ON soi.name = dni.so_detail
		LEFT JOIN `tabSO Delivery Schedule` operational_schedule ON operational_schedule.name = dni.custom_so_delivery_schedule
		LEFT JOIN `tabSales Order` schedule_so ON schedule_so.name = soi.parent
		JOIN `tabWarehouse` wh ON wh.name = dni.warehouse
		LEFT JOIN `tabSales Invoice Item` sii ON sii.dn_detail = dni.name AND sii.docstatus < 2
		LEFT JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE dn.docstatus = 0
			AND (dn.workflow_state = 'For DR Printing' OR
				(dn.workflow_state = 'Draft' AND dni.custom_so_delivery_schedule IS NOT NULL
					AND operational_schedule.confirmation_status = 'Finalized'
					AND operational_schedule.history_status = 'Verified'))
			AND IFNULL(wh.custom_is_province, 0) = 0
			AND {conditions}
		ORDER BY delivery_date, dn.name, dni.idx
	""".format(
		conditions=" AND ".join(conditions),
	), values, as_dict=True)

	return columns, rows, _("{0} item(s) ready for DR printing.").format(len(rows)), None, [
		{"value": len({row.delivery_note for row in rows}), "indicator": "Orange", "label": _("Delivery Notes"), "datatype": "Int"},
		{"value": len({row.delivery_note for row in rows if row.dr_number}), "indicator": "Green", "label": _("Numbered"), "datatype": "Int"},
	]


@frappe.whitelist()
def get_workbench_data(filters=None):
	filters = frappe._dict(frappe.parse_json(filters or "{}"))
	_validate_invoicing_role()
	if not filters.get("company") or not filters.get("delivery_date"):
		return {"rows": [], "message": _("Select a company and delivery date.")}
	doc_names = frappe.get_list(
		"Delivery Note",
		filters={"company": filters.company, "docstatus": 0},
		fields=["name"],
		order_by="modified asc",
		page_length=0,
	)
	rows = []
	for entry in doc_names:
		doc = frappe.get_doc("Delivery Note", entry.name)
		if not _is_printable_queue_document(doc):
			continue
		if not frappe.has_permission("Delivery Note", "read", doc=doc):
			continue
		try:
			for item in doc.items:
				_validate_warehouse_access(item.warehouse)
		except frappe.PermissionError:
			continue
		items = []
		for item in doc.items:
			items.append({"item_code": item.item_code, "item_name": item.item_name, "qty": item.qty, "warehouse": item.warehouse})
		delivery_note_date = str(doc.posting_date or doc.get("posting_date") or "")
		if not items or not delivery_note_date or delivery_note_date > str(filters.delivery_date):
			continue
		if filters.get("warehouse") and not any(item["warehouse"] == filters.warehouse for item in items):
			continue
		invoice_rows = frappe.db.sql("""
			SELECT DISTINCT si.name, si.docstatus
			FROM `tabSales Invoice Item` sii JOIN `tabSales Invoice` si ON si.name = sii.parent
			WHERE sii.delivery_note = %s AND si.docstatus < 2
			ORDER BY si.creation
		""", doc.name, as_dict=True)
		invoices = [
			{"name": row.name, "status": _( "Draft") if row.docstatus == 0 else _("Submitted")}
			for row in invoice_rows if frappe.has_permission("Sales Invoice", "read", row.name)
		]
		rows.append({
			"delivery_note": doc.name,
			"delivery_note_date": delivery_note_date,
			"dr_number": doc.get("custom_dr_number"),
			"sales_order": doc.get("custom_sales_order") or ", ".join(sorted({item.get("against_sales_order") for item in doc.items if item.get("against_sales_order")})),
			"customer_name": doc.customer_name,
			"item_count": len(items),
			"items": items,
			"invoices": invoices,
			"modified": str(doc.modified),
		})
	return {"rows": rows, "message": _("{0} Delivery Note(s) ready for DR printing.").format(len(rows))}



@frappe.whitelist(methods=["POST"])
def assign_dr_number(delivery_note, dr_number):
	_validate_invoicing_role()
	dr_number = (dr_number or "").strip()
	if not dr_number:
		frappe.throw(_("DR Number is required."))

	# Serializes assignment of the same DR number across concurrent clerk sessions.
	with frappe.cache.lock("delivery-note-dr-number:{0}".format(dr_number), timeout=15):
		doc = _get_locked_delivery_note(delivery_note)
		_validate_delivery_note(doc, require_transact=True)
		v2_draft = _is_v2_printing_draft(doc)
		if not v2_draft:
			doc.check_permission("write")
		duplicate = frappe.db.get_value(
			"Delivery Note",
			{"custom_dr_number": dr_number, "name": ["!=", doc.name], "docstatus": ["!=", 2]},
			"name",
		)
		if duplicate:
			frappe.throw(_("DR Number {0} is already assigned to Delivery Note {1}.").format(
				frappe.bold(dr_number), frappe.bold(duplicate)
			))
		doc.custom_dr_number = dr_number
		if v2_draft:
			# Invoicing Clerk owns only this printing metadata write for validated V2 Drafts.
			doc.save(ignore_permissions=True)
		else:
			doc.save()
		saved_dr_number = frappe.db.get_value("Delivery Note", doc.name, "custom_dr_number")
		if saved_dr_number != dr_number:
			frappe.throw(_("DR Number could not be verified after saving. Print preview was not started."))
		doc.add_comment("Edit", _("Assigned DR Number {0} for printing.").format(frappe.bold(dr_number)))

	return {
		"delivery_note": doc.name,
		"dr_number": saved_dr_number,
		"print_format": _get_print_format(doc.company),
	}


@frappe.whitelist(methods=["POST"])
def submit_for_delivery(delivery_notes):
	_validate_invoicing_role()
	names = list(dict.fromkeys(frappe.parse_json(delivery_notes)))
	if not names:
		frappe.throw(_("Select at least one Delivery Note."))

	for name in sorted(names):
		doc = _get_locked_delivery_note(name)
		_validate_delivery_note(doc, require_transact=True)
		v2_draft = _is_v2_printing_draft(doc)
		if not v2_draft:
			doc.check_permission("write")
		if not doc.custom_dr_number:
			frappe.throw(_("Assign and print a DR Number for Delivery Note {0} first.").format(frappe.bold(name)))
		if v2_draft:
			from frappe.model.workflow import apply_workflow

			doc = apply_workflow(doc.as_json(), "Submit for Delivery")
			if doc.docstatus != 0 or doc.workflow_state != "To Deliver and Bill":
				frappe.throw(_("Delivery Note {0} was not released through its valid workflow transition.").format(name))
		else:
			doc.workflow_state = "To Deliver and Bill"
			doc.status = "To Deliver and Bill"
			doc.save()
			doc.add_comment("Workflow", _("Submit for Delivery"))

	return _("Submitted Delivery Note(s) for delivery: {0}").format(", ".join(names))


@frappe.whitelist(methods=["POST"])
def create_sales_invoices(delivery_notes, invoice_number):
	_validate_invoicing_role()
	names = list(dict.fromkeys(frappe.parse_json(delivery_notes)))
	if len(names) != 1:
		frappe.throw(_("Create an invoice for exactly one Delivery Note at a time."))
	invoice_number = (invoice_number or "").strip()
	if not invoice_number:
		frappe.throw(_("Invoice Number is required."))
	field = frappe.get_meta("Sales Invoice").get_field("custom_invoice_number")
	max_length = field.length if field else None
	if max_length and len(invoice_number) > max_length:
		frappe.throw(_("Invoice Number cannot exceed {0} characters.").format(max_length))
	if not frappe.has_permission("Sales Invoice", "create"):
		frappe.throw(_("You are not allowed to create Sales Invoices."), frappe.PermissionError)
	name = names[0]
	from qcmc_logic.api.delivery_note import create_sales_invoice_from_draft_dn
	with frappe.cache.lock("sales-invoice-custom-number:{0}".format(invoice_number), timeout=15):
		duplicate = frappe.db.get_value(
			"Sales Invoice",
			{"custom_invoice_number": invoice_number},
			"name",
		)
		if duplicate:
			# A retry may follow a saved invoice whose preview failed. Reuse it
			# only after the same permission and full-document matching checks.
			return verify_sales_invoice_for_preview(name, invoice_number, duplicate)

		doc = _get_locked_delivery_note(name)
		_validate_delivery_note(doc, require_transact=True)
		dr_number = (doc.get("custom_dr_number") or "").strip()
		if not dr_number:
			frappe.throw(_("Assign a DR Number to Delivery Note {0} before creating its Sales Invoice.").format(
				frappe.bold(doc.name)
			), title=_("DR Number Required"))
		detail_names = [item.name for item in doc.items]
		existing = frappe.db.sql("""
			SELECT DISTINCT sii.parent FROM `tabSales Invoice Item` sii
			JOIN `tabSales Invoice` si ON si.name = sii.parent
			WHERE sii.dn_detail IN %(details)s AND si.docstatus < 2
		""", {"details": tuple(detail_names)}, as_dict=True)
		if existing:
			frappe.throw(_("An active Sales Invoice is already linked to this Delivery Note: {0}.").format(
				", ".join(row.parent for row in existing)
			), title=_("Invoice Already Exists"))

		invoice = create_sales_invoice_from_draft_dn(name)
		if invoice.get("custom_delivery_number") != dr_number:
			invoice.custom_delivery_number = dr_number
		invoice.custom_invoice_number = invoice_number
		if not frappe.has_permission("Sales Invoice", "print", doc=invoice):
			frappe.throw(_("You are not allowed to print this Sales Invoice."), frappe.PermissionError)
		invoice.insert()

	return {
		"delivery_note": doc.name,
		"sales_invoice": invoice.name,
		"invoice_number": invoice_number,
		"dr_number": dr_number,
	}


@frappe.whitelist(methods=["POST"])
def verify_sales_invoice_for_preview(delivery_note, invoice_number=None, sales_invoice=None):
	_validate_invoicing_role()
	dn = frappe.get_doc("Delivery Note", delivery_note)
	dn.check_permission("read")
	if sales_invoice:
		_invoice = frappe.get_doc("Sales Invoice", sales_invoice)
	else:
		matches = frappe.get_list(
			"Sales Invoice",
			filters={"custom_invoice_number": invoice_number},
			fields=["name"],
			page_length=2,
		)
		if len(matches) != 1:
			frappe.throw(_("No single saved Sales Invoice was found for invoice number {0}.").format(
				frappe.bold(invoice_number)
			))
		_invoice = frappe.get_doc("Sales Invoice", matches[0].name)
	_invoice.check_permission("read")
	_invoice.check_permission("print")
	if invoice_number is None:
		invoice_number = _invoice.get("custom_invoice_number")
	if not invoice_number:
		frappe.throw(_("The saved Sales Invoice has no Invoice Number."))

	if _invoice.docstatus != 0:
		frappe.throw(_("Sales Invoice {0} is not a draft and cannot be previewed from this workbench.").format(
			frappe.bold(_invoice.name)
		))
	dr_number = (dn.get("custom_dr_number") or "").strip()
	if not dr_number or _invoice.get("custom_invoice_number") != invoice_number or _invoice.get("custom_delivery_number") != dr_number:
		frappe.throw(_("The saved invoice number or DR reference does not match the Delivery Note."))

	expected = {item.name: item for item in dn.items}
	seen = set()
	for item in _invoice.items:
		source = expected.get(item.get("dn_detail"))
		if (
			not source or item.get("dn_detail") in seen
			or item.get("delivery_note") != dn.name
			or any(item.get(field) != source.get(field) for field in ("item_code", "qty", "uom", "conversion_factor"))
		):
			frappe.throw(_("The saved Sales Invoice items or quantities do not match Delivery Note {0}.").format(
				frappe.bold(dn.name)
			))
		seen.add(item.dn_detail)
	if not expected or seen != set(expected):
		frappe.throw(_("The saved Sales Invoice does not reference every item on Delivery Note {0} exactly.").format(
			frappe.bold(dn.name)
		))

	return {
		"verified": True,
		"delivery_note": dn.name,
		"sales_invoice": _invoice.name,
		"print_format": ("Charge Invoice Receipt QC" if _invoice.company == "QC Styropackaging Corporation"
			else frappe.get_meta("Sales Invoice").default_print_format or "Standard"),
		"invoice_number": _invoice.custom_invoice_number,
		"dr_number": _invoice.custom_delivery_number,
	}


def _get_locked_delivery_note(name):
	from qcmc_logic.api.sales_order_schedule_split import lock_orders
	parents = frappe.get_all("Delivery Note Item", filters={"parent": name}, pluck="against_sales_order")
	lock_orders([parent for parent in parents if parent])
	locked_name = frappe.db.sql(
		"SELECT name FROM `tabDelivery Note` WHERE name = %s FOR UPDATE", (name,)
	)
	if not locked_name:
		frappe.throw(_("Delivery Note {0} was not found.").format(name))
	return frappe.get_doc("Delivery Note", name, for_update=True)


def _validate_delivery_note(doc, require_transact=False):
	if doc.docstatus != 0 or not _is_printable_queue_document(doc):
		frappe.throw(_("Delivery Note {0} is no longer awaiting DR printing.").format(doc.name))
	for item in doc.items:
		_validate_warehouse_access(item.warehouse, require_transact=require_transact)
	doc.check_permission("read")


def _is_v2_printing_draft(doc):
	if doc.docstatus != 0 or doc.workflow_state != "Draft" or not doc.items:
		return False
	linked_orders = {item.get("against_sales_order") for item in doc.items}
	if len(linked_orders) != 1 or not doc.get("custom_sales_order") or doc.get("custom_sales_order") not in linked_orders:
		return False
	so = frappe.db.get_value("Sales Order", doc.custom_sales_order,
		["company", "customer", "docstatus", "status"], as_dict=True)
	from qcmc_logic.api.sales_order_delivery_eligibility import OPEN_DELIVERY_STATUSES
	if (not so or so.company != doc.company or so.customer != doc.customer or so.docstatus != 1
		or so.status not in OPEN_DELIVERY_STATUSES):
		return False
	for item in doc.items:
		schedule_name = item.get("custom_so_delivery_schedule")
		if not schedule_name or not item.get("so_detail") or not item.get("against_sales_order"):
			return False
		schedule = frappe.db.get_value("SO Delivery Schedule", schedule_name,
			["sales_order", "sales_order_item", "item_code", "warehouse", "confirmation_status"], as_dict=True)
		if (not schedule or schedule.sales_order != item.against_sales_order
			or schedule.sales_order_item != item.so_detail or schedule.item_code != item.item_code
			or schedule.warehouse != item.warehouse or schedule.confirmation_status != "Finalized"):
			return False
	return True


def _is_printable_queue_document(doc):
	return doc.workflow_state == "For DR Printing" or _is_v2_printing_draft(doc)


def _validate_v2_release_transition(doc):
	"""Revalidate the V2 Draft-to-delivery transition for workflow and direct saves."""
	if "Invoicing Clerk" not in frappe.get_roles():
		frappe.throw(_("Invoicing Clerk permission is required to release this Delivery Note."), frappe.PermissionError)
	if not (doc.get("custom_dr_number") or "").strip():
		frappe.throw(_("Assign a DR Number before releasing this Delivery Note."))

	next_state = doc.workflow_state
	try:
		# The shared V2 validator describes the immediately preceding Draft state.
		doc.workflow_state = "Draft"
		if not _is_v2_printing_draft(doc):
			frappe.throw(_("Only a fully confirmed V2 Draft Delivery Note can be released."))
	finally:
		doc.workflow_state = next_state

	for item in doc.items:
		schedule = frappe.db.get_value("SO Delivery Schedule", item.get("custom_so_delivery_schedule"),
			["final_qty", "confirmation_status", "sales_confirmed_by", "logistics_confirmed_by"], as_dict=True)
		if (not schedule or schedule.confirmation_status != "Finalized"
			or not schedule.sales_confirmed_by or not schedule.logistics_confirmed_by
			or flt(schedule.final_qty, item.precision("qty")) != flt(item.qty, item.precision("qty"))):
			frappe.throw(_("Delivery Note quantity must match its jointly finalized schedule before release."))
		_validate_warehouse_access(item.warehouse, require_transact=True)


def _validate_invoicing_role():
	roles = set(frappe.get_roles(frappe.session.user))
	if frappe.session.user != "Administrator" and "Invoicing Clerk" not in roles:
		frappe.throw(_("You are not allowed to assign or submit Delivery Receipts."), frappe.PermissionError)


def _apply_warehouse_scope(conditions, values):
	user = frappe.session.user
	if not _get_effective_warehouse_access_names(user, source="Role Profile"):
		return
	warehouses = get_user_allowed_warehouses(user, require_list_view=True, source="Role Profile")
	if not warehouses:
		conditions.append("1 = 0")
	else:
		conditions.append("dni.warehouse IN %(allowed_warehouses)s")
		values["allowed_warehouses"] = tuple(warehouses)


def _validate_warehouse_access(warehouse, require_transact=False):
	user = frappe.session.user
	if not _get_effective_warehouse_access_names(user, source="Role Profile"):
		return
	allowed = set(get_user_allowed_warehouses(
		user,
		require_transact=require_transact,
		require_list_view=not require_transact,
		source="Role Profile",
	))
	if not warehouse or warehouse not in allowed:
		frappe.throw(_("You are not allowed to transact in warehouse {0}.").format(warehouse), frappe.PermissionError)


def _get_print_format(company):
	return frappe.get_meta("Delivery Note").default_print_format or "Standard"
