import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def execute():
    doctypes = ("Warehouse Transfer", "Warehouse Transfer Details")

    for doctype in doctypes:
        ensure_dimension_layout_fields(doctype)
        create_dimensions(doctype)
        frappe.clear_cache(doctype=doctype)


def ensure_dimension_layout_fields(doctype):
    if not frappe.db.exists("DocType", doctype):
        return

    if not frappe.get_meta(doctype, cached=False).has_field("accounting_dimensions_section"):
        create_custom_field(
            doctype,
            {
                "fieldname": "accounting_dimensions_section",
                "label": "Accounting Dimensions",
                "fieldtype": "Section Break",
                "insert_after": get_insert_after_field(doctype),
            },
            ignore_validate=True,
        )

    if not frappe.get_meta(doctype, cached=False).has_field("dimension_col_break"):
        create_custom_field(
            doctype,
            {
                "fieldname": "dimension_col_break",
                "fieldtype": "Column Break",
                "insert_after": "accounting_dimensions_section",
            },
            ignore_validate=True,
        )


def get_insert_after_field(doctype):
    preferred_fields = {
        "Warehouse Transfer": "transfer_items",
        "Warehouse Transfer Details": "reference_doc",
    }
    preferred = preferred_fields.get(doctype)
    meta = frappe.get_meta(doctype, cached=False)

    if preferred and meta.has_field(preferred):
        return preferred

    fields = [field.fieldname for field in meta.get("fields") if field.fieldname]
    return fields[-1] if fields else None


def create_dimensions(doctype):
    accounting_dimensions = frappe.get_all(
        "Accounting Dimension",
        filters={"disabled": 0},
        fields=["fieldname", "label", "document_type"],
    )

    for dimension in accounting_dimensions:
        if frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": dimension.fieldname}):
            continue

        create_custom_field(
            doctype,
            {
                "fieldname": dimension.fieldname,
                "label": dimension.label,
                "fieldtype": "Link",
                "options": dimension.document_type,
                "insert_after": "accounting_dimensions_section",
                "allow_on_submit": 1,
            },
            ignore_validate=True,
        )
