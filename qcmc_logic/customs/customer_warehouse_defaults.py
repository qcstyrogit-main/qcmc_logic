import frappe


CUSTOMER_WAREHOUSE_DEFAULT_DOCTYPE = "Customer Company Warehouse Default"
CUSTOMER_WAREHOUSE_DEFAULT_FIELD = "custom_company_warehouse_defaults"

SUPPORTED_CUSTOMER_WAREHOUSE_DOCTYPES = {
    "Delivery Note",
    "POS Invoice",
    "Sales Invoice",
    "Sales Order",
}


@frappe.whitelist()
def get_customer_company_default_warehouse(customer=None, company=None):
    if not customer or not company:
        return None

    if not frappe.db.table_exists(CUSTOMER_WAREHOUSE_DEFAULT_DOCTYPE):
        return None

    return frappe.db.get_value(
        CUSTOMER_WAREHOUSE_DEFAULT_DOCTYPE,
        {
            "parenttype": "Customer",
            "parentfield": CUSTOMER_WAREHOUSE_DEFAULT_FIELD,
            "parent": customer,
            "company": company,
        },
        "warehouse",
        order_by="idx asc",
    )


def apply_customer_company_default_warehouse(doc, method=None):
    if doc.doctype not in SUPPORTED_CUSTOMER_WAREHOUSE_DOCTYPES:
        return
    if not doc.get("customer") or not doc.get("company"):
        return

    warehouse = get_customer_company_default_warehouse(doc.customer, doc.company)
    if not warehouse:
        return

    if _has_field(doc.doctype, "set_warehouse") and not doc.get("set_warehouse"):
        doc.set_warehouse = warehouse

    for row in doc.get("items") or []:
        if _has_field(row.doctype, "warehouse") and not row.get("warehouse"):
            row.warehouse = warehouse


def validate_customer_company_warehouse_defaults(doc, method=None):
    if doc.doctype != "Customer" or not _has_field(
        "Customer",
        CUSTOMER_WAREHOUSE_DEFAULT_FIELD,
    ):
        return

    seen_companies = set()
    for row in doc.get(CUSTOMER_WAREHOUSE_DEFAULT_FIELD) or []:
        if not row.company:
            continue

        if row.company in seen_companies:
            frappe.throw(
                "Only one Company Warehouse Default is allowed per company."
            )
        seen_companies.add(row.company)

        if not row.warehouse:
            continue

        warehouse_values = frappe.db.get_value(
            "Warehouse",
            row.warehouse,
            ["company", "is_group"],
            as_dict=True,
        )
        if warehouse_values and warehouse_values.is_group:
            frappe.throw(
                "{0} cannot be a group warehouse.".format(frappe.bold(row.warehouse))
            )

        warehouse_company = warehouse_values and warehouse_values.company
        if warehouse_company and warehouse_company != row.company:
            frappe.throw(
                "{0} must belong to {1}.".format(
                    frappe.bold(row.warehouse),
                    frappe.bold(row.company),
                )
            )


def _has_field(doctype, fieldname):
    try:
        return frappe.get_meta(doctype).has_field(fieldname)
    except Exception:
        return False
