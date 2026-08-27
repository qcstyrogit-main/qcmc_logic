import frappe
from erpnext.stock.utils import get_incoming_rate
from erpnext.accounts.general_ledger import make_reverse_gl_entries
from qcmc_logic.utils import (
    get_user_allowed_warehouses,
    _get_material_request_warehouses,
    _get_warehouse_is_province,
)
from frappe.utils import nowdate, nowtime, cint, flt, getdate
from erpnext.stock.stock_ledger import make_sl_entries
from qcmc_logic.overrides.putaway_rule_dimension import (
    get_dimension_putaway_for_item,
    get_dimension_values,
    get_rule_dimension_values,
)
from qcmc_logic.overrides.pick_list import (
    update_pick_list_progress,
    validate_pick_list_references,
)


@frappe.whitelist()
def validate(self):
    if frappe.session.user == "Administrator":
        return

    allowed = get_user_allowed_warehouses(frappe.session.user, require_transact=True)

    if self.source_warehouse not in allowed:
        frappe.throw("You are not allowed to transact from this source warehouse.")


def _skip_warehouse_access_checks():
    return frappe.session.user == "Administrator"


def _set_company_fields(doc):
    if doc.source_warehouse:
        doc.source_company = frappe.db.get_value("Warehouse", doc.source_warehouse, "company")
    if doc.target_warehouse:
        doc.target_company = frappe.db.get_value("Warehouse", doc.target_warehouse, "company")


def _get_warehouse_location(warehouse):
    if not warehouse:
        return None
    return frappe.db.get_value("Warehouse", warehouse, "custom_location")


def _get_company_dimension_default(fieldname, company):
    if not company:
        return None

    dimension = frappe.db.get_value(
        "Accounting Dimension",
        {"fieldname": fieldname, "disabled": 0},
        "name",
    )
    if not dimension:
        return None

    return frappe.db.get_value(
        "Accounting Dimension Detail",
        {"parent": dimension, "company": company},
        "default_dimension",
    )


def _get_location_for_dimension(warehouse, company):
    location = _get_warehouse_location(warehouse)
    if location:
        return location

    return _get_company_dimension_default("location", company)


def _require_location_for_dimension(warehouse, company):
    location = _get_location_for_dimension(warehouse, company)
    if not location:
        frappe.throw(
            "Location is required for Warehouse Transfer accounting. "
            "Set Custom Location on Warehouse {0} or set a default Location "
            "in Accounting Dimension for company {1}.".format(warehouse, company)
        )
    return location


def _validate_source_warehouse_access(doc):
    if _skip_warehouse_access_checks() or not doc.source_warehouse:
        return

    allowed = set(get_user_allowed_warehouses(frappe.session.user, require_transact=True))
    if doc.source_warehouse not in allowed:
        frappe.throw("You are not allowed to create transfers from this source warehouse.")


def _validate_material_request_references(doc):
    reference_names = []
    reference_names.extend(
        _get_row_material_request(row) for row in (doc.get("transfer_items") or []) if _get_row_material_request(row)
    )

    for material_request in set(reference_names):
        mr = frappe.db.get_value(
            "Material Request",
            material_request,
            ["docstatus", "company", "material_request_type"],
            as_dict=True,
        )
        if not mr:
            frappe.throw(f"Material Request {material_request} does not exist.")
        if mr.docstatus != 1:
            frappe.throw(f"Material Request {material_request} must be submitted.")
        if mr.material_request_type != "Material Transfer":
            frappe.throw(
                f"Material Request {material_request} must be a Material Transfer request."
            )
        if doc.source_company and doc.target_company and mr.company not in (doc.source_company, doc.target_company):
            frappe.throw(
                f"Material Request {material_request} belongs to {mr.company}, "
                "which is not part of this transfer."
            )

        mr_source, mr_target = _get_material_request_warehouses(material_request)
        if doc.source_warehouse and mr_source and mr_source != doc.source_warehouse:
            frappe.throw(
                f"Material Request {material_request} source warehouse does not match this transfer."
            )
        if doc.target_warehouse and mr_target and mr_target != doc.target_warehouse:
            frappe.throw(
                f"Material Request {material_request} target warehouse does not match this transfer."
            )


def validate_transfer_type_rules(doc, method=None):
    _set_company_fields(doc)

    if not doc.source_warehouse or not doc.target_warehouse or not doc.transfer_type:
        return

    if doc.source_warehouse == doc.target_warehouse:
        frappe.throw("Source Warehouse and Target Warehouse cannot be the same.")

    source_company = doc.source_company
    target_company = doc.target_company
    source_warehouse_type = frappe.db.get_value("Warehouse", doc.source_warehouse, "warehouse_type")
    target_warehouse_type = frappe.db.get_value("Warehouse", doc.target_warehouse, "warehouse_type")
    target_is_province = _get_warehouse_is_province(doc.target_warehouse)

    if doc.transfer_type == "Warehouse Transfer":
        if source_company != target_company:
            frappe.throw("Warehouse Transfer requires source and target warehouses from the same company.")
        if source_warehouse_type != target_warehouse_type:
            frappe.throw("Warehouse Transfer requires source and target warehouses with the same warehouse type.")
        if target_is_province:
            frappe.throw("Warehouse Transfer cannot use a provincial target warehouse.")

    elif doc.transfer_type == "Intercompany Warehouse Transfer":
        if source_company == target_company:
            frappe.throw("Intercompany Warehouse Transfer requires source and target warehouses from different companies.")
        if source_warehouse_type != target_warehouse_type:
            frappe.throw("Intercompany Warehouse Transfer requires source and target warehouses with the same warehouse type.")
        if target_is_province:
            frappe.throw("Intercompany Warehouse Transfer cannot use a provincial target warehouse.")

    elif doc.transfer_type == "Provincial Warehouse Transfer":
        if not target_is_province:
            frappe.throw("Provincial Warehouse Transfer requires a provincial target warehouse.")

    _validate_source_warehouse_access(doc)
    _validate_material_request_references(doc)
    validate_pick_list_references(doc)


def validate_update_after_submit(doc, method):
    previous = doc.get_doc_before_save()

    if doc.transfer_status == "Received":
        if previous and previous.transfer_status == "Received":
            frappe.throw("Cannot update a Warehouse Transfer after it has been marked as 'Received'.")
        _validate_receiving_update(doc, previous)
    elif previous and previous.transfer_status == "Transferred" and doc.transfer_status == "Transferred":
        _validate_receiving_update(doc, previous)


def _validate_receiving_update(doc, previous):
    if _skip_warehouse_access_checks():
        return

    transact_whs = set(get_user_allowed_warehouses(frappe.session.user, require_transact=True))
    if doc.target_warehouse not in transact_whs:
        frappe.throw("You are not allowed to receive transfers for this target warehouse.")

    if not previous:
        return

    protected_fields = (
        "transfer_type",
        "source_warehouse",
        "source_company",
        "target_warehouse",
        "target_company",
        "date_transferred",
    )
    for field in protected_fields:
        if not _same_protected_value(doc.get(field), previous.get(field), field):
            frappe.throw(f"Receivers cannot modify {frappe.unscrub(field)}.")

    previous_items = {row.name: row for row in (previous.get("transfer_items") or [])}
    current_items = {row.name: row for row in (doc.get("transfer_items") or []) if row.name}

    deleted = [row.item_code for name, row in previous_items.items() if name not in current_items]
    if deleted:
        frappe.throw("Receivers cannot delete transferred item rows.")

    for row in doc.get("transfer_items") or []:
        if flt(row.received_qty) < 0:
            frappe.throw("Received Qty cannot be negative.")

        if row.name in previous_items:
            previous_row = previous_items[row.name]
            for field in (
                "item_code",
                "item_name",
                "uom",
                "issued_qty",
                "reference_doc",
                "material_request",
                "material_request_item",
                "against_pick_list",
                "pick_list_item",
            ):
                if row.get(field) != previous_row.get(field):
                    frappe.throw("Receivers can only modify Received Qty on existing item rows.")
        else:
            if not row.item_code:
                frappe.throw("Item is required for receiver-added rows.")
            if flt(row.issued_qty) != 0:
                frappe.throw("Receiver-added item rows must have Issued Qty set to 0.")


def _same_protected_value(current, previous, fieldname):
    if fieldname in {"date_transferred"}:
        if not current and not previous:
            return True
        return getdate(current) == getdate(previous)

    return current == previous


def on_submit(doc, method=None):
    """Post the source side when the transfer is submitted.

    Workflow can set transfer_status around the submit event, so source posting
    is intentionally based on docstatus and guarded by existing SLE checks.
    """
    if doc.docstatus == 1:
        create_source_stock_entry(doc.name)
        update_material_request_progress(doc.name)
        update_pick_list_progress(doc.name)
        if doc.source_company != doc.target_company:
            create_intercompany_gl(doc.name, source=True)


def on_update_after_submit(doc, method=None):
    """Handles workflow transitions after document is submitted (docstatus = 1)."""
    previous = doc.get_doc_before_save()
    validate_update_after_submit(doc, method)

    new_state = doc.transfer_status
    previous_state = previous.transfer_status if previous else None

    if new_state == "Received" and previous_state != "Received":
        create_source_stock_entry(doc.name)
        create_target_stock_entry(doc.name)
        update_material_request_progress(doc.name)
        update_pick_list_progress(doc.name)
        if doc.source_company != doc.target_company:
            create_intercompany_gl(doc.name, source=False)


def get_in_transit_wh(warehouse):
    return frappe.db.get_value("Warehouse", warehouse, "default_in_transit_warehouse")


def _get_row_material_request(row):
    material_request = row.get("material_request")
    if material_request:
        return material_request

    # Backward compatibility for rows created before Reference Doc became Remarks.
    reference_doc = row.get("reference_doc")
    if reference_doc and frappe.db.exists("Material Request", reference_doc):
        return reference_doc

    return None


def _has_stock_ledger_entries(doc, warehouse, positive):
    filters = {
        "voucher_type": "Warehouse Transfer",
        "voucher_no": doc.name,
        "warehouse": warehouse,
        "is_cancelled": 0,
    }
    if positive:
        filters["actual_qty"] = [">", 0]
    else:
        filters["actual_qty"] = ["<", 0]

    return frappe.db.exists("Stock Ledger Entry", filters)


def _has_gl_entries(doc, source=True):
    company = doc.source_company if source else doc.target_company
    side = "Source" if source else "Target"
    return frappe.db.exists(
        "GL Entry",
        {
            "voucher_type": "Warehouse Transfer",
            "voucher_no": doc.name,
            "company": company,
            "remarks": ["like", f"{side} side entry for WT {doc.name}%"],
            "is_cancelled": 0,
        },
    )

def create_source_stock_entry(docname):
    doc = frappe.get_doc("Warehouse Transfer", docname)
    try:
        if _has_stock_ledger_entries(doc, doc.source_warehouse, positive=False):
            return

        sl_entries = []
        posting_date = doc.date_transferred or nowdate()
        posting_time = nowtime()

        for item in doc.transfer_items:
            qty = float(item.issued_qty or 0)
            if qty <= 0:
                continue

            location = _require_location_for_dimension(doc.source_warehouse, doc.source_company)
            # Build the SLE as a frappe._dict so code that uses row.warehouse works
            sle = frappe._dict({
                "item_code": item.item_code,
                "warehouse": doc.source_warehouse,          # required by some code paths
                "posting_date": posting_date,
                "posting_time": posting_time,
                "voucher_type": "Warehouse Transfer",       # keep audit trail
                "voucher_no": doc.name,
                "voucher_detail_no": item.name,             # safe identifier
                "actual_qty": -1 * qty,                     # negative for source issue
                "company": doc.source_company,
                "stock_uom": frappe.get_cached_value("Item", item.item_code, "stock_uom") \
                             or frappe.db.get_value("Item", item.item_code, "stock_uom"),
                # valuation-related fields (set to 0 if you handle accounting elsewhere)
                "incoming_rate": 0.0,
                "valuation_rate": 0.0,
                "stock_value_difference": 0.0,
                "is_cancelled": 0,
                "location": location,
            })

            sl_entries.append(sle)

        if not sl_entries:
            frappe.msgprint(f"No valid items to post for Warehouse Transfer {doc.name}")
            return

        # Debug: log first SLE structure to help trace problems in logs
        try:
            frappe.logger().info(f"[create_source_stock_entry] first_sle: {sl_entries[0]}")
        except Exception:
            pass

        # Create SLEs (this updates Bin and inserts Stock Ledger Entries)
        make_sl_entries(sl_entries, allow_negative_stock=True)

        frappe.msgprint(f"✅ Source Stock Ledger Entries created for Warehouse Transfer {doc.name}")

    except Exception as e:
        # rethrow with simple message for UI
        frappe.throw(f"Error creating source Stock Ledger Entry: {e}")

def create_target_stock_entry(docname):

    doc = frappe.get_doc("Warehouse Transfer", docname)
    try:
        if _has_stock_ledger_entries(doc, doc.target_warehouse, positive=True):
            return

        sl_entries = []
        posting_date = doc.date_received or nowdate()
        posting_time = nowtime()

        for item in doc.transfer_items:
            qty = float(item.received_qty or 0)
            if qty <= 0:
                continue

            location = _require_location_for_dimension(doc.target_warehouse, doc.target_company)
            putaway_rule = get_dimension_putaway_for_item(
                item.item_code,
                doc.target_company,
                source_warehouse=doc.source_warehouse,
                item_dimensions=get_dimension_values(item),
            )
            target_warehouse = putaway_rule.warehouse if putaway_rule else doc.target_warehouse
            # Build the SLE as a frappe._dict so code that uses row.warehouse works
            sle = frappe._dict({
                "item_code": item.item_code,
                "warehouse": target_warehouse,          # required by some code paths
                "posting_date": posting_date,
                "posting_time": posting_time,
                "voucher_type": "Warehouse Transfer",       # keep audit trail
                "voucher_no": doc.name,
                "voucher_detail_no": item.name,             # safe identifier
                "actual_qty": qty,                     # negative for source issue
                "company": doc.target_company,
                "stock_uom": frappe.get_cached_value("Item", item.item_code, "stock_uom") \
                             or frappe.db.get_value("Item", item.item_code, "stock_uom"),
                # valuation-related fields (set to 0 if you handle accounting elsewhere)
                "incoming_rate": 0.0,
                "valuation_rate": 0.0,
                "stock_value_difference": 0.0,
                "is_cancelled": 0,
                "location": location,
            })
            if putaway_rule:
                sle.update(get_rule_dimension_values(putaway_rule))

            sl_entries.append(sle)

        if not sl_entries:
            frappe.throw(
                f"No received quantities to post for Warehouse Transfer {doc.name}. "
                "Save Received Qty before marking the transfer as Received."
            )

        # Debug: log first SLE structure to help trace problems in logs
        try:
            frappe.logger().info(f"[create_target_stock_entry] first_sle: {sl_entries[0]}")
        except Exception:
            pass

        # Create SLEs (this updates Bin and inserts Stock Ledger Entries)
        make_sl_entries(sl_entries, allow_negative_stock=True)

        frappe.msgprint(f"✅ Target Stock Ledger Entries created for Warehouse Transfer {doc.name}")

    except Exception as e:

        # rethrow with simple message for UI
        frappe.throw(f"Error creating target Stock Ledger Entry: {e}")

def create_intercompany_gl(docname, source=True):

    doc = frappe.get_doc("Warehouse Transfer", docname)
    if _has_gl_entries(doc, source=source):
        return

    totals_by_mapping = {}
    missing_mappings = set()
    # Store cost_center and location per mapping key for later use
    mapping_meta = {}

    for row in doc.transfer_items:
        inventory_group = frappe.get_value("Item", row.item_code, "custom_inventory_group")
        # Get selling cost center from Item Default
        cost_center = frappe.db.get_value(
            "Item Default",
            {"parent": row.item_code, "company": doc.source_company if source else doc.target_company},
            "selling_cost_center"
        ) or frappe.get_value("Company", doc.source_company if source else doc.target_company, "cost_center")
        warehouse = doc.source_warehouse if source else doc.target_warehouse
        company = doc.source_company if source else doc.target_company
        location = _require_location_for_dimension(warehouse, company)
        mapping = frappe.get_value(
            "Intercompany Expense Mapping",
            {
                "source_company": doc.source_company,
                "target_company": doc.target_company,
                "inventory_group": inventory_group,
                "is_active": 1
            },
            [
                "source_inv_account",
                "source_cogs_account",
                "source_revenue_account",
                "source_expense_account",
                "target_revenue_account",
                "target_expense_account"
            ],
            as_dict=True
        )


        if mapping:
            frappe.log(f"✅ Mapping found for {inventory_group}:\n{frappe.as_json(mapping, indent=2)}")
        else:
            frappe.log(f"❌ No mapping found for {inventory_group} ({doc.source_company} → {doc.target_company})")
        if not mapping:
            missing_mappings.add(str(inventory_group))
            continue

        qty = (row.issued_qty or 0) if source else (row.received_qty or 0)
        rate = get_incoming_rate(
            {
                "item_code": row.item_code,
                "warehouse": doc.source_warehouse ,
                "posting_date": (doc.date_transferred if source else doc.date_received) or nowdate(),
                "posting_time": nowtime(),
                "company": doc.source_company
            },
            raise_error_if_no_rate=False,
        ) or 0.0
        amount = qty * rate

        key = (
            mapping.source_inv_account,
            mapping.source_cogs_account,
            mapping.source_revenue_account,
            mapping.source_expense_account,
            mapping.target_revenue_account,
            mapping.target_expense_account
        )
        totals_by_mapping.setdefault(key, 0.0)
        totals_by_mapping[key] += amount
        # Store cost_center and location for this mapping key
        mapping_meta[key] = {"cost_center": cost_center, "location": location}

    if missing_mappings:
        frappe.throw(f"⚠️ No active Intercompany Expense Mapping found for Inventory Group(s): "
                     f"{', '.join(sorted(missing_mappings))}")

    posting_date = doc.date_transferred if source else doc.date_received
    company = doc.source_company if source else doc.target_company

    gl_entries = []

    for accounts, total_amount in totals_by_mapping.items():
        src_inv, src_cogs, src_rev, src_exp, tgt_rev, tgt_exp = accounts
        meta = mapping_meta.get(accounts, {})
        cost_center = meta.get("cost_center")
        location = meta.get("location")
        frappe.log(f"🔎 Debug row for {row.item_code}: qty={qty}, rate={rate}, amount={amount}, source={source}")
        if not total_amount:
            continue

        if source:
            # Credit Inventory
            gl_entries.append({
                "account": src_inv,
                "credit": total_amount,
                "debit": 0,
                "company": company,
                "voucher_type": "Warehouse Transfer",
                "voucher_no": doc.name,
                "posting_date": posting_date,
                "location": location,
                "remarks": f"Source side entry for WT {doc.name}"
            })
            # Debit COGS (use cost_center and location)
            gl_entries.append({
                "account": src_cogs,
                "debit": total_amount,
                "credit": 0,
                "company": company,
                "voucher_type": "Warehouse Transfer",
                "voucher_no": doc.name,
                "posting_date": posting_date,
                "remarks": f"Source side entry for WT {doc.name}",
                "cost_center": cost_center,
                "location": location
            })
            # Credit Sales Revenue (use cost_center and location)
            gl_entries.append({
                "account": src_exp,
                "credit": total_amount,
                "debit": 0,
                "company": company,
                "voucher_type": "Warehouse Transfer",
                "voucher_no": doc.name,
                "posting_date": posting_date,
                "remarks": f"Source side entry for WT {doc.name}",
                "cost_center": cost_center,
                "location": location
            })
            # Debit Accounts Receivable
            gl_entries.append(_with_required_party({
                "account": src_rev,
                "debit": total_amount,
                "credit": 0,
                "company": company,
                "voucher_type": "Warehouse Transfer",
                "voucher_no": doc.name,
                "posting_date": posting_date,
                "location": location,
                "remarks": f"Source side entry for WT {doc.name}"
            }, company=doc.target_company, party_type="Customer"))
        else:
            # target company entries
            # Debit Inventory
            gl_entries.append({
                "account": tgt_rev,
                "debit": total_amount,
                "credit": 0,
                "company": company,
                "voucher_type": "Warehouse Transfer",
                "voucher_no": doc.name,
                "posting_date": posting_date,
                "location": location,
                "remarks": f"Target side entry for WT {doc.name}"
            })
            # Credit Accounts Payable (use location)
            gl_entries.append(_with_required_party({
                "account": tgt_exp,
                "credit": total_amount,
                "debit": 0,
                "company": company,
                "voucher_type": "Warehouse Transfer",
                "voucher_no": doc.name,
                "posting_date": posting_date,
                "remarks": f"Target side entry for WT {doc.name}",
                "location": location
            }, company=doc.source_company, party_type="Supplier"))

    if not gl_entries:
        frappe.throw("⚠️ No valid Intercompany mappings found. GL Entries not created.")

    for gle in gl_entries:
        gle_doc = frappe.get_doc({
            "doctype": "GL Entry",
            **gle
        })
        gle_doc.insert(ignore_permissions=True)
        gle_doc.submit()

    frappe.msgprint(f"✅ Intercompany GL Entries created for {doc.name}")


def _with_required_party(gl_entry, company, party_type):
    account_type = frappe.db.get_value("Account", gl_entry.get("account"), "account_type")
    required_party_type = None
    if account_type == "Receivable":
        required_party_type = "Customer"
    elif account_type == "Payable":
        required_party_type = "Supplier"

    if not required_party_type:
        return gl_entry

    if required_party_type != party_type:
        frappe.throw(
            "{0} is a {1} account, but Warehouse Transfer is trying to use {2} as party type.".format(
                frappe.bold(gl_entry.get("account")),
                account_type,
                party_type,
            )
        )

    party = _get_intercompany_party(company, party_type)
    if not party:
        frappe.throw(
            "Set up a {0} master for company {1} before posting intercompany Warehouse Transfer GL. "
            "The {2} account requires a valid {0} party.".format(
                party_type,
                frappe.bold(company),
                frappe.bold(gl_entry.get("account")),
            )
        )

    gl_entry["party_type"] = party_type
    gl_entry["party"] = party
    return gl_entry


def _get_intercompany_party(company, party_type):
    party_name_field = "customer_name" if party_type == "Customer" else "supplier_name"
    company_abbr = frappe.db.get_value("Company", company, "abbr")

    for value in (company, company_abbr):
        if not value:
            continue

        party = frappe.db.get_value(party_type, value, "name")
        if party:
            return party

        party = frappe.db.get_value(party_type, {party_name_field: value}, "name")
        if party:
            return party

    return None


def update_material_request_progress(docname):
    doc = frappe.get_doc("Warehouse Transfer", docname)
    material_requests = {
        _get_row_material_request(row)
        for row in (doc.get("transfer_items") or [])
        if _get_row_material_request(row)
    }

    for material_request in material_requests:
        mr = frappe.get_doc("Material Request", material_request)
        mr_item_names = [row.name for row in mr.get("items") or []]
        if not mr_item_names:
            continue

        transferred_by_item = frappe._dict(
            frappe.db.sql(
                """
                select
                    coalesce(wtd.material_request_item, mri.name) as material_request_item,
                    sum(wtd.issued_qty) as transferred_qty
                from `tabWarehouse Transfer Details` wtd
                inner join `tabWarehouse Transfer` wt on wt.name = wtd.parent
                left join `tabMaterial Request Item` mri
                    on mri.parent = coalesce(wtd.material_request, wtd.reference_doc)
                    and mri.item_code = wtd.item_code
                where
                    wt.docstatus = 1
                    and ifnull(wt.transfer_status, '') in ('Transferred', 'Received')
                    and (
                        wtd.material_request = %(material_request)s
                        or wtd.reference_doc = %(material_request)s
                    )
                    and coalesce(wtd.material_request_item, mri.name) in %(mr_item_names)s
                group by coalesce(wtd.material_request_item, mri.name)
                """,
                {
                    "material_request": material_request,
                    "mr_item_names": tuple(mr_item_names),
                },
            )
        )

        for item in mr.get("items") or []:
            qty = flt(transferred_by_item.get(item.name))
            frappe.db.set_value("Material Request Item", item.name, "ordered_qty", qty)

        mr.reload()
        mr._update_percent_field(
            {
                "target_dt": "Material Request Item",
                "target_parent_dt": mr.doctype,
                "target_parent_field": "per_ordered",
                "target_ref_field": "stock_qty",
                "target_field": "ordered_qty",
                "name": mr.name,
            },
            update_modified=True,
        )
        mr.reload()
        mr.set_status(update=True)

def on_cancel(doc, method):
    try:
        # make reverse_gl_entries automatically fetches and reverses all GL Entries
        make_reverse_gl_entries("Warehouse Transfer", doc.name, cancel_outstanding_cheques=False)
        # make reverse stock ledger entries
        sle_entries = frappe.get_all(
            "Stock Ledger Entry",
            filters={"voucher_type": "Warehouse Transfer", "voucher_no": doc.name, "is_cancelled": 0},
            pluck="name"
        )
        for sle in sle_entries:
            linked_sle = frappe.get_doc("Stock Ledger Entry", sle)
            make_sl_entries([{
                "item_code": linked_sle.item_code,
                "warehouse": linked_sle.warehouse,
                "posting_date": nowdate(),
                "posting_time": nowtime(),
                "voucher_type": "Warehouse Transfer",
                "voucher_no": doc.name,
                "voucher_detail_no": linked_sle.name,
                "actual_qty": -1 * linked_sle.actual_qty,
                "company": linked_sle.company,
                "stock_uom": linked_sle.stock_uom,
                "incoming_rate": linked_sle.incoming_rate,
                "valuation_rate": linked_sle.valuation_rate,
                "stock_value_difference": -1 * linked_sle.stock_value_difference,
                "is_cancelled": 1, #
                "location": getattr(linked_sle, "location", None)
                or _require_location_for_dimension(
                    linked_sle.warehouse,
                    linked_sle.company,
                ),
            }], allow_negative_stock=True)

        update_material_request_progress(doc.name)
        update_pick_list_progress(doc.name)

    except Exception as e:
        frappe.log_error(
            f"Failed to cancel GL Entries for Warehouse Transfer {doc.name}: {str(e)}",
            "Warehouse Transfer Cancel Cascade"
        )


def on_trash(doc, method):
    try:
        # Delete all GL Entries linked to this Warehouse Transfer
        gl_entries = frappe.get_all(
            "GL Entry",
            filters={"voucher_type": "Warehouse Transfer", "voucher_no": doc.name},
            pluck="name"
        )
        for gle in gl_entries:
            linked_doc = frappe.get_doc("GL Entry", gle)
            if linked_doc.docstatus in (0, 2):
                frappe.delete_doc("GL Entry", gle, force=1)
        # Delete all Stock Ledger Entries linked to this Warehouse Transfer
        sle_entries = frappe.get_all(
            "Stock Ledger Entry",
            filters={"voucher_type": "Warehouse Transfer", "voucher_no": doc.name},
            pluck="name"
        )
        for sle in sle_entries:
            linked_sle = frappe.get_doc("Stock Ledger Entry", sle)
            if linked_sle.docstatus in (0, 2):
                frappe.delete_doc("Stock Ledger Entry", sle, force=1)
        update_pick_list_progress(doc.name)
    except Exception as e:
        frappe.log_error(
            f"Failed to delete GL Entries for Warehouse Transfer {doc.name}: {str(e)}",
            "Warehouse Transfer Delete Cascade"
        )
