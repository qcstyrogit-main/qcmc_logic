"""Site-wide creation counts for the administrative transaction dashboard."""

from datetime import date, timedelta

import frappe
from frappe import _
from frappe.query_builder.functions import Count


@frappe.whitelist()
def get_data(date_from=None, date_to=None):
    frappe.only_for("System Manager")
    try:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
        stop = end + timedelta(days=1)
    except (TypeError, ValueError, OverflowError):
        frappe.throw(_("Select valid Date From and Date To values."))
    if start > end:
        frappe.throw(_("Date From must be on or before Date To."))

    doctype_records = frappe.get_all(
        "DocType",
        filters={"is_submittable": 1, "istable": 0, "issingle": 0, "is_virtual": 0},
        fields=["name", "module"], order_by="name",
    )
    doctypes = [record.name for record in doctype_records]
    doctype_modules = {record.name: record.module for record in doctype_records}
    employees = {}
    for employee in frappe.get_all(
        "Employee", filters={"user_id": ["is", "set"]},
        fields=["user_id", "employee_name"], order_by="status asc, name asc",
    ):
        if employee.employee_name:
            employees.setdefault(employee.user_id, employee.employee_name)
    rows = {}
    for user in frappe.get_all("User", fields=["name", "full_name"], order_by="full_name, name"):
        rows[user.name] = {
            "user": user.name,
            "employee_name": employees.get(user.name) or user.full_name or user.name,
            "counts": dict.fromkeys(doctypes, 0),
            "total": 0,
        }
    totals = dict.fromkeys(doctypes, 0)
    for doctype in doctypes:
        table = frappe.qb.DocType(doctype)
        activity = (
            frappe.qb.from_(table)
            .select(table.owner, Count(table.name).as_("count"))
            .where(table.creation >= start)
            .where(table.creation < stop)
            .groupby(table.owner)
        ).run(as_dict=True)
        for entry in activity:
            row = rows.get(entry.owner)
            if row is None:
                row = rows[entry.owner] = {
                    "user": entry.owner,
                    "employee_name": entry.owner or _("Unknown User"),
                    "counts": dict.fromkeys(doctypes, 0),
                    "total": 0,
                }
            row["counts"][doctype] = entry.count
            row["total"] += entry.count
            totals[doctype] += entry.count
    ordered_rows = sorted(rows.values(), key=lambda row: (row["employee_name"].casefold(), row["user"]))
    total = sum(totals.values())
    return {
        "doctypes": doctypes,
        "doctype_modules": doctype_modules,
        "rows": ordered_rows,
        "totals": {"counts": totals, "total": total},
        "summary": {
            "documents": total,
            "active_users": sum(bool(row["total"]) for row in ordered_rows),
            "active_doctypes": sum(bool(value) for value in totals.values()),
        },
    }
