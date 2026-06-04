import frappe

from qcmc_logic.utils import (
    get_user_allowed_warehouses,
    is_global_warehouse_access_enabled,
)


WAREHOUSE_TRANSACTION_DOCTYPES = {
    "Delivery Note": {
        "children": {"Delivery Note Item": ["warehouse"]},
    },
    "Material Request": {
        "fields": ["set_from_warehouse", "set_warehouse"],
        "children": {"Material Request Item": ["from_warehouse", "warehouse"]},
    },
    "Pick List": {
        "children": {"Pick List Item": ["warehouse"], "Pick List Item Location": ["warehouse"]},
    },
    "Purchase Invoice": {
        "children": {"Purchase Invoice Item": ["warehouse"]},
    },
    "Purchase Order": {
        "fields": ["set_warehouse"],
        "children": {"Purchase Order Item": ["warehouse"]},
    },
    "Purchase Receipt": {
        "fields": ["set_warehouse"],
        "children": {
            "Purchase Receipt Item": ["warehouse"],
            "Purchase Receipt Item Supplied": ["reserve_warehouse"],
        },
    },
    "Sales Invoice": {
        "children": {"Sales Invoice Item": ["warehouse"]},
    },
    "Stock Entry": {
        "fields": ["from_warehouse", "to_warehouse"],
        "children": {"Stock Entry Detail": ["s_warehouse", "t_warehouse"]},
    },
    "Stock Reconciliation": {
        "children": {"Stock Reconciliation Item": ["warehouse"]},
    },
    "Warehouse Transfer": {
        "fields": ["source_warehouse", "target_warehouse"],
    },
    "Work Order": {
        "fields": ["source_warehouse", "wip_warehouse", "fg_warehouse", "scrap_warehouse"],
        "children": {"Work Order Item": ["source_warehouse"]},
    },
}


def _warehouse_access_applies(user):
    return user != "Administrator" and is_global_warehouse_access_enabled()


def _sql_list(values):
    return ", ".join(frappe.db.escape(value) for value in values)


def _doctype_has_field(doctype, fieldname):
    return frappe.get_meta(doctype).has_field(fieldname)


def _get_existing_fields(doctype, fieldnames):
    return [fieldname for fieldname in fieldnames if _doctype_has_field(doctype, fieldname)]


def _get_transaction_config(doctype):
    config = WAREHOUSE_TRANSACTION_DOCTYPES.get(doctype) or {}
    fields = _get_existing_fields(doctype, config.get("fields", []))
    children = {}

    for child_doctype, fieldnames in (config.get("children") or {}).items():
        if not frappe.db.table_exists(child_doctype):
            continue

        existing_fields = _get_existing_fields(child_doctype, fieldnames)
        if existing_fields:
            children[child_doctype] = existing_fields

    return {"fields": fields, "children": children}


def _warehouse_transaction_permission_query(doctype, user):
    if not _warehouse_access_applies(user):
        return ""

    allowed_warehouses = get_user_allowed_warehouses(user, require_transact=True)
    if not allowed_warehouses:
        return "1=0"

    config = _get_transaction_config(doctype)
    if not config["fields"] and not config["children"]:
        return ""

    table = f"`tab{doctype}`"
    allowed_sql = _sql_list(allowed_warehouses)
    has_allowed_conditions = []
    no_disallowed_conditions = []

    for fieldname in config["fields"]:
        field = f"{table}.`{fieldname}`"
        has_allowed_conditions.append(f"{field} IN ({allowed_sql})")
        no_disallowed_conditions.append(
            f"(IFNULL({field}, '') = '' OR {field} IN ({allowed_sql}))"
        )

    for child_doctype, fieldnames in config["children"].items():
        child_table = f"`tab{child_doctype}`"
        for fieldname in fieldnames:
            child_field = f"{child_table}.`{fieldname}`"
            parent_match = f"{child_table}.parent = {table}.name"
            has_allowed_conditions.append(
                "EXISTS ("
                f"SELECT 1 FROM {child_table} "
                f"WHERE {parent_match} AND {child_field} IN ({allowed_sql})"
                ")"
            )
            no_disallowed_conditions.append(
                "NOT EXISTS ("
                f"SELECT 1 FROM {child_table} "
                f"WHERE {parent_match} "
                f"AND IFNULL({child_field}, '') != '' "
                f"AND {child_field} NOT IN ({allowed_sql})"
                ")"
            )

    if not has_allowed_conditions:
        return "1=0"

    return "({0}) AND ({1})".format(
        " OR ".join(has_allowed_conditions),
        " AND ".join(no_disallowed_conditions),
    )


def warehouse_transaction_permission_query(user):
    doctype = frappe.local.form_dict.get("doctype")
    if not doctype:
        return ""

    return _warehouse_transaction_permission_query(doctype, user)


def delivery_note_permission_query(user):
    return _warehouse_transaction_permission_query("Delivery Note", user)


def material_request_permission_query(user):
    return _warehouse_transaction_permission_query("Material Request", user)


def pick_list_permission_query(user):
    return _warehouse_transaction_permission_query("Pick List", user)


def purchase_invoice_permission_query(user):
    return _warehouse_transaction_permission_query("Purchase Invoice", user)


def purchase_order_permission_query(user):
    return _warehouse_transaction_permission_query("Purchase Order", user)


def purchase_receipt_permission_query(user):
    return _warehouse_transaction_permission_query("Purchase Receipt", user)


def sales_invoice_permission_query(user):
    return _warehouse_transaction_permission_query("Sales Invoice", user)


def stock_entry_permission_query(user):
    return _warehouse_transaction_permission_query("Stock Entry", user)


def stock_reconciliation_permission_query(user):
    return _warehouse_transaction_permission_query("Stock Reconciliation", user)


def work_order_permission_query(user):
    return _warehouse_transaction_permission_query("Work Order", user)


def _iter_doc_warehouse_values(doc):
    config = _get_transaction_config(doc.doctype)

    for fieldname in config["fields"]:
        warehouse = doc.get(fieldname)
        if warehouse:
            yield warehouse

    for child_doctype, fieldnames in config["children"].items():
        table_fieldnames = [
            df.fieldname
            for df in doc.meta.fields
            if df.fieldtype == "Table" and df.options == child_doctype
        ]

        for table_fieldname in table_fieldnames:
            for row in doc.get(table_fieldname) or []:
                for fieldname in fieldnames:
                    warehouse = row.get(fieldname)
                    if warehouse:
                        yield warehouse


def warehouse_transaction_has_permission(doc, ptype=None, user=None):
    if not user:
        user = frappe.session.user
    if not _warehouse_access_applies(user):
        return True
    if ptype == "create":
        return True
    if not doc:
        return None

    allowed_warehouses = set(get_user_allowed_warehouses(user, require_transact=True))
    if not allowed_warehouses:
        return False

    warehouses = set(_iter_doc_warehouse_values(doc))
    if not warehouses:
        return True

    return warehouses.issubset(allowed_warehouses)


def _get_warehouse_access_values(user, require_transact=False):
    if not user:
        user = frappe.session.user

    access_names = frappe.get_all(
        "Warehouse Access",
        filters={"user": user},
        pluck="name",
    )
    if not access_names:
        return []

    filters = {"parent": ["in", access_names]}
    if require_transact:
        filters["allow_transact"] = 1

    return frappe.get_all(
        "Allowed Warehouse",
        filters=filters,
        pluck="warehouse",
    )


def warehouse_transfer_permission_query(user):
    if not _warehouse_access_applies(user):
        return ""

    return _warehouse_transaction_permission_query("Warehouse Transfer", user)


def warehouse_transfer_has_permission(doc, ptype=None, user=None):
    return warehouse_transaction_has_permission(doc, ptype=ptype, user=user)


def appraisal_permission_query(user):
    roles = frappe.get_roles(user)

    # Only restrict supervisors, never managers/admins
    if "Appraisal User" not in roles or "Appraisal Manager" in roles:
        return ""

    assignment = frappe.db.get_value(
        "Appraisal Section Assignment",
        {"user": user},
        "name"
    )

    if not assignment:
        return "1=0"

    sections = frappe.get_all(
        "Appraisal Section Assignment Detail",
        filters={"parent": assignment},
        pluck="appraisal_section"
    )

    if not sections:
        return "1=0"

    sections_sql = ", ".join(frappe.db.escape(s) for s in sections)

    return f"`tabAppraisal`.custom_appraisal_section IN ({sections_sql})"
