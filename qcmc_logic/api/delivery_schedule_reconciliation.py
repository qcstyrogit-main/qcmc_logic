"""Read-only preflight for migrating mutable legacy schedule rows."""

import frappe
from frappe import _


@frappe.whitelist(methods=["GET"])
def preflight_delivery_schedule_reconciliation(limit=1000):
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("System Manager permission is required for migration preflight."), frappe.PermissionError)
	try:
		limit = min(max(int(limit), 1), 5000)
	except (TypeError, ValueError):
		frappe.throw(_("Invalid row limit."))
	# This endpoint must remain usable before the V2 schema patch is applied.
	# Project absent V2 columns as NULL/default literals rather than making the
	# pre-migration inventory itself depend on the migration it is meant to gate.
	schedule_columns = {field: frappe.db.has_column("SO Delivery Schedule", field)
		for field in ("original_delivery_date", "original_qty", "history_status")}
	so_item_field = frappe.db.has_column("Delivery Note Item", "custom_so_delivery_schedule")
	projection = ", ".join(
		f"s.{field}" if exists else f"NULL AS {field}"
		for field, exists in schedule_columns.items())
	dn_join = """
		LEFT JOIN (
			SELECT dni.custom_so_delivery_schedule AS schedule,
				COUNT(DISTINCT CASE WHEN dn.docstatus = 2 THEN dn.name END) AS cancelled_dn_count,
				SUM(CASE WHEN dn.docstatus = 2 THEN dni.qty ELSE 0 END) AS cancelled_dn_qty,
				SUM(CASE WHEN dn.docstatus = 1 THEN dni.qty ELSE 0 END) AS submitted_dn_qty,
				SUM(CASE WHEN dn.docstatus = 0 THEN dni.qty ELSE 0 END) AS draft_dn_qty
			FROM `tabDelivery Note Item` dni JOIN `tabDelivery Note` dn ON dn.name = dni.parent
			WHERE dni.custom_so_delivery_schedule IS NOT NULL
			GROUP BY dni.custom_so_delivery_schedule
		) d ON d.schedule = s.name
	""" if so_item_field else """
		LEFT JOIN (SELECT NULL AS schedule, 0 AS cancelled_dn_count, 0 AS cancelled_dn_qty,
			0 AS submitted_dn_qty, 0 AS draft_dn_qty) d ON 1 = 0
	"""
	rows = frappe.db.sql(f"""
		SELECT s.name, s.sales_order, s.sales_order_item, s.item_code, s.warehouse,
			s.delivery_date AS current_schedule_date, s.planned_qty AS current_total,
			{projection},
		COALESCE(d.cancelled_dn_count, 0) AS cancelled_dn_count,
		COALESCE(d.cancelled_dn_qty, 0) AS cancelled_dn_qty,
		COALESCE(d.submitted_dn_qty, 0) AS submitted_dn_qty,
		COALESCE(d.draft_dn_qty, 0) AS draft_dn_qty,
		COALESCE(v.version_count, 0) AS version_count
		FROM `tabSO Delivery Schedule` s
		{dn_join}
		LEFT JOIN (
			SELECT docname, COUNT(*) AS version_count FROM `tabVersion`
			WHERE ref_doctype = 'SO Delivery Schedule' GROUP BY docname
		) v ON v.docname = s.name
		ORDER BY s.creation, s.name
		LIMIT %s
	""", (limit,), as_dict=True)
	for row in rows:
		row.classification = "Verified New V2" if row.history_status == "Verified" and row.original_qty is not None else "Ambiguous — review required"
		row.evidence = "Stored original values" if row.classification == "Verified New V2" else (
			"Version history and linked DN quantities are evidence only; originals were not inferred."
		)
	return {"rows": rows, "count": len(rows), "mutated": False,
		"schema_columns_present": {**schedule_columns, "Delivery Note Item.custom_so_delivery_schedule": so_item_field},
		"warning": _("This report does not reconstruct or update historical original values.")}
