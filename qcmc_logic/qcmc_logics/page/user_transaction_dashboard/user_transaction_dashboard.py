"""Site-wide creation counts for the administrative transaction dashboard."""

from datetime import date, timedelta
import re

import frappe
from frappe import _
from frappe.query_builder.functions import Count, Date, Extract


@frappe.whitelist()
def get_data(date_from=None, date_to=None):
    frappe.only_for("System Manager")
    start, end, stop = _date_bounds(date_from, date_to)

    doctype_records = _transaction_doctypes()
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
    permission_groups = {}
    for user in frappe.get_all(
        "User", fields=["name", "full_name", "enabled", "user_type"], order_by="full_name, name"
    ):
        monitored = bool(user.enabled and user.user_type == "System User")
        can_create = []
        if monitored and doctypes:
            # DocType-level Create access depends on effective roles. Evaluate
            # each role set once; Administrator has an explicit Frappe bypass.
            role_key = (user.name == "Administrator", tuple(sorted(frappe.get_roles(user.name))))
            if role_key not in permission_groups:
                permission_groups[role_key] = [
                    dt for dt in doctypes
                    if frappe.has_permission(dt, "create", user=user.name)
                ]
            can_create = permission_groups[role_key]
        rows[user.name] = {
            "user": user.name,
            "employee_name": employees.get(user.name) or user.full_name or user.name,
            "enabled": bool(user.enabled),
            "user_type": user.user_type,
            "monitored": monitored,
            "can_create": can_create,
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
                    "enabled": False,
                    "user_type": None,
                    "monitored": False,
                    "can_create": [],
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


def _date_bounds(date_from, date_to):
    try:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
        stop = end + timedelta(days=1)
    except (TypeError, ValueError, OverflowError):
        frappe.throw(_("Select valid Date From and Date To values."))
    if start > end:
        frappe.throw(_("Date From must be on or before Date To."))
    return start, end, stop


def _transaction_doctypes():
    return frappe.get_all(
        "DocType",
        filters={"is_submittable": 1, "istable": 0, "issingle": 0, "is_virtual": 0},
        fields=["name", "module"], order_by="name",
    )


def _json_value(value):
    try:
        return frappe.parse_json(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        frappe.throw(_("Invalid chart settings or selections."))


def _string_selection(value, limit):
    value = _json_value(value)
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > limit or any(
        not isinstance(item, str) or not item or len(item) > 140 for item in value
    ):
        frappe.throw(_("Select valid users and transaction DocTypes."))
    return list(dict.fromkeys(value))


@frappe.whitelist()
def get_creation_trend(date_from=None, date_to=None, doctypes=None, users=None, interval="month"):
    frappe.only_for("System Manager")
    start, end, stop = _date_bounds(date_from, date_to)
    if interval not in ("day", "month"):
        frappe.throw(_("Choose Day or Month for creation trends."))
    months = (end.year - start.year) * 12 + end.month - start.month + 1
    if (interval == "day" and (end - start).days >= 366) or (interval == "month" and months > 120):
        frappe.throw(_("Use up to 366 days for daily trends or 120 months for monthly trends."))
    selected = _string_selection(doctypes, 500)
    owners = _string_selection(users, 1000)
    available = {record.name for record in _transaction_doctypes()}
    if selected is not None and any(dt not in available for dt in selected):
        frappe.throw(_("Choose persisted transaction DocTypes for creation trends."))
    selected = sorted(available) if selected is None else selected
    if interval == "day":
        labels = [(start + timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)]
    else:
        first = start.year * 12 + start.month - 1
        labels = [f"{(first + offset) // 12:04d}-{(first + offset) % 12 + 1:02d}" for offset in range(months)]
    values = dict.fromkeys(labels, 0)
    for dt in selected:
        table = frappe.qb.DocType(dt)
        query = frappe.qb.from_(table).where(table.creation >= start).where(table.creation < stop)
        if owners:
            query = query.where(table.owner.isin(owners))
        if interval == "day":
            bucket = Date(table.creation)
            query = query.select(bucket.as_("bucket"), Count(table.name).as_("count")).groupby(bucket)
        else:
            year, month = Extract("YEAR", table.creation), Extract("MONTH", table.creation)
            query = query.select(year.as_("year"), month.as_("month"), Count(table.name).as_("count")).groupby(year, month)
        for row in query.run(as_dict=True):
            key = str(row.bucket) if interval == "day" else f"{row.year:04d}-{row.month:02d}"
            values[key] += row.count
    return {"labels": labels, "values": list(values.values())}


def validate_chart_layout(charts):
    charts = _json_value(charts)
    if not isinstance(charts, list) or len(charts) > 12:
        frappe.throw(_("A layout can contain up to 12 charts."))
    result, identifiers = [], set()
    for chart in charts:
        if not isinstance(chart, dict):
            frappe.throw(_("Invalid chart configuration."))
        identifier, title = chart.get("id"), chart.get("title")
        kind, metric, group = chart.get("type"), chart.get("metric"), chart.get("group_by")
        top_n = chart.get("top_n")
        if (not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier)
                or identifier in identifiers or not isinstance(title, str) or not title.strip() or len(title) > 120
                or kind not in ("bar", "stacked_bar", "line", "pie", "donut")
                or metric not in ("documents", "using", "not_using", "usage_rate", "adoption")
                or group not in ("module", "doctype", "user", "overall", "day", "month")
                or type(top_n) is not int or top_n not in (0, 5, 10)):
            frappe.throw(_("Choose a valid chart title, type, measure, grouping and Top N."))
        if ((group in ("day", "month") and (metric != "documents" or kind not in ("line", "bar")))
                or (kind == "line" and group not in ("day", "month"))
                or (kind == "stacked_bar" and metric != "adoption")
                or (kind in ("pie", "donut") and not (metric == "documents" or (metric == "adoption" and group == "overall")))):
            frappe.throw(_("Use line charts for creation trends, stacked bars for adoption, and pie/donut for transaction shares or overall adoption."))
        identifiers.add(identifier)
        result.append(dict(id=identifier, title=title.strip(), type=kind, metric=metric, group_by=group, top_n=top_n))
    return result


@frappe.whitelist()
def get_chart_layout():
    frappe.only_for("System Manager")
    from frappe.model.utils.user_settings import get_user_settings

    settings = frappe.parse_json(get_user_settings("Page")) or {}
    charts = settings.get("qcmc_transaction_charts")
    return {"charts": validate_chart_layout(charts) if charts is not None else None}


@frappe.whitelist()
def save_chart_layout(charts):
    frappe.only_for("System Manager")
    from frappe.model.utils.user_settings import update_user_settings

    validated = validate_chart_layout(charts)
    update_user_settings("Page", {"qcmc_transaction_charts": validated})
    return {"charts": validated}
