import frappe
from frappe import _
from frappe.utils import cint, flt


SUPPORTED_PURPOSES = {
    "Material Transfer for Manufacture",
    "Material Consumption for Manufacture",
    "Manufacture",
}


def _validate_purpose(purpose):
    if purpose not in SUPPORTED_PURPOSES:
        frappe.throw(_("Purpose {0} is not supported for Job Card fetch.").format(frappe.bold(purpose)))


def _get_work_order(work_order):
    if not work_order:
        frappe.throw(_("Job Card must be linked to a Work Order."))

    wo = frappe.get_doc("Work Order", work_order)
    if wo.docstatus != 1:
        frappe.throw(_("Work Order {0} must be submitted.").format(frappe.bold(work_order)))
    if wo.status == "Stopped":
        frappe.throw(_("Work Order {0} is stopped.").format(frappe.bold(work_order)))

    return wo


def _get_final_operation(work_order):
    """Return the last Work Order operation by sequence and row order."""
    operations = list(work_order.get("operations") or [])
    if not operations:
        return None

    return max(
        operations,
        key=lambda row: (cint(row.get("sequence_id")), cint(row.get("idx"))),
    )


def _is_final_operation_job_card(job_card, work_order):
    """Return whether a Job Card belongs to the Work Order's final operation."""
    final_operation = _get_final_operation(work_order)
    if not final_operation:
        return True

    return job_card.operation_id == final_operation.name


def _validate_final_operation_job_card(job_card, work_order):
    final_operation = _get_final_operation(work_order)
    if not final_operation or job_card.operation_id == final_operation.name:
        return

    frappe.throw(
        _(
            "Manufacture Stock Entries are allowed only from the final operation "
            "{0} (Sequence {1}) for Work Order {2}."
        ).format(
            frappe.bold(final_operation.operation),
            frappe.bold(cint(final_operation.sequence_id)),
            frappe.bold(work_order.name),
        )
    )


def _get_latest_actual_time_log(job_card):
    time_logs = list(job_card.get("time_logs") or [])
    if not time_logs:
        frappe.throw(
            _(
                "Final Job Card {0} must have an Actual Time row before creating "
                "a Manufacture Stock Entry."
            ).format(frappe.bold(job_card.name))
        )

    return max(time_logs, key=lambda row: cint(row.get("idx")))


def _pending_qty(job_card, purpose):
    if purpose == "Manufacture":
        if not job_card.finished_good:
            work_order = frappe.db.get_value(
                "Work Order",
                job_card.work_order,
                ["qty", "produced_qty", "skip_transfer"],
                as_dict=True,
            )
            if not work_order:
                return 0

            pending_work_order_qty = max(flt(work_order.qty) - flt(work_order.produced_qty), 0)

            if work_order.skip_transfer:
                return min(
                    max(flt(job_card.for_quantity) - flt(work_order.produced_qty), 0),
                    pending_work_order_qty,
                )

            return min(
                max(flt(job_card.transferred_qty) - flt(work_order.produced_qty), 0),
                pending_work_order_qty,
            )

        return max(flt(job_card.for_quantity) - flt(job_card.manufactured_qty), 0)

    if purpose == "Material Transfer for Manufacture":
        return max(flt(job_card.for_quantity) - flt(job_card.transferred_qty), 0)

    if frappe.get_meta("Job Card Item").has_field("consumed_qty"):
        total_required = sum(flt(row.required_qty) for row in job_card.items)
        total_consumed = sum(flt(row.get("consumed_qty")) for row in job_card.items)
        if total_required:
            return max(total_required - total_consumed, 0)

    return flt(job_card.for_quantity)


def _has_pending_material(job_card, purpose):
    if purpose == "Manufacture":
        return _pending_qty(job_card, purpose) > 0

    if purpose == "Material Transfer for Manufacture":
        return any(flt(row.required_qty) > flt(row.transferred_qty) for row in job_card.items)

    if frappe.get_meta("Job Card Item").has_field("consumed_qty"):
        return any(flt(row.required_qty) > flt(row.get("consumed_qty")) for row in job_card.items)

    return bool(job_card.items)


def _job_card_row(job_card, purpose):
    pending_qty = _pending_qty(job_card, purpose)
    consumed_qty = sum(flt(row.get("consumed_qty")) for row in job_card.items)
    status = job_card.status
    if purpose == "Manufacture" and pending_qty <= 0:
        status = _("No unposted completed output")

    return {
        "name": job_card.name,
        "work_order": job_card.work_order,
        "production_item": job_card.finished_good or job_card.production_item,
        "for_quantity": flt(job_card.for_quantity),
        "transferred_qty": flt(job_card.transferred_qty),
        "consumed_qty": consumed_qty,
        "remaining_qty": pending_qty,
        "status": status,
        "has_pending_material": _has_pending_material(job_card, purpose),
    }


@frappe.whitelist()
def get_job_cards_for_stock_entry(purpose, work_order=None, txt=None, start=0, page_len=20):
    """Return selectable Job Cards with Work Order, item, and remaining qty."""
    _validate_purpose(purpose)

    filters = [["docstatus", "!=", 2]]
    if work_order:
        filters.append(["work_order", "=", work_order])
    if txt:
        filters.append(["name", "like", f"%{txt}%"])

    job_cards = frappe.get_all(
        "Job Card",
        filters=filters,
        fields=[
            "name",
            "work_order",
            "production_item",
            "finished_good",
            "for_quantity",
            "transferred_qty",
            "manufactured_qty",
            "status",
            "modified",
        ],
        order_by="modified desc",
        limit_start=cint(start),
        limit_page_length=cint(page_len) or 20,
    )

    rows = []
    work_order_docs = {}
    for item in job_cards:
        if not item.work_order:
            continue

        wo = frappe.db.get_value(
            "Work Order",
            item.work_order,
            ["docstatus", "status", "transfer_material_against"],
            as_dict=True,
        )
        if not wo or cint(wo.docstatus) != 1 or wo.status == "Stopped":
            continue

        job_card = frappe.get_doc("Job Card", item.name)
        if item.work_order not in work_order_docs:
            work_order_docs[item.work_order] = frappe.get_doc("Work Order", item.work_order)

        if purpose == "Manufacture" and not _is_final_operation_job_card(
            job_card, work_order_docs[item.work_order]
        ):
            continue

        if purpose == "Manufacture" and job_card.finished_good and job_card.docstatus != 1:
            continue

        rows.append(_job_card_row(job_card, purpose))

    rows.sort(key=lambda row: (0 if row["has_pending_material"] else 1, row["name"]))
    return rows


@frappe.whitelist()
def get_job_card_details_for_stock_entry(job_card, purpose, work_order=None):
    """Return header values needed to fill Stock Entry from one Job Card."""
    _validate_purpose(purpose)
    if purpose == "Manufacture":
        frappe.throw(_("Use the Manufacture action to create the Stock Entry from a Job Card."))

    if not job_card:
        frappe.throw(_("Please select a Job Card."))

    jc = frappe.get_doc("Job Card", job_card)
    if jc.docstatus == 2 or jc.status == "Cancelled":
        frappe.throw(_("Job Card {0} is cancelled.").format(frappe.bold(job_card)))

    wo = _get_work_order(jc.work_order)

    if work_order and work_order != jc.work_order:
        frappe.throw(
            _("Selected Job Card {0} belongs to Work Order {1}, not {2}.").format(
                frappe.bold(jc.name), frappe.bold(jc.work_order), frappe.bold(work_order)
            )
        )

    if wo.transfer_material_against != "Job Card":
        frappe.msgprint(
            _(
                "Work Order {0} is not configured to transfer material against Job Card. "
                "Items may not be limited to this Job Card."
            ).format(frappe.bold(wo.name)),
            indicator="orange",
        )

    pending_qty = _pending_qty(jc, purpose)
    if not _has_pending_material(jc, purpose):
        frappe.throw(_("No pending material found for Job Card {0}.").format(frappe.bold(jc.name)))

    if purpose == "Material Transfer for Manufacture":
        from_warehouse = jc.source_warehouse or wo.source_warehouse
        to_warehouse = jc.wip_warehouse or wo.wip_warehouse
    else:
        from_warehouse = jc.wip_warehouse or wo.wip_warehouse
        to_warehouse = None

    return {
        "job_card": jc.name,
        "work_order": jc.work_order,
        "bom_no": jc.semi_fg_bom or jc.bom_no or wo.bom_no,
        "from_bom": 1,
        "fg_completed_qty": pending_qty,
        "from_warehouse": from_warehouse,
        "to_warehouse": to_warehouse,
        "production_item": jc.production_item,
        "remaining_qty": pending_qty,
    }


@frappe.whitelist()
def make_manufacture_stock_entry_from_job_card(job_card, qty=None):
    """Create a draft Manufacture entry appropriate for the selected Job Card."""
    frappe.has_permission("Stock Entry", ptype="create", throw=True)

    if not job_card:
        frappe.throw(_("Please select a Job Card."))

    jc = frappe.get_doc("Job Card", job_card)
    wo = _get_work_order(jc.work_order)
    _validate_final_operation_job_card(jc, wo)

    pending_qty = _pending_qty(jc, "Manufacture")
    if pending_qty <= 0:
        frappe.throw(
            _("Job Card {0} has no remaining quantity to manufacture.").format(
                frappe.bold(jc.name)
            )
        )

    qty = flt(qty)
    if qty <= 0:
        frappe.throw(_("Manufacture quantity must be greater than zero."))
    if qty > pending_qty:
        frappe.throw(
            _("Manufacture quantity cannot exceed the available completed output of {0}.").format(
                frappe.bold(pending_qty)
            )
        )

    draft_filters = {
        "purpose": "Manufacture",
        "docstatus": 0,
    }
    if jc.finished_good:
        draft_filters["job_card"] = jc.name
    else:
        draft_filters["work_order"] = jc.work_order

    existing_draft = frappe.db.get_value("Stock Entry", draft_filters, "name")
    if existing_draft:
        frappe.throw(
            _("Draft Manufacture Stock Entry {0} already exists for Job Card {1}.").format(
                frappe.get_desk_link("Stock Entry", existing_draft),
                frappe.bold(jc.name),
            )
        )

    if jc.finished_good:
        if jc.docstatus != 1:
            frappe.throw(_("Job Card {0} must be submitted.").format(frappe.bold(jc.name)))
        return jc.make_stock_entry_for_semi_fg_item(auto_submit=False)

    from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

    time_log = _get_latest_actual_time_log(jc)
    _sync_operation_for_incremental_output(jc, wo, qty)
    stock_entry = frappe.get_doc(
        make_stock_entry(
            work_order_id=wo.name,
            purpose="Manufacture",
            qty=qty,
        )
    )
    stock_entry.custom_final_job_card = jc.name
    stock_entry.custom_job_card_time_log = time_log.name
    stock_entry.insert()
    return stock_entry.as_dict()


def _sync_operation_for_incremental_output(job_card, work_order, qty):
    """Allow incremental output while the shift Job Card remains open."""
    if not job_card.operation_id:
        return

    operation = frappe.get_doc("Work Order Operation", job_card.operation_id)
    completed_qty = max(
        flt(operation.completed_qty),
        flt(work_order.produced_qty) + flt(qty),
    )

    if completed_qty != flt(operation.completed_qty):
        operation.db_set("completed_qty", completed_qty, update_modified=False)
