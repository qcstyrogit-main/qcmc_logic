# import frappe

# def get_po_print_format(doc, print_format=None):
#     series = (doc.naming_series or "").strip()

#     if series in [".Q.X.#", ".M.X.#", ".MCY.#"]:
#         return "PO_APEX"
#     return "PO"


import frappe

def get_po_print_format(doctype, name=None, print_format=None, **kwargs):
    # Only apply logic for Purchase Order
    if doctype == "Purchase Order" and name:
        doc = frappe.get_doc(doctype, name)
        series = (doc.naming_series or "").strip()
        if any(x in series for x in [".Q.X.#", ".M.X.#", ".MCY.#"]):
            return "PO_APEX"
        return "PO"

    # fallback for other doctypes
    return print_format or None
