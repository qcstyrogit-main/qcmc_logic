"""Capture actual posting time only during the final Delivery Note workflow action."""
from datetime import datetime
import frappe
from frappe import _
from frappe.utils import getdate, get_time

ACTION = "Tag To Active"
FLAG = "qcmc_delivery_actual_posting"


def _parse(data):
    if not isinstance(data, dict):
        frappe.throw(_("Confirm the actual posting date and time before tagging this Delivery Note Active."))
    try:
        date = datetime.strptime(str(data.get("posting_date")), "%Y-%m-%d").date()
        time = datetime.strptime(str(data.get("posting_time")), "%H:%M:%S").time()
    except (TypeError, ValueError):
        frappe.throw(_("Enter a valid posting date and time."))
    return date, time


def apply_final_workflow(data, action, standard_apply_workflow):
    current = frappe.get_doc("Delivery Note", data.get("name"), for_update=True)
    current.check_permission("read")
    if current.docstatus != 0 or current.workflow_state not in ("To Deliver and Bill", "Draft"):
        frappe.throw(_("This Delivery Note is no longer awaiting final submission. Refresh it."))
    if str(current.modified) != str(data.get("modified")):
        frappe.throw(_("Delivery Note changed. Reload it before confirming the posting date."), frappe.TimestampMismatchError)
    if current.workflow_state == "Draft":
        if "Provincial Stock User" not in frappe.get_roles() or not current.items or any(
                not item.warehouse or frappe.db.get_value("Warehouse", item.warehouse, "company") != current.company
                or not frappe.db.get_value("Warehouse", item.warehouse, "custom_is_province") for item in current.items):
            frappe.throw(_("Only provincial warehouse deliveries can be tagged Active directly from Draft. Head Office deliveries must be released first."), frappe.PermissionError)
    date, time = _parse(data.get("_qcmc_actual_posting"))
    if current.meta.get("queue_in_background"):
        frappe.throw(_("Final Delivery Note posting requires synchronous workflow submission. Contact MIS."))
    prior = frappe.flags.get(FLAG)
    frappe.flags[FLAG] = {"name": current.name, "date": date, "time": time}
    try:
        # The native workflow checks the role, transition, conditions and document permissions.
        # It reloads the document, so the posting values are supplied via a scoped request flag.
        result = standard_apply_workflow(current.as_json(), action)
        if frappe.db.get_value("Delivery Note", current.name, "docstatus") != 1:
            frappe.throw(_("Final submission did not complete. No posting date was committed."))
        saved = frappe.db.get_value("Delivery Note", current.name, ["posting_date", "posting_time"], as_dict=True)
        if getdate(saved.posting_date) != date or get_time(saved.posting_time) != time:
            frappe.throw(_("Actual posting date or time changed during submission. Transaction rolled back."))
        return result
    finally:
        frappe.flags[FLAG] = prior


def _is_final_submission(doc):
    return int(doc.docstatus) == 1 and doc.get("workflow_state") == "Completed"


def apply_actual_posting(doc, method=None):
    if not _is_final_submission(doc):
        return
    values = frappe.flags.get(FLAG)
    if not values or values["name"] != doc.name:
        frappe.throw(_("Use Tag To Active and confirm the actual posting date and time."))
    doc.set_posting_time = 1
    doc.posting_date = values["date"]
    doc.posting_time = str(values["time"])


def verify_actual_posting(doc, method=None):
    if not _is_final_submission(doc):
        return
    values = frappe.flags.get(FLAG)
    if (not values or values["name"] != doc.name or not doc.set_posting_time
            or getdate(doc.posting_date) != values["date"] or get_time(doc.posting_time) != values["time"]):
        frappe.throw(_("Confirm the actual posting date and time through Tag To Active before submitting."))
