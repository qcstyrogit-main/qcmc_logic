import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


LOGISTICS_REASON_OPTIONS = "\nOK\nTO\nCR\nSA\nOR\nND\nSE"


def execute():
	create_custom_fields(
		{
			"Delivery Note Item": [
				{
					"fieldname": "custom_logistics_reason",
					"label": "Logistics Reason",
					"fieldtype": "Select",
					"options": LOGISTICS_REASON_OPTIONS,
					"insert_after": "custom_quantity",
				},
				{
					"fieldname": "custom_logistics_remarks",
					"label": "Logistics Remarks",
					"fieldtype": "Small Text",
					"insert_after": "custom_logistics_reason",
				},
				{
					"fieldname": "custom_logistics_proposed_qty",
					"label": "Logistics Proposed Qty",
					"fieldtype": "Float",
					"insert_after": "custom_logistics_remarks",
				},
				{
					"fieldname": "custom_logistics_proposed_date",
					"label": "Logistics Proposed Date",
					"fieldtype": "Date",
					"insert_after": "custom_logistics_proposed_qty",
				},
			]
		},
		update=True,
	)
	frappe.db.set_value(
		"Custom Field",
		"Delivery Note Item-custom_logistics_reason",
		"options",
		LOGISTICS_REASON_OPTIONS,
	)
	frappe.clear_cache(doctype="Delivery Note Item")
	_clear_incorrect_delivery_note_recommendations("MAT-DN-2026-00224")


def _clear_incorrect_delivery_note_recommendations(delivery_note):
	if not frappe.db.exists("Delivery Note", delivery_note):
		return
	fields = {
		"custom_logistics_reason": "",
		"custom_logistics_remarks": "",
	}
	if frappe.db.has_column("Delivery Note Item", "custom_logistics_proposed_qty"):
		fields["custom_logistics_proposed_qty"] = 0
	if frappe.db.has_column("Delivery Note Item", "custom_logistics_proposed_date"):
		fields["custom_logistics_proposed_date"] = None
	for item in frappe.get_all("Delivery Note Item", filters={"parent": delivery_note}, pluck="name"):
		frappe.db.set_value("Delivery Note Item", item, fields, update_modified=False)
