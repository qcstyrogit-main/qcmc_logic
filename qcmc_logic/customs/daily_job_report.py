import frappe
from frappe import _
from frappe.utils import add_days, flt, get_datetime, now_datetime


PROCESS_DT = "Machine Shop Repairs and Project Process"
PROJECT_DT = "Machine Shop Repairs and Project"
OBSOLETE_SCHEDULE_FIELDS = (
    "Daily Job Report-daily_job_schedule",
    "Daily Job Report-job_schedule_row",
)


def remove_obsolete_schedule_fields():
    """Remove the earlier visible DJR links; schedule matching is now automatic."""
    for field_name in OBSOLETE_SCHEDULE_FIELDS:
        if frappe.db.exists("Custom Field", field_name):
            frappe.delete_doc("Custom Field", field_name, ignore_permissions=True, force=True)
    frappe.clear_cache(doctype="Daily Job Report")


def validate(doc, method=None):
    """Allow actual work only when Engineering scheduled it for the same MSJR/process/time."""
    _validate_dates(doc)
    process = _get_process(doc)
    _validate_active_project(doc, process)
    schedule_row = _find_scheduled_work(doc, process)
    _validate_reported_quantity(doc, process, schedule_row)


def _validate_dates(doc):
    current = now_datetime()
    started = get_datetime(doc.date_started) if doc.get("date_started") else None
    finished = get_datetime(doc.date_finished) if doc.get("date_finished") else None
    if started and started > current:
        frappe.throw(_("Date Started cannot be a future date."))
    if finished and finished > current:
        frappe.throw(_("Date Finished cannot be a future date."))
    if started and finished and started > finished:
        frappe.throw(_("Date Started cannot be greater than Date Finished."))


def _get_process(doc):
    process = frappe.db.get_value(
        PROCESS_DT,
        doc.get("process_no"),
        ["parent", "status", "plan_quantity", "done_quantity"],
        as_dict=True,
    )
    if not process:
        frappe.throw(_("Select a valid Machine Shop process."))
    return process


def _validate_active_project(doc, process):
    state = frappe.db.get_value(PROJECT_DT, process.parent, "workflow_state")
    if state != "Active":
        frappe.throw(
            _("Daily Job Reports can only be recorded against an Active project. Current state: {0}.").format(
                frappe.bold(state or _("Unknown"))
            )
        )
    doc.project_no = process.parent


def _find_scheduled_work(doc, process):
    project_msjr = frappe.db.get_value(PROJECT_DT, process.parent, "msjr_no")
    rows = frappe.db.sql(
        """
        SELECT
            js.name AS row_name,
            js.parent AS schedule_name,
            js.employee,
            js.quantity,
            djs.sched_date,
            djs.time_from,
            djs.time_to,
            djs.shift
        FROM `tabJob Schedule` js
        INNER JOIN `tabDaily Job Schedule` djs ON djs.name = js.parent
        WHERE js.parenttype = 'Daily Job Schedule'
          AND js.process = %(process)s
          AND js.msrp_no = %(msrp)s
          AND js.msjr_no = %(msjr)s
          AND djs.docstatus != 2
        ORDER BY djs.sched_date DESC, djs.creation DESC, js.idx ASC
        """,
        {"process": doc.process_no, "msrp": process.parent, "msjr": project_msjr},
        as_dict=True,
    )
    started = get_datetime(doc.date_started) if doc.get("date_started") else None
    finished = get_datetime(doc.date_finished) if doc.get("date_finished") else None
    if not started or not finished:
        frappe.throw(_("Date Started and Date Finished are required to verify schedule coverage."))

    for row in rows:
        if not row.sched_date or row.time_from is None or row.time_to is None:
            continue
        window_start = get_datetime(f"{row.sched_date} {row.time_from}")
        window_end = get_datetime(f"{row.sched_date} {row.time_to}")
        if window_end <= window_start:
            window_end = add_days(window_end, 1)
        if started < window_start or finished > window_end:
            continue
        if row.employee and doc.get("worked_by") and row.employee != doc.worked_by:
            continue
        row.window_start = window_start
        row.window_end = window_end
        if row.employee and not doc.get("worked_by"):
            doc.worked_by = row.employee
        return row

    frappe.throw(
        _(
            "No Engineering Daily Job Schedule covers this MSJR, MSRP Process, employee, and DJR date/time."
        ),
        title=_("Work Not Scheduled"),
    )


def _validate_reported_quantity(doc, process, schedule_row=None):
    quantity = flt(doc.get("quantity"))
    if quantity < 0:
        frappe.throw(_("Reported Quantity cannot be negative."))

    already_reported = frappe.db.sql(
        """
        SELECT COALESCE(SUM(quantity), 0)
        FROM `tabDaily Job Report`
        WHERE process_no = %s AND name != %s AND docstatus != 2
        """,
        (doc.process_no, doc.name or ""),
    )[0][0]
    remaining = max(flt(process.plan_quantity) - flt(already_reported), 0)
    if quantity > remaining:
        frappe.throw(
            _("Reported Quantity {0} exceeds the remaining process quantity of {1}.").format(
                quantity, remaining
            ),
            title=_("Quantity Exceeds Plan"),
        )

    if schedule_row:
        row_reported = frappe.db.sql(
            """
            SELECT COALESCE(SUM(quantity), 0)
            FROM `tabDaily Job Report`
            WHERE process_no = %s
              AND name != %s
              AND docstatus != 2
              AND date_started >= %s
              AND date_finished <= %s
            """,
            (
                doc.process_no,
                doc.name or "",
                schedule_row.window_start,
                schedule_row.window_end,
            ),
        )[0][0]
        row_remaining = max(flt(schedule_row.quantity) - flt(row_reported), 0)
        if quantity > row_remaining:
            frappe.throw(
                _("Reported Quantity {0} exceeds the remaining scheduled-row quantity of {1}.").format(
                    quantity, row_remaining
                ),
                title=_("Quantity Exceeds Schedule"),
            )
