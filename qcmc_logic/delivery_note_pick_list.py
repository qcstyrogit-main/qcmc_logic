"""Existing Delivery Note -> Pick List linkage, preserving the commercial document."""
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt


def _active_link(name):
    return bool(name and frappe.db.exists("Pick List", {"name": name, "docstatus": ["!=", 2]}))


@frappe.whitelist()
def get_linked_pick_lists(delivery_note):
    doc = frappe.get_doc("Delivery Note", delivery_note)
    doc.check_permission("read")
    names = sorted({row.against_pick_list for row in doc.items if row.against_pick_list})
    return [
        frappe.db.get_value("Pick List", name, ["name", "status", "docstatus", "purpose"], as_dict=True)
        for name in names
        if _active_link(name) and frappe.has_permission("Pick List", "read", name)
    ]


@frappe.whitelist()
def get_linked_delivery_notes(pick_list):
    pick = frappe.get_doc("Pick List", pick_list)
    pick.check_permission("read")
    if pick.docstatus == 2:
        return []
    names = frappe.db.get_all("Delivery Note Item",
        filters={"against_pick_list": pick_list}, pluck="parent")
    return [
        frappe.db.get_value("Delivery Note", name, ["name", "docstatus", "status"], as_dict=True)
        for name in sorted(set(names))
        if frappe.db.exists("Delivery Note", name)
        and frappe.has_permission("Delivery Note", "read", name)
    ]


def repair_delivery_note_pick_references(doc, method=None):
    """Resolve replaced Pick List child rows without changing Delivery Note quantities."""
    for row in doc.items:
        if not row.against_pick_list:
            continue
        if not _active_link(row.against_pick_list):
            if doc.docstatus == 0:
                row.against_pick_list = None
                row.pick_list_item = None
            continue
        matches = frappe.db.get_all("Pick List Item", filters={
            "parent": row.against_pick_list, "item_code": row.item_code,
            "warehouse": row.warehouse,
        }, fields=["name", "sales_order_item", "batch_no"])
        if row.get("so_detail"):
            matches = [m for m in matches if m.sales_order_item == row.so_detail]
        if row.get("batch_no"):
            matches = [m for m in matches if (m.batch_no or "") == row.batch_no]
        if not matches:
            frappe.throw(_("Row {0}: No matching item exists in Pick List {1}.").format(
                row.idx, row.against_pick_list))
        # One Delivery Note item can represent several bins. Keep the stable
        # parent Pick List reference rather than an obsolete child-row name.
        row.pick_list_item = matches[0].name if len(matches) == 1 else None


@frappe.whitelist(methods=["POST"])
def create_pick_list_from_delivery_note(delivery_note):
    dn = frappe.get_doc("Delivery Note", delivery_note)
    dn.check_permission("write")
    frappe.has_permission("Pick List", "create", throw=True)
    if dn.docstatus != 0 or dn.is_return:
        frappe.throw(_("Only non-return draft Delivery Notes can create Pick Lists."))
    lines = [row for row in dn.items if flt(row.qty) > 0]
    if not lines:
        frappe.throw(_("Add positive-quantity items before creating a Pick List."))
    if any(not row.warehouse for row in lines):
        frappe.throw(_("Set a source Warehouse on every item first."))

    # A cancelled Pick List must not block a replacement.
    for row in dn.items:
        if row.against_pick_list and not _active_link(row.against_pick_list):
            frappe.db.set_value("Delivery Note Item", row.name,
                {"against_pick_list": None, "pick_list_item": None}, update_modified=False)
            row.against_pick_list = None
            row.pick_list_item = None
    active = {row.against_pick_list for row in dn.items if _active_link(row.against_pick_list)}
    if active:
        if len(active) == 1:
            return {"name": next(iter(active)), "existing": True}
        frappe.throw(_("This Delivery Note is linked to multiple Pick Lists. Review the links first."))

    pick = frappe.new_doc("Pick List")
    pick.company = dn.company
    pick.customer = dn.customer
    pick.purpose = "Delivery"
    pick.pick_manually = 1
    warehouses = {row.warehouse for row in lines}
    if len(warehouses) == 1:
        pick.parent_warehouse = next(iter(warehouses))
    for row in lines:
        item = frappe.get_cached_value("Item", row.item_code, ["stock_uom", "is_stock_item"], as_dict=True)
        if not item or not item.is_stock_item:
            frappe.throw(_("Item {0} is not a stock item; direct Delivery Note handling is required.").format(row.item_code))
        if frappe.db.get_value("Warehouse", row.warehouse, "company") != dn.company:
            frappe.throw(_("Row {0}: Warehouse does not belong to the Delivery Note company.").format(row.idx))
        factor = flt(row.conversion_factor) or 1
        pick.append("locations", {
            "item_code": row.item_code,
            "warehouse": row.warehouse,
            "uom": row.uom or item.stock_uom,
            "stock_uom": item.stock_uom,
            "conversion_factor": factor,
            "qty": flt(row.qty),
            "stock_qty": flt(row.qty) * factor,
            "picked_qty": 0,
            "sales_order": row.against_sales_order,
            "sales_order_item": row.so_detail,
            "batch_no": row.batch_no,
        })
    pick.insert()
    for source, target in zip(lines, pick.locations):
        frappe.db.set_value("Delivery Note Item", source.name,
            {"against_pick_list": pick.name, "pick_list_item": target.name},
            update_modified=False)
    return {"name": pick.name, "existing": False}


def get_delivery_note_out_movements(warehouse, location=None, item_code=None, after=None):
    """Attribute only submitted outbound Delivery Note SLEs to picked locations.

    This is a read-only location projection. Posted SLEs remain authoritative;
    returned and cancelled documents cannot generate additional OUT here.
    """
    from collections import defaultdict

    params = {"warehouse": warehouse}
    conditions = ["dni.warehouse = %(warehouse)s", "dn.docstatus = 1",
        "ifnull(dn.is_return, 0) = 0", "pl.docstatus = 1",
        "sle.is_cancelled = 0", "sle.actual_qty < 0"]
    if item_code:
        conditions.append("dni.item_code = %(item_code)s")
        params["item_code"] = item_code
    issues = frappe.db.sql("""
        select dn.name as delivery_note, dni.name as delivery_item,
               dni.item_code, dni.against_pick_list as pick_list,
               coalesce(dni.so_detail, '') as so_detail,
               sle.actual_qty, sle.posting_datetime as movement_time,
               sle.stock_uom as uom, sle.location as ledger_location,
               coalesce(sle.owner, dn.owner) as performed_by
        from `tabDelivery Note Item` dni
        inner join `tabDelivery Note` dn on dn.name = dni.parent
        inner join `tabPick List` pl on pl.name = dni.against_pick_list
        inner join `tabStock Ledger Entry` sle
            on sle.voucher_type = 'Delivery Note'
            and sle.voucher_no = dn.name
            and sle.voucher_detail_no = dni.name
        where """ + " and ".join(conditions) + """
        order by sle.posting_datetime, dn.name, dni.idx, sle.name
    """, params, as_dict=True)
    if not issues:
        return []
    parents = sorted({row.pick_list for row in issues})
    pick_rows = frappe.db.sql("""
        select parent, item_code, warehouse, coalesce(sales_order_item, '') as so_detail,
               name, location, picked_qty, idx
        from `tabPick List Item`
        where parent in %(parents)s and warehouse = %(warehouse)s
        order by parent, item_code, idx, name
    """, {"parents": tuple(parents), "warehouse": warehouse}, as_dict=True)
    available = defaultdict(list)
    for row in pick_rows:
        if row.location and flt(row.picked_qty) > 0:
            available[(row.parent, row.item_code, row.so_detail)].append(
                [row.location, flt(row.picked_qty)])
    result = []
    for issue in issues:
        pending = abs(flt(issue.actual_qty))
        for candidate in available[(issue.pick_list, issue.item_code, issue.so_detail)]:
            if pending <= 1e-9:
                break
            allocated = min(candidate[1], pending)
            if allocated <= 0:
                continue
            pending -= allocated
            candidate[1] -= allocated
            if location is not None and location != candidate[0]:
                continue
            if after and issue.movement_time <= after:
                continue
            result.append({
                "item_code": issue.item_code,
                "location": candidate[0],
                "quantity": -allocated,
                "uom": issue.uom,
                "reference_name": issue.delivery_note,
                "movement_time": issue.movement_time,
                "performed_by": issue.performed_by,
                "ledger_location": issue.ledger_location,
            })
    return result




@frappe.whitelist(methods=["POST"])
def repair_submitted_delivery_pick_list(pick_list):
    """Explicit repair for previously submitted Delivery Notes with split bins."""
    pick = frappe.get_doc("Pick List", pick_list)
    pick.check_permission("write")
    if pick.docstatus != 1 or pick.purpose != "Delivery":
        frappe.throw(_("Only submitted Delivery Pick Lists can be synchronized."))
    docs = frappe.db.get_all("Delivery Note Item",
        filters={"against_pick_list": pick_list}, pluck="parent")
    if not docs:
        frappe.throw(_("No linked Delivery Notes were found."))
    for name in set(docs):
        dn = frappe.get_doc("Delivery Note", name)
        dn.check_permission("read")
    # The sync helper queries every submitted note referenced by this Pick List.
    sync_delivery_pick_list_progress(frappe.get_doc("Delivery Note", sorted(set(docs))[0]))
    return frappe.db.get_value("Pick List", pick_list,
        ["name", "status", "delivery_status", "per_delivered"], as_dict=True)


def sync_delivery_pick_list_progress(doc, method=None):
    """Recalculate delivered quantities on split Pick List rows after DN posting.

    Native ERPNext maps a DN item to one Pick List Item. QCMC's delivery flow
    can split the same item across physical locations. Sum all submitted
    Delivery Notes and allocate that total across the Pick List's picked rows.
    Never infer delivery from a draft or cancelled DN.
    """
    names = sorted({row.against_pick_list for row in doc.items if row.against_pick_list})
    for name in names:
        if not frappe.db.exists("Pick List", {"name": name, "docstatus": 1}):
            continue
        pick = frappe.get_doc("Pick List", name)
        if pick.purpose != "Delivery":
            continue
        from collections import defaultdict
        outstanding = defaultdict(float)
        shipped = frappe.db.sql("""
            select dni.item_code, dni.warehouse,
                coalesce(dni.so_detail, '') as so_detail,
                coalesce(dni.batch_no, '') as batch_no,
                sum(dni.stock_qty) as delivered
            from `tabDelivery Note Item` dni
            inner join `tabDelivery Note` dn on dn.name = dni.parent
            where dni.against_pick_list = %s and dn.docstatus = 1
                and coalesce(dn.is_return, 0) = 0
            group by dni.item_code, dni.warehouse, dni.so_detail, dni.batch_no
        """, name, as_dict=True)
        for row in shipped:
            key = (row.item_code, row.warehouse, row.so_detail or "", row.batch_no or "")
            outstanding[key] += flt(row.delivered)
        total_picked = 0
        total_delivered = 0
        for row in pick.locations:
            key = (row.item_code, row.warehouse, row.sales_order_item or "", row.batch_no or "")
            picked = flt(row.picked_qty)
            allocated = min(picked, max(outstanding[key], 0))
            outstanding[key] -= allocated
            total_picked += picked
            total_delivered += allocated
            frappe.db.set_value("Pick List Item", row.name, "delivered_qty",
                allocated, update_modified=False)
        # Derive completion from actual submitted, linked deliveries.
        percentage = 100 * total_delivered / total_picked if total_picked > 0 else 0
        status = "Completed" if total_picked > 0 and percentage >= 100 - 1e-7 else (
            "Partly Delivered" if total_delivered > 0 else "Open"
        )
        frappe.db.set_value("Pick List", name, {
            "per_delivered": percentage,
            "delivery_status": "Fully Delivered" if status == "Completed" else (
                "Partly Delivered" if total_delivered else "Not Delivered"),
            "status": status,
        }, update_modified=False)

def unlink_cancelled_pick_list(pick_list):
    rows = frappe.db.get_all("Delivery Note Item",
        filters={"against_pick_list": pick_list}, fields=["parent"])
    for name in {row.parent for row in rows}:
        if frappe.db.get_value("Delivery Note", name, "docstatus") == 1:
            frappe.throw(_("Cancel Delivery Note {0} before cancelling its linked Pick List.").format(
                frappe.bold(name)))
    frappe.db.sql("""
        update `tabDelivery Note Item` item
        inner join `tabDelivery Note` dn on dn.name = item.parent
        set item.against_pick_list = NULL, item.pick_list_item = NULL
        where item.against_pick_list = %s and dn.docstatus = 0
    """, pick_list)
