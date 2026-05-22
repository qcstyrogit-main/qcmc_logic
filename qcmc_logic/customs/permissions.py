import frappe


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
    if user == "Administrator":
        return ""

    target_warehouses = _get_warehouse_access_values(user)
    source_warehouses = _get_warehouse_access_values(user, require_transact=True)
    conditions = []

    if target_warehouses:
        targets = ", ".join(frappe.db.escape(warehouse) for warehouse in target_warehouses)
        conditions.append(f"`tabWarehouse Transfer`.target_warehouse IN ({targets})")

    if source_warehouses:
        sources = ", ".join(frappe.db.escape(warehouse) for warehouse in source_warehouses)
        conditions.append(f"`tabWarehouse Transfer`.source_warehouse IN ({sources})")

    if not conditions:
        return "1=0"

    return "(" + " OR ".join(conditions) + ")"


def warehouse_transfer_has_permission(doc, ptype=None, user=None):
    if not user:
        user = frappe.session.user
    if user == "Administrator":
        return True
    if ptype == "create":
        return True
    if not doc:
        return None

    target_warehouses = set(_get_warehouse_access_values(user))
    if doc.get("target_warehouse") in target_warehouses:
        return True

    source_warehouses = set(_get_warehouse_access_values(user, require_transact=True))
    if doc.get("source_warehouse") in source_warehouses:
        return True

    return False


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
