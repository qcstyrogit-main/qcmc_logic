import frappe
from frappe import _
from frappe.utils import flt


def validate_scheduled_processes(doc, method=None):
    """Validate newly scheduled processes without breaking historical schedules."""
    _validate_unique_shift(doc)
    existing_processes = {}
    if not doc.is_new():
        existing_processes = {
            row.name: row.process
            for row in frappe.get_all(
                "Job Schedule",
                filters={"parent": doc.name, "parenttype": "Daily Job Schedule"},
                fields=["name", "process"],
            )
        }

    for row in doc.get("job_schedule") or []:
        if not row.get("process"):
            continue
        if row.name in existing_processes and existing_processes[row.name] == row.process:
            continue
        _validate_schedule_row(row)


def _validate_unique_shift(doc):
    """Enforce one schedule per date/shift on the server (the client check is advisory)."""
    if not doc.get("sched_date") or not doc.get("shift"):
        return

    filters = {"sched_date": doc.sched_date, "shift": doc.shift}
    if not doc.is_new():
        filters["name"] = ["!=", doc.name]
    duplicate = frappe.db.exists("Daily Job Schedule", filters)
    if duplicate:
        frappe.throw(
            _("A {0} shift already exists for {1}: {2}.").format(
                frappe.bold(doc.shift), frappe.bold(doc.sched_date), frappe.bold(duplicate)
            ),
            title=_("Duplicate Daily Job Schedule"),
        )


def _validate_schedule_row(row):
    process = frappe.db.get_value(
        "Machine Shop Repairs and Project Process",
        row.process,
        ["parent", "process_name", "status", "plan_quantity", "done_quantity"],
        as_dict=True,
    )
    if not process:
        frappe.throw(_("Process {0} does not exist.").format(frappe.bold(row.process)))

    if row.get("msrp_no") != process.parent:
        frappe.throw(
            _("Row {0}: Process {1} does not belong to Project {2}.").format(
                row.idx, frappe.bold(row.process), frappe.bold(row.get("msrp_no") or "")
            )
        )

    project = frappe.db.get_value(
        "Machine Shop Repairs and Project",
        process.parent,
        ["workflow_state", "msjr_no"],
        as_dict=True,
    )
    if not project or project.workflow_state != "Active":
        frappe.throw(
            _("Row {0}: Project {1} must be Active before its process can be scheduled.").format(
                row.idx, frappe.bold(process.parent)
            )
        )

    if row.get("msjr_no") and row.msjr_no != project.msjr_no:
        frappe.throw(
            _("Row {0}: MSJR {1} does not match Project {2}.").format(
                row.idx, frappe.bold(row.msjr_no), frappe.bold(process.parent)
            )
        )

    remaining_qty = max(flt(process.plan_quantity) - flt(process.done_quantity), 0)
    if process.status == "Completed" or remaining_qty <= 0:
        frappe.throw(
            _("Row {0}: Process {1} is completed or has no remaining quantity.").format(
                row.idx, frappe.bold(process.process_name or row.process)
            )
        )

    scheduled_qty = flt(row.get("quantity"))
    if scheduled_qty <= 0:
        frappe.throw(_("Row {0}: Scheduled Quantity must be greater than zero.").format(row.idx))
    if scheduled_qty > remaining_qty:
        frappe.throw(
            _("Row {0}: Scheduled Quantity cannot exceed the remaining quantity of {1}.").format(
                row.idx, remaining_qty
            )
        )
