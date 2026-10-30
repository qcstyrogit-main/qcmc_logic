"""Creation activity by owner across persisted, top-level submittable documents."""

import frappe
from frappe import _
from frappe.query_builder.functions import Count, Max
from frappe.utils import add_days, getdate


def execute(filters=None):
    frappe.only_for("System Manager")
    filters = frappe._dict(filters or {})
    created_from = getdate(filters.created_from) if filters.created_from else None
    created_to = getdate(filters.created_to) if filters.created_to else None
    if created_from and created_to and created_from > created_to:
        frappe.throw(_("Created From must be on or before Created To."))

    users = frappe.get_all(
        "User", fields=["name", "full_name", "enabled", "user_type", "role_profile_name"],
        order_by="name",
    )
    rows = {}
    profiles = {}
    for assignment in frappe.get_all(
        "User Role Profile", filters={"parenttype": "User", "parentfield": "role_profiles"},
        fields=["parent", "role_profile"],
    ):
        if assignment.role_profile:
            profiles.setdefault(assignment.parent, set()).add(assignment.role_profile)
    for user in users:
        assigned = profiles.get(user.name, set()).copy()
        if user.role_profile_name:
            assigned.add(user.role_profile_name)
        rows[user.name] = dict(
            user=user.name, full_name=user.full_name, enabled=user.enabled,
            user_type=user.user_type, role_profiles=", ".join(sorted(assigned)),
            draft=0, submitted=0, cancelled=0, total_transactions=0,
            transaction_types=0, last_transaction_creation=None,
        )

    doctypes = frappe.get_all(
        "DocType", filters={"is_submittable": 1, "istable": 0, "issingle": 0, "is_virtual": 0},
        pluck="name",
    )
    for doctype in doctypes:
        table = frappe.qb.DocType(doctype)
        query = frappe.qb.from_(table).select(
            table.owner, table.docstatus, Count(table.name).as_("count"),
            Max(table.creation).as_("last_creation"),
        ).groupby(table.owner, table.docstatus)
        if created_from:
            query = query.where(table.creation >= created_from)
        if created_to:
            query = query.where(table.creation < add_days(created_to, 1))
        owners = set()
        for activity in query.run(as_dict=True):
            row = rows.get(activity.owner)
            if row is None:
                continue
            status = {0: "draft", 1: "submitted", 2: "cancelled"}[activity.docstatus]
            row[status] += activity.count
            row["total_transactions"] += activity.count
            owners.add(activity.owner)
            last = row["last_transaction_creation"]
            if last is None or activity.last_creation > last:
                row["last_transaction_creation"] = activity.last_creation
        for owner in owners:
            rows[owner]["transaction_types"] += 1
    return get_columns(), list(rows.values())


def get_columns():
    return [
        {"label": _(label), "fieldname": field, "fieldtype": kind, "width": width,
         **({"options": "User"} if field == "user" else {})}
        for label, field, kind, width in [
            ("User", "user", "Link", 220),
            ("Full Name", "full_name", "Data", 180),
            ("Enabled", "enabled", "Check", 80),
            ("User Type", "user_type", "Data", 130),
            ("Role Profiles", "role_profiles", "Data", 220),
            ("Draft", "draft", "Int", 90),
            ("Submitted", "submitted", "Int", 100),
            ("Cancelled", "cancelled", "Int", 100),
            ("Total Transactions", "total_transactions", "Int", 150),
            ("Transaction Types", "transaction_types", "Int", 140),
            ("Last Transaction Creation", "last_transaction_creation", "Datetime", 190),
        ]
    ]
