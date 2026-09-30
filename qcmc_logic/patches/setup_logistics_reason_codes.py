import frappe


REASON_CODES = {
	"OK": "Good to go",
	"TO": "Truck Overload",
	"CR": "Customer Request",
	"SA": "Stock Availability",
	"OR": "Off Route",
	"ND": "Next Delivery Date",
	"SE": "Sales Error",
}


def execute():
	if not frappe.db.table_exists("Logistics Reason Code"):
		return
	for code, meaning in REASON_CODES.items():
		if frappe.db.exists("Logistics Reason Code", code):
			frappe.db.set_value("Logistics Reason Code", code, "meaning", meaning)
			continue
		doc = frappe.new_doc("Logistics Reason Code")
		doc.code = code
		doc.meaning = meaning
		doc.insert(ignore_permissions=True)

