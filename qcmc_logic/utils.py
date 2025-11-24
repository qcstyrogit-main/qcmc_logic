import frappe

@frappe.whitelist()
def get_user_allowed_warehouses(user=None):
    """Fetch all allowed warehouses from the custom Warehouse Access doctype for the given user."""
    if not user:
        user = frappe.session.user

    # Check if user has a Warehouse Access record
    access_doc = frappe.get_all(
        "Warehouse Access",
        filters={"user": user},
        fields=["name"]
    )

    if not access_doc:
        return []  # no warehouses allowed

    # There should normally be only one Warehouse Access doc per user, but we handle multiple just in case
    allowed = frappe.get_all(
        "Allowed Warehouse",
        filters={"parent": ["in", [d.name for d in access_doc]]},
        pluck="warehouse"
    )

    return allowed

@frappe.whitelist()
def check_warehouse_access(user, warehouse):
    """
    Check if a given user has access to the specified warehouse
    based on the custom 'Warehouse Access' doctype.
    """
    allowed = frappe.db.exists(
        "Allowed Warehouse",
        {
            "parenttype": "Warehouse Access",
            "parentfield": "allowed_warehouses",
            "parent": ["in", frappe.get_all(
                "Warehouse Access",
                filters={"user": user},
                pluck="name"
            )],
            "warehouse": warehouse
        }
    )
    return True if allowed else False