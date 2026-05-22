import frappe

from qcmc_logic.utils import get_user_allowed_warehouses


SKIP_DOCTYPES = {
    "Warehouse Access",
    "Allowed Warehouse",
    "Cost Center Warehouse Mapping",
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


def validate_warehouse_access(doc, method=None):
    if frappe.session.user == "Administrator" or doc.doctype in SKIP_DOCTYPES:
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
            warehouse = doc.get(df.fieldname)
            if warehouse:
                yield (
                    df.fieldname,
                    warehouse,
                    df.fieldname in SOURCE_WAREHOUSE_FIELDS,
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
                warehouse = row.get(child_df.fieldname)
                if warehouse:
                    yield (
                        child_df.fieldname,
                        warehouse,
                        child_df.fieldname in SOURCE_WAREHOUSE_FIELDS,
                    )
