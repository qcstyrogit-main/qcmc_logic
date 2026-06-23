import frappe
from frappe import _
from frappe.utils import cint, flt


SUPPORTED_PURPOSES = {
    "Material Transfer for Manufacture",
    "Material Consumption for Manufacture",
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


def _pending_qty(job_card, purpose):
    if purpose == "Material Transfer for Manufacture":
        return max(flt(job_card.for_quantity) - flt(job_card.transferred_qty), 0)

    if frappe.get_meta("Job Card Item").has_field("consumed_qty"):
        total_required = sum(flt(row.required_qty) for row in job_card.items)
        total_consumed = sum(flt(row.get("consumed_qty")) for row in job_card.items)
        if total_required:
            return max(total_required - total_consumed, 0)

    return flt(job_card.for_quantity)


def _has_pending_material(job_card, purpose):
    if purpose == "Material Transfer for Manufacture":
        return any(flt(row.required_qty) > flt(row.transferred_qty) for row in job_card.items)

    if frappe.get_meta("Job Card Item").has_field("consumed_qty"):
        return any(flt(row.required_qty) > flt(row.get("consumed_qty")) for row in job_card.items)

    return bool(job_card.items)


def _job_card_row(job_card, purpose):
    pending_qty = _pending_qty(job_card, purpose)
    consumed_qty = sum(flt(row.get("consumed_qty")) for row in job_card.items)

    return {
        "name": job_card.name,
        "work_order": job_card.work_order,
        "production_item": job_card.production_item,
        "for_quantity": flt(job_card.for_quantity),
        "transferred_qty": flt(job_card.transferred_qty),
        "consumed_qty": consumed_qty,
        "remaining_qty": pending_qty,
        "status": job_card.status,
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
            "for_quantity",
            "transferred_qty",
            "status",
            "modified",
        ],
        order_by="modified desc",
        limit_start=cint(start),
        limit_page_length=cint(page_len) or 20,
    )

    rows = []
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
        rows.append(_job_card_row(job_card, purpose))

    rows.sort(key=lambda row: (0 if row["has_pending_material"] else 1, row["name"]))
    return rows


@frappe.whitelist()
def get_job_card_details_for_stock_entry(job_card, purpose, work_order=None):
    """Return header values needed to fill Stock Entry from one Job Card."""
    _validate_purpose(purpose)

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
