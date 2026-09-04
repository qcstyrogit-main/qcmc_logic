import frappe
from frappe import _
from frappe.utils import cint, flt

from qcmc_logic.customs.manufacturing_warehouse_access import (
    user_can_transact_job_card,
    user_can_transact_work_order,
)
from qcmc_logic.utils import (
    get_user_allowed_inventory_groups,
    has_inventory_group_access,
)


SUPPORTED_PURPOSES = {
    "Material Transfer for Manufacture",
    "Material Consumption for Manufacture",
    "Manufacture",
}
FABRICATED_MSJR_ROLE = "Stockroom_PR_EDSA_lv1"
FABRICATED_PART_REQUEST_TYPES = {
    "PARTS FABRICATION",
    "FABRICATION - ITEM",
    "FABRICATION - MACHINE PART",
}


def _validate_fabricated_msjr_role():
    if frappe.session.user == "Administrator":
        return
    if FABRICATED_MSJR_ROLE not in frappe.get_roles(frappe.session.user):
        frappe.throw(
            _("Only users with role {0} can receive fabricated MSJR output.").format(
                frappe.bold(FABRICATED_MSJR_ROLE)
            ),
            frappe.PermissionError,
        )


@frappe.whitelist()
def get_fabricated_msjrs_for_stock_entry(txt=None, page_len=20):
    """Return completed parts-fabrication MSJRs with output still to receive."""
    _validate_fabricated_msjr_role()
    frappe.has_permission("Stock Entry", ptype="create", throw=True)
    filters = {"workflow_state": "Completed", "docstatus": 1}
    or_filters = None
    if txt:
        or_filters = {
            "name": ["like", f"%{txt}%"],
            "item_code": ["like", f"%{txt}%"],
            "asset_name": ["like", f"%{txt}%"],
        }

    requests = frappe.get_list(
        "Machine Shop Job Request",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name", "request", "item_code", "asset", "asset_name",
            "quantity_produced", "company", "document_date", "modified",
        ],
        order_by="modified desc",
        limit_page_length=100,
    )

    rows = []
    for msjr in requests:
        request_type = (
            frappe.db.get_value("Machine Shop Request Code", msjr.request, "description") or ""
        ).strip().upper()
        if request_type not in FABRICATED_PART_REQUEST_TYPES:
            continue

        item_code = msjr.item_code
        if not item_code and msjr.asset:
            item_code = frappe.db.get_value("Asset", msjr.asset, "item_code")
        if not item_code:
            continue

        received_qty = frappe.db.sql(
            """
            SELECT COALESCE(SUM(sed.qty), 0)
            FROM `tabStock Entry` se
            INNER JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
            WHERE se.msjr_no = %s
              AND se.docstatus < 2
              AND se.purpose = 'Material Receipt'
              AND sed.item_code = %s
            """,
            (msjr.name, item_code),
        )[0][0]
        remaining_qty = max(flt(msjr.quantity_produced) - flt(received_qty), 0)
        if remaining_qty <= 0:
            continue

        rows.append({
            "name": msjr.name,
            "item_code": item_code,
            "description": msjr.asset_name or "",
            "quantity_produced": flt(msjr.quantity_produced),
            "received_qty": flt(received_qty),
            "remaining_qty": remaining_qty,
            "company": msjr.company,
            "document_date": msjr.document_date,
        })
        if len(rows) >= cint(page_len or 20):
            break

    return rows


@frappe.whitelist()
def make_material_receipt_from_fabricated_msjr(msjr_no):
    """Reuse the canonical MSJR output mapper from the Stock Entry screen."""
    from qcmc_logic.utils import make_completed_output_stock_entry

    _validate_fabricated_msjr_role()
    if not msjr_no:
        frappe.throw(_("Please select a completed fabricated MSJR."))
    return make_completed_output_stock_entry(msjr_no).as_dict()


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
    if not user_can_transact_work_order(wo.name):
        frappe.throw(
            _("You are not allowed to transact against Work Order {0}.").format(
                frappe.bold(work_order)
            )
        )

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
                ["qty", "produced_qty"],
                as_dict=True,
            )
            if not work_order:
                return 0

            pending_work_order_qty = max(flt(work_order.qty) - flt(work_order.produced_qty), 0)
            pending_job_card_output = max(
                flt(job_card.total_completed_qty) - flt(job_card.manufactured_qty),
                0,
            )
            return min(
                pending_job_card_output,
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


def _get_unauthorized_pending_material_items(job_card, purpose, user=None):
    if purpose != "Material Transfer for Manufacture":
        return []

    if not user:
        user = frappe.session.user
    if not has_inventory_group_access(user):
        return []

    allowed_inventory_groups = set(
        get_user_allowed_inventory_groups(user, require_transact=True)
    )
    item_codes = [
        row.item_code
        for row in job_card.items
        if row.item_code and flt(row.required_qty) > flt(row.transferred_qty)
    ]
    if not item_codes:
        return []

    inventory_groups = {
        row.name: row.custom_inventory_group
        for row in frappe.get_all(
            "Item",
            filters={"name": ["in", item_codes]},
            fields=["name", "custom_inventory_group"],
        )
    }

    unauthorized = []
    for row in job_card.items:
        if not row.item_code or flt(row.required_qty) <= flt(row.transferred_qty):
            continue

        inventory_group = inventory_groups.get(row.item_code)
        if not inventory_group or inventory_group not in allowed_inventory_groups:
            unauthorized.append(
                frappe._dict(
                    item_code=row.item_code,
                    inventory_group=inventory_group,
                )
            )

    return unauthorized


def _validate_pending_material_inventory_group_access(job_card, purpose, user=None):
    unauthorized = _get_unauthorized_pending_material_items(job_card, purpose, user=user)
    if not unauthorized:
        return

    item_list = ", ".join(
        "{0} ({1})".format(
            frappe.bold(row.item_code),
            frappe.bold(row.inventory_group or _("No Inventory Group")),
        )
        for row in unauthorized
    )
    frappe.throw(
        _(
            "You are not allowed to transact these pending material items for Job Card {0}: {1}"
        ).format(frappe.bold(job_card.name), item_list)
    )


def _can_use_job_card_for_purpose(job_card, work_order, purpose):
    """Return whether the selected Stock Entry purpose can act on this Job Card."""
    if not _has_pending_material(job_card, purpose):
        return False

    if purpose == "Material Transfer for Manufacture":
        return bool(
            work_order.transfer_material_against == "Job Card"
            and not cint(job_card.skip_material_transfer)
            and not cint(job_card.backflush_from_wip_warehouse)
            and job_card.items
            and not _get_unauthorized_pending_material_items(job_card, purpose)
        )

    if purpose == "Material Consumption for Manufacture":
        return bool(
            cint(job_card.skip_material_transfer)
            or cint(job_card.backflush_from_wip_warehouse)
        )

    if purpose == "Manufacture":
        if job_card.finished_good:
            return job_card.docstatus == 1

        return _is_final_operation_job_card(job_card, work_order)

    return False


def _job_card_row(job_card, purpose):
    pending_qty = _pending_qty(job_card, purpose)
    consumed_qty = sum(flt(row.get("consumed_qty")) for row in job_card.items)
    status = job_card.status
    if purpose == "Manufacture" and pending_qty <= 0:
        status = _("No unposted completed output")

    return {
        "name": job_card.name,
        "work_order": job_card.work_order,
        "operation": job_card.get("operation"),
        "workstation": job_card.get("workstation"),
        "work_order_operation": job_card.get("operation_id"),
        "production_item": job_card.finished_good or job_card.production_item,
        "for_quantity": flt(job_card.for_quantity),
        "transferred_qty": flt(job_card.transferred_qty),
        "consumed_qty": consumed_qty,
        "remaining_qty": pending_qty,
        "status": status,
        "has_pending_material": _has_pending_material(job_card, purpose),
    }


@frappe.whitelist()
def get_job_cards_for_stock_entry(
    purpose,
    work_order=None,
    company=None,
    txt=None,
    start=0,
    page_len=20,
):
    """Return selectable Job Cards with Work Order, item, and remaining qty."""
    _validate_purpose(purpose)

    filters = [["docstatus", "!=", 2]]
    if work_order:
        filters.append(["work_order", "=", work_order])
    if txt:
        filters.append(["name", "like", f"%{txt}%"])

    job_card_meta = frappe.get_meta("Job Card")
    fields = [
        "name",
        "work_order",
        "production_item",
        "finished_good",
        "for_quantity",
        "total_completed_qty",
        "transferred_qty",
        "manufactured_qty",
        "status",
        "modified",
    ]
    fields.extend(
        fieldname
        for fieldname in ("operation", "workstation", "operation_id")
        if job_card_meta.has_field(fieldname)
    )

    job_cards = frappe.get_all(
        "Job Card",
        filters=filters,
        fields=fields,
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
            ["docstatus", "status", "transfer_material_against", "company"],
            as_dict=True,
        )
        if not wo or cint(wo.docstatus) != 1 or wo.status == "Stopped":
            continue
        if company and wo.company != company:
            continue
        if not user_can_transact_work_order(item.work_order):
            continue

        job_card = frappe.get_doc("Job Card", item.name)
        if not user_can_transact_job_card(job_card):
            continue

        if item.work_order not in work_order_docs:
            work_order_docs[item.work_order] = frappe.get_doc("Work Order", item.work_order)

        if not _can_use_job_card_for_purpose(
            job_card,
            work_order_docs[item.work_order],
            purpose,
        ):
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
    if not user_can_transact_job_card(jc):
        frappe.throw(
            _("You are not allowed to transact against Job Card {0}.").format(
                frappe.bold(job_card)
            )
        )

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

    if not _can_use_job_card_for_purpose(jc, wo, purpose):
        frappe.throw(
            _("Job Card {0} cannot be used for {1}.").format(
                frappe.bold(jc.name),
                frappe.bold(purpose),
            )
        )

    pending_qty = _pending_qty(jc, purpose)
    if not _has_pending_material(jc, purpose):
        frappe.throw(_("No pending material found for Job Card {0}.").format(frappe.bold(jc.name)))
    _validate_pending_material_inventory_group_access(jc, purpose)

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
    if not user_can_transact_job_card(jc):
        frappe.throw(
            _("You are not allowed to transact against Job Card {0}.").format(
                frappe.bold(job_card)
            )
        )

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
    # Preserve the authoritative manufacturing link explicitly. Some customized
    # Stock Entry mappings can omit it while syncing the generated document.
    stock_entry.work_order = wo.name
    # The native Stock Entry.job_card link is reserved by ERPNext for Job Cards
    # with a configured semi-finished `finished_good`. Final-operation Job Cards
    # are linked through custom_final_job_card and the Stock Entry override
    # synchronizes the final Work Order quantity after submit/cancel.
    stock_entry.custom_final_job_card = jc.name
    stock_entry.custom_job_card_time_log = time_log.name
    stock_entry.insert()
    if stock_entry.work_order != wo.name:
        stock_entry.db_set("work_order", wo.name, update_modified=False)
        stock_entry.work_order = wo.name
    return stock_entry.as_dict()


def _sync_operation_for_incremental_output(job_card, work_order, qty):
    """Allow partial shift output without converting the remainder to loss."""
    if not job_card.operation_id:
        return

    operation = frappe.get_doc("Work Order Operation", job_card.operation_id)

    # QCMC uses successive Job Cards/shifts to complete a Work Order. ERPNext's
    # standard Job Card submission treats ``for_quantity - completed_qty`` as
    # process loss. Here that difference is remaining production, not loss.
    # Clear legacy values as part of Draft creation so already-submitted Job
    # Cards can be retried safely after this correction.
    if flt(job_card.get("process_loss_qty")):
        job_card.db_set("process_loss_qty", 0, update_modified=False)
    if flt(operation.process_loss_qty):
        operation.db_set("process_loss_qty", 0, update_modified=False)

    completed_qty = max(
        flt(operation.completed_qty),
        flt(work_order.produced_qty) + flt(qty),
    )

    if completed_qty != flt(operation.completed_qty):
        operation.db_set("completed_qty", completed_qty, update_modified=False)
