import frappe

from qcmc_logic.utils import (
    get_user_allowed_warehouses,
    is_global_warehouse_access_enabled,
)


SKIP_DOCTYPES = {
    "Warehouse Access",
    "Allowed Warehouse",
    "Cost Center Warehouse Mapping",
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
        or not is_global_warehouse_access_enabled()
    ):
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

    if _is_material_transfer_request(doc):
        if fieldname in MATERIAL_REQUEST_TARGET_FIELDS:
            return True

    return True


def _is_material_request_source_field(doc, fieldname):
    return _is_material_transfer_request(doc) and fieldname in MATERIAL_REQUEST_SOURCE_FIELDS
