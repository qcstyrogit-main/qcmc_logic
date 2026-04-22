import frappe
from erpnext.stock.utils import get_incoming_rate
from erpnext.accounts.general_ledger import make_reverse_gl_entries
from qcmc_logic.utils import get_user_allowed_warehouses
from frappe.utils import now, nowdate, cint
from erpnext.stock.stock_ledger import make_sl_entries


@frappe.whitelist()


def validate_transfer_type_rules(doc, method=None):
    if not doc.source_warehouse or not doc.target_warehouse or not doc.transfer_type:
        return

    if doc.source_warehouse == doc.target_warehouse:
        frappe.throw("Source Warehouse and Target Warehouse cannot be the same.")

    source_company = frappe.db.get_value("Warehouse", doc.source_warehouse, "company")
    target_company = frappe.db.get_value("Warehouse", doc.target_warehouse, "company")

    if doc.transfer_type == "Intercompany Warehouse Transfer" and source_company == target_company:
        frappe.throw("Intercompany Warehouse Transfer requires source and target warehouses from different companies.")

    if doc.transfer_type == "Provincial Warehouse Transfer":
        is_province = frappe.db.get_value("Warehouse", doc.target_warehouse, "custom_is_province")
        if not cint(is_province):
            frappe.throw("Provincial Warehouse Transfer requires a provincial target warehouse.")


def validate_update_after_submit(doc, method):
    if doc.transfer_status == "Received":
        frappe.throw("Cannot update a Warehouse Transfer after it has been marked as 'Received'.") 
    if doc.transfer_status == "Transferred":
        allowed_whs = get_user_allowed_warehouses(frappe.session.user)
        if doc.source_warehouse in allowed_whs and doc.target_warehouse not in allowed_whs:
            frappe.throw("You cannot modify this transfer while in 'Transferred' state, "
                         "since you only have access to the source warehouse.")


def on_submit(doc, method=None):
    """Handles workflow transitions while document is still in Draft (docstatus = 0)."""
    new_state = doc.transfer_status
    if new_state == "Transferred":   # Example: Draft → Transferred
        create_source_stock_entry(doc.name)
        if doc.source_company != doc.target_company:
            create_intercompany_gl(doc.name, source=True)


def on_update_after_submit(doc, method=None):
    """Handles workflow transitions after document is submitted (docstatus = 1)."""
    new_state = doc.transfer_status
    if new_state == "Received":   # Example: Transferred → Received
        create_target_stock_entry(doc.name)
        if doc.source_company != doc.target_company:
            create_intercompany_gl(doc.name, source=False)


def get_in_transit_wh(warehouse):
    return frappe.db.get_value("Warehouse", warehouse, "default_in_transit_warehouse")

def create_source_stock_entry(docname):
    doc = frappe.get_doc("Warehouse Transfer", docname)
    try:
        sl_entries = []
        posting_date = doc.date_transferred or nowdate()
        posting_time = now()

        for item in doc.transfer_items:
            qty = float(item.issued_qty or 0)
            if qty <= 0:
                continue

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
        sl_entries = []
        posting_date = doc.date_transferred or nowdate()
        posting_time = now()

        for item in doc.transfer_items:
            qty = float(item.issued_qty or 0)
            if qty <= 0:
                continue

            # Build the SLE as a frappe._dict so code that uses row.warehouse works
            sle = frappe._dict({
                "item_code": item.item_code,
                "warehouse": doc.target_warehouse,          # required by some code paths
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
            })

            sl_entries.append(sle)

        if not sl_entries:
            frappe.msgprint(f"No valid items to post for Warehouse Transfer {doc.name}")
            return

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
        frappe.throw(f"Error creating source Stock Ledger Entry: {e}")

def create_intercompany_gl(docname, source=True):
    
    doc = frappe.get_doc("Warehouse Transfer", docname)

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
        # Get location from warehouse
        location = frappe.get_value(
            "Warehouse",
            doc.source_warehouse if source else doc.target_warehouse,
            "custom_location"
        )
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
                "posting_date": doc.date_transferred if source else doc.date_received,
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

    source_party = doc.source_company
    target_party = doc.target_company

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
            gl_entries.append({
                "account": src_rev,
                "debit": total_amount,
                "credit": 0,
                "company": company,
                "voucher_type": "Warehouse Transfer",
                "voucher_no": doc.name,
                "posting_date": posting_date,
                "party_type": "Customer",
                "location": location,
                "party": source_party,
                "remarks": f"Source side entry for WT {doc.name}"
            })
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
            gl_entries.append({
                "account": tgt_exp,
                "credit": total_amount,
                "debit": 0,
                "company": company,
                "voucher_type": "Warehouse Transfer",
                "voucher_no": doc.name,
                "posting_date": posting_date,
                "party_type": "Supplier",
                "party": target_party,
                "remarks": f"Target side entry for WT {doc.name}",
                "location": location
            })
    
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
                "posting_time": now(),
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
            }], allow_negative_stock=True)

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
    except Exception as e:
        frappe.log_error(
            f"Failed to delete GL Entries for Warehouse Transfer {doc.name}: {str(e)}",
            "Warehouse Transfer Delete Cascade"
        )
