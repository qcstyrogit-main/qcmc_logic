import frappe
from frappe.model.mapper import get_mapped_doc

@frappe.whitelist()
def create_sales_invoice_from_draft_dn(dn_name):

    def set_missing_values(source, target):
        # carry over essential header fields
        target.customer = source.customer
        target.company = source.company
        target.posting_date = frappe.utils.today()

        # optional but helpful
        target.ignore_pricing_rule = 1

    si = get_mapped_doc(
        "Delivery Note",
        dn_name,
        {
            "Delivery Note": {
                "doctype": "Sales Invoice",
                "field_map": {
                    "name": "delivery_note",   # link header if you use a custom link
                    "customer": "customer",
                    "company": "company"
                },
            },
            "Delivery Note Item": {
                "doctype": "Sales Invoice Item",
                "field_map": {
                    "name": "dn_detail",        # ✅ important for linkage
                    "parent": "delivery_note",  # ✅ link back to DN
                    "item_code": "item_code",
                    "item_name": "item_name",
                    "description": "description",
                    "qty": "qty",
                    "stock_uom": "stock_uom",
                    "uom": "uom",
                    "rate": "rate",
                    "amount": "amount"
                }
            },
        },
        postprocess=set_missing_values
    )

    # ❗ do NOT insert → just return for manual editing
    return si