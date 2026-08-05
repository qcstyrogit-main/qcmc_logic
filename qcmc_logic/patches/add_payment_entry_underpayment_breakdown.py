import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


UNDERPAYMENT_TYPES = (
    ("RETURNS", "RETURNS"),
    ("PRICE DIFF", "PRICE DIFFERENCE"),
    ("SHORT PYMT", "SHORT PAYMENT"),
    ("ANNIV SUPPORT", "ANNIVERSARY SUPPORT"),
    ("OPENING SUPPORT", "OPENING SUPPORT"),
    ("LISTING FEE", "LISTING FEE"),
    ("DC ALLOW", "DC ALLOWANCE"),
    ("CROSS DOCK FEE", "CROSS DOCK FEE"),
    ("MDSR SALARY", "MERCHANDISER SALARY"),
    ("MDSR PENALTY", "MERCHANDISER PENALTY"),
    ("LACKING DEL", "LACKING DELIVERY"),
    ("EWT NO CERT", "EWT NO CERTFICATE"),
    ("MISC", "MISCELLANEOUS (barcode/shelf tag/roll twine/freight/vendor/porta/whse fee)"),
    ("LATE DEL", "PENALTY FOR LATE DELIVERY"),
    ("XMAS SUPPORT", "CHRISTMAS SUPPORT"),
    ("SALES DISC", "SALES DISCOUNT"),
    ("BANK CHARGE", "BANK CHARGE"),
    ("LOST SI", "PENALTY FOR LOST SI"),
    ("ACCT", "ACCOUNTABILITY"),
)


def execute():
    create_underpayment_type_doctype()
    create_payment_entry_underpayment_doctype()
    add_payment_entry_underpayment_remarks()
    add_payment_entry_underpayment_table()
    seed_underpayment_types()
    frappe.clear_cache(doctype="Payment Entry")


def create_underpayment_type_doctype():
    if frappe.db.exists("DocType", "Underpayment Type"):
        return

    doc = frappe.get_doc(
        {
            "doctype": "DocType",
            "name": "Underpayment Type",
            "module": "QCMC Logics",
            "custom": 1,
            "allow_rename": 0,
            "autoname": "field:underpayment_code",
            "naming_rule": "By fieldname",
            "title_field": "underpayment_description",
            "fields": [
                {
                    "fieldname": "underpayment_code",
                    "fieldtype": "Data",
                    "label": "Underpayment Code",
                    "reqd": 1,
                    "unique": 1,
                    "in_list_view": 1,
                    "in_standard_filter": 1,
                },
                {
                    "fieldname": "underpayment_description",
                    "fieldtype": "Data",
                    "label": "Underpayment Description",
                    "reqd": 1,
                    "in_list_view": 1,
                },
            ],
            "permissions": [_system_manager_permission()],
        }
    )
    doc.insert(ignore_permissions=True)


def create_payment_entry_underpayment_doctype():
    if frappe.db.exists("DocType", "Payment Entry Underpayment"):
        return

    doc = frappe.get_doc(
        {
            "doctype": "DocType",
            "name": "Payment Entry Underpayment",
            "module": "QCMC Logics",
            "custom": 1,
            "istable": 1,
            "editable_grid": 1,
            "fields": [
                {
                    "fieldname": "sales_invoice",
                    "fieldtype": "Link",
                    "label": "Sales Invoice",
                    "options": "Sales Invoice",
                    "reqd": 1,
                    "in_list_view": 1,
                    "in_standard_filter": 1,
                },
                {
                    "fieldname": "underpayment_type",
                    "fieldtype": "Link",
                    "label": "Underpayment Type",
                    "options": "Underpayment Type",
                    "reqd": 1,
                    "in_list_view": 1,
                    "in_standard_filter": 1,
                },
                {
                    "fieldname": "underpayment_description",
                    "fieldtype": "Data",
                    "label": "Description",
                    "fetch_from": "underpayment_type.underpayment_description",
                    "fetch_if_empty": 1,
                    "read_only": 1,
                    "in_list_view": 1,
                },
                {
                    "fieldname": "amount",
                    "fieldtype": "Currency",
                    "label": "Amount",
                    "reqd": 1,
                    "in_list_view": 1,
                },
                {
                    "fieldname": "remarks",
                    "fieldtype": "Small Text",
                    "label": "Remarks",
                    "in_list_view": 1,
                },
            ],
        }
    )
    doc.insert(ignore_permissions=True)
    add_payment_entry_underpayment_remarks()


def add_payment_entry_underpayment_table():
    create_custom_fields(
        {
            "Payment Entry": [
                {
                    "fieldname": "custom_underpayment_section",
                    "fieldtype": "Section Break",
                    "label": "Underpayment Breakdown",
                    "insert_after": "references",
                    "collapsible": 1,
                    "hidden": 1,
                },
                {
                    "fieldname": "custom_underpayment_breakdown",
                    "fieldtype": "Table",
                    "label": "Underpayment Breakdown",
                    "options": "Payment Entry Underpayment",
                    "insert_after": "custom_underpayment_section",
                    "hidden": 1,
                },
            ]
        },
        ignore_validate=True,
    )
    for fieldname in (
        "Payment Entry-custom_underpayment_section",
        "Payment Entry-custom_underpayment_breakdown",
    ):
        if frappe.db.exists("Custom Field", fieldname):
            frappe.db.set_value(
                "Custom Field",
                fieldname,
                {"hidden": 1, "depends_on": None},
                update_modified=False,
            )


def add_payment_entry_underpayment_remarks():
    if not frappe.db.exists("DocType", "Payment Entry Underpayment"):
        return
    field_exists = frappe.db.exists(
        "DocField",
        {"parent": "Payment Entry Underpayment", "fieldname": "remarks"},
    )
    if not field_exists:
        meta = frappe.get_meta("Payment Entry Underpayment")
        field = frappe.get_doc(
            {
                "doctype": "DocField",
                "parent": "Payment Entry Underpayment",
                "parenttype": "DocType",
                "parentfield": "fields",
                "idx": len(meta.fields) + 1,
                "fieldname": "remarks",
                "fieldtype": "Small Text",
                "label": "Remarks",
                "in_list_view": 1,
            }
        )
        field.db_insert()

    if not frappe.db.has_column("Payment Entry Underpayment", "remarks"):
        frappe.db.sql("alter table `tabPayment Entry Underpayment` add column `remarks` text")

    frappe.clear_cache(doctype="Payment Entry Underpayment")


def seed_underpayment_types():
    for code, description in UNDERPAYMENT_TYPES:
        if frappe.db.exists("Underpayment Type", code):
            frappe.db.set_value(
                "Underpayment Type",
                code,
                "underpayment_description",
                description,
                update_modified=False,
            )
            continue

        doc = frappe.get_doc(
            {
                "doctype": "Underpayment Type",
                "underpayment_code": code,
                "underpayment_description": description,
            }
        )
        doc.insert(ignore_permissions=True)


def _system_manager_permission():
    return {
        "role": "System Manager",
        "read": 1,
        "write": 1,
        "create": 1,
        "delete": 1,
        "print": 1,
        "email": 1,
        "report": 1,
        "export": 1,
        "share": 1,
    }
