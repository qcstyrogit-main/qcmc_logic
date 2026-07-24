import frappe


def execute():
	for name in ("Customer-tax_id-mask", "Sales Order-tax_id-mask"):
		if frappe.db.exists("Property Setter", name):
			frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)

	for doctype in ("Sales Order", "Delivery Note"):
		rows = frappe.get_all(
			doctype,
			filters={"tax_id": ["in", ["XXXXXXX", "XXXXXXXX"]]},
			fields=["name", "customer"],
			limit_page_length=0,
		)
		for row in rows:
			tax_id = frappe.db.get_value("Customer", row.customer, "tax_id")
			if tax_id and set(tax_id) != {"X"}:
				frappe.db.set_value(doctype, row.name, "tax_id", tax_id, update_modified=False)

	frappe.clear_cache(doctype="Customer")
	frappe.clear_cache(doctype="Sales Order")
	frappe.clear_cache(doctype="Delivery Note")
	frappe.db.commit()
