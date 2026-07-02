import frappe
from frappe.utils import time_diff_in_seconds


def validate(doc, method=None):
    _calc_duration(doc)
    _fetch_reason_fields(doc)


def _calc_duration(doc):
    if not (doc.from_time and doc.to_time):
        return
    diff = time_diff_in_seconds(doc.to_time, doc.from_time)
    if diff <= 0:
        frappe.throw("To Time must be after From Time.", title="Invalid Time Range")
    doc.duration_minutes = round(diff / 60, 2)


def _fetch_reason_fields(doc):
    if not doc.downtime_reason:
        return
    dr = frappe.db.get_value(
        "Downtime Reason",
        doc.downtime_reason,
        ["category", "subcategory"],
        as_dict=True,
    )
    if dr:
        doc.category = dr.category
        doc.subcategory = dr.subcategory
