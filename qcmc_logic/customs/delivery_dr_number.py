"""Company-scoped DR number validation shared by form, workbench and invoice mappers."""
import frappe
from frappe import _
from frappe.utils import escape_html


def normalize(value):
    return str(value or "").strip()


def find_duplicate(company, number, exclude=None, lock=False):
    number = normalize(number)
    if not company or not number:
        return None
    # A locking read observes the latest committed values even under repeatable read.
    sql = """
        SELECT name FROM {0}tabDelivery Note{0}
        WHERE company = %s AND docstatus IN (0, 1)
        AND LOWER(TRIM(custom_dr_number)) = LOWER(%s) AND name != %s
        LIMIT 1
    """.format(chr(96))
    if lock:
        sql += " FOR UPDATE"
    rows = frappe.db.sql(sql, (company, number, exclude or ""))
    return rows[0][0] if rows else None


def validate_dr_number(doc, method=None):
    if int(doc.docstatus) == 2:
        return
    number = normalize(doc.get("custom_dr_number"))
    doc.custom_dr_number = number
    if not number:
        return
    if not doc.company:
        frappe.throw(_("Select the company before assigning a DR Number."))
    # The company row is a transaction-scoped mutex shared by all normal DN writes.
    # It remains locked through commit, unlike a cache lock released before commit.
    frappe.db.sql("SELECT name FROM {0}tabCompany{0} WHERE name = %s FOR UPDATE".format(chr(96)), (doc.company,))
    duplicate = find_duplicate(doc.company, number, doc.name, lock=True)
    if duplicate:
        if frappe.has_permission("Delivery Note", "read", doc=duplicate):
            frappe.throw(_("DR Number {0} is already used by Delivery Note {1} in this company.").format(
                frappe.bold(escape_html(number)), frappe.bold(escape_html(duplicate))))
        frappe.throw(_("DR Number {0} is already used by another active Delivery Note in this company.").format(
            frappe.bold(escape_html(number))))


def require_dr_number(doc):
    if int(doc.docstatus) == 2 or not normalize(doc.get("custom_dr_number")):
        frappe.throw(_("Assign a DR Number to the active Delivery Note before creating its Sales Invoice."))
    duplicate = find_duplicate(doc.company, doc.custom_dr_number, doc.name)
    if duplicate:
        frappe.throw(_("Resolve the duplicate DR Number before creating the Sales Invoice."))


@frappe.whitelist()
def check_dr_number(company, dr_number, delivery_note=None):
    if delivery_note:
        doc = frappe.get_doc("Delivery Note", delivery_note)
        doc.check_permission("read")
    elif not frappe.has_permission("Delivery Note", "create"):
        frappe.throw(_("Delivery Note access is required."), frappe.PermissionError)
    if not frappe.has_permission("Company", "read", doc=company):
        frappe.throw(_("Company access is required."), frappe.PermissionError)
    duplicate = find_duplicate(company, dr_number, delivery_note)
    return {"duplicate": bool(duplicate),
            "delivery_note": duplicate if duplicate and frappe.has_permission("Delivery Note", "read", doc=duplicate) else None}


def validate_new_invoice(doc, method=None):
    # Direct creation via import or API must follow the same rule as both DN mappers.
    names = {item.delivery_note for item in doc.items if item.get("delivery_note")}
    for item in doc.items:
        if item.get("dn_detail"):
            parent = frappe.db.get_value("Delivery Note Item", item.dn_detail, "parent")
            if parent:
                names.add(parent)
    for name in sorted(names):
        require_dr_number(frappe.get_doc("Delivery Note", name))
