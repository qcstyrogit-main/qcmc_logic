import frappe


SKIP_DOCTYPES = {
    "Warehouse Access",
    "Allowed Warehouse",
    "Cost Center Warehouse Mapping",
    "Error Log",
    "Stock Settings",
    "Warehouse Transfer",
    "Warehouse",
    "User Permission",
}

SOURCE_WAREHOUSE_FIELDS = {
    "from_warehouse",
    "set_from_warehouse",
    "source_warehouse",
    "s_warehouse",
}

TARGET_WAREHOUSE_FIELDS = {
    "to_warehouse",
    "set_warehouse",
    "target_warehouse",
    "t_warehouse",
    "warehouse",
}

STOCK_ENTRY_SOURCE_PURPOSES = {
    "Material Issue",
    "Material Transfer",
    "Send to Subcontractor",
    "Material Transfer for Manufacture",
    "Material Consumption for Manufacture",
    "Return Raw Material to Customer",
    "Subcontracting Delivery",
    "Manufacture",
    "Repack",
    "Disassemble",
}

STOCK_ENTRY_TARGET_PURPOSES = {
    "Material Receipt",
    "Material Transfer",
    "Send to Subcontractor",
    "Material Transfer for Manufacture",
    "Receive from Customer",
    "Subcontracting Return",
    "Manufacture",
    "Repack",
    "Disassemble",
}

STOCK_ENTRY_WAREHOUSE_TYPE_EXEMPT_PURPOSES = {
    "Material Transfer for Manufacture",
    "Material Consumption for Manufacture",
}

MATERIAL_REQUEST_SOURCE_FIELDS = {
    "from_warehouse",
    "set_from_warehouse",
}

MATERIAL_REQUEST_TARGET_FIELDS = {
    "warehouse",
    "set_warehouse",
}


def validate_warehouse_access(doc, method=None):
    if (
        frappe.session.user == "Administrator"
        or doc.doctype in SKIP_DOCTYPES
    ):
        return

    from qcmc_logic.utils import (
        get_user_allowed_warehouses,
        is_global_warehouse_access_enabled,
    )

    if not is_global_warehouse_access_enabled():
        return

    allowed = set(get_user_allowed_warehouses(frappe.session.user))
    transact_allowed = set(
        get_user_allowed_warehouses(frappe.session.user, require_transact=True)
    )

    for fieldname, warehouse, require_transact in _iter_warehouse_values(doc):
        valid_warehouses = transact_allowed if require_transact else allowed
        if warehouse not in valid_warehouses:
            frappe.throw(
                "{0} is not allowed for {1}.".format(
                    frappe.bold(warehouse),
                    frappe.unscrub(fieldname),
                )
            )


def validate_warehouse_type_restriction(doc, method=None):
    if doc.doctype not in {"Material Request", "Stock Entry"}:
        return

    from qcmc_logic.utils import is_warehouse_type_restriction_enabled

    if not is_warehouse_type_restriction_enabled():
        return

    if doc.doctype == "Material Request":
        if doc.get("material_request_type") != "Material Transfer":
            return

        for source_warehouse, target_warehouse in _iter_material_request_warehouse_pairs(doc):
            _validate_same_warehouse_type(source_warehouse, target_warehouse, doc.doctype)

    if doc.doctype == "Stock Entry":
        if doc.get("purpose") in STOCK_ENTRY_WAREHOUSE_TYPE_EXEMPT_PURPOSES:
            return

        for source_warehouse, target_warehouse in _iter_stock_entry_warehouse_pairs(doc):
            _validate_same_warehouse_type(source_warehouse, target_warehouse, doc.doctype)


def _iter_warehouse_values(doc):
    for df in doc.meta.fields:
        if df.fieldtype == "Link" and df.options == "Warehouse":
            if _is_material_request_source_field(doc, df.fieldname):
                continue

            warehouse = doc.get(df.fieldname)
            if warehouse:
                yield (
                    df.fieldname,
                    warehouse,
                    _requires_transact(doc, df.fieldname),
                )

        if df.fieldtype != "Table" or not df.options:
            continue

        child_meta = frappe.get_meta(df.options)
        warehouse_fields = [
            child_df
            for child_df in child_meta.fields
            if child_df.fieldtype == "Link" and child_df.options == "Warehouse"
        ]
        if not warehouse_fields:
            continue

        for row in doc.get(df.fieldname) or []:
            for child_df in warehouse_fields:
                if _is_material_request_source_field(doc, child_df.fieldname):
                    continue

                warehouse = row.get(child_df.fieldname)
                if warehouse:
                    yield (
                        child_df.fieldname,
                        warehouse,
                        _requires_transact(doc, child_df.fieldname),
                    )


def _is_material_transfer_request(doc):
    return (
        doc.doctype == "Material Request"
        and doc.get("material_request_type") == "Material Transfer"
    )


def _requires_transact(doc, fieldname):
    if _is_material_request_source_field(doc, fieldname):
        return False

    if doc.doctype == "Stock Entry":
        return _stock_entry_field_requires_transact(doc, fieldname)

    if doc.doctype == "Material Request":
        return fieldname in MATERIAL_REQUEST_TARGET_FIELDS

    if doc.doctype in {"Delivery Note", "Sales Invoice", "Pick List"}:
        return fieldname == "warehouse"

    if doc.doctype in {"Purchase Invoice", "Purchase Order", "Purchase Receipt"}:
        return fieldname in {"set_warehouse", "warehouse"}

    if doc.doctype == "Stock Reconciliation":
        return fieldname == "warehouse"

    return fieldname in SOURCE_WAREHOUSE_FIELDS or fieldname in TARGET_WAREHOUSE_FIELDS


def _is_material_request_source_field(doc, fieldname):
    return _is_material_transfer_request(doc) and fieldname in MATERIAL_REQUEST_SOURCE_FIELDS


def _stock_entry_field_requires_transact(doc, fieldname):
    purpose = doc.get("purpose")

    if fieldname in {"from_warehouse", "s_warehouse"}:
        return purpose in STOCK_ENTRY_SOURCE_PURPOSES

    if fieldname in {"to_warehouse", "t_warehouse"}:
        return purpose in STOCK_ENTRY_TARGET_PURPOSES

    return False


def _iter_material_request_warehouse_pairs(doc):
    parent_source = doc.get("set_from_warehouse")
    parent_target = doc.get("set_warehouse")
    if parent_source and parent_target:
        yield parent_source, parent_target

    for row in doc.get("items") or []:
        source_warehouse = row.get("from_warehouse") or parent_source
        target_warehouse = row.get("warehouse") or parent_target
        if source_warehouse and target_warehouse:
            yield source_warehouse, target_warehouse


def _iter_stock_entry_warehouse_pairs(doc):
    parent_source = doc.get("from_warehouse")
    parent_target = doc.get("to_warehouse")
    if parent_source and parent_target:
        yield parent_source, parent_target

    for row in doc.get("items") or []:
        source_warehouse = row.get("s_warehouse") or parent_source
        target_warehouse = row.get("t_warehouse") or parent_target
        if source_warehouse and target_warehouse:
            yield source_warehouse, target_warehouse


def _validate_same_warehouse_type(source_warehouse, target_warehouse, doctype):
    if source_warehouse == target_warehouse:
        return

    source_type = frappe.db.get_value("Warehouse", source_warehouse, "warehouse_type")
    target_type = frappe.db.get_value("Warehouse", target_warehouse, "warehouse_type")

    if source_type != target_type:
        frappe.throw(
            "{0} requires source and target warehouses with the same warehouse type. {1} is {2}; {3} is {4}.".format(
                doctype,
                frappe.bold(source_warehouse),
                frappe.bold(source_type or "No Warehouse Type"),
                frappe.bold(target_warehouse),
                frappe.bold(target_type or "No Warehouse Type"),
            )
        )
