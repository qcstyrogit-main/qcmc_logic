import hashlib
import json
import uuid

import frappe
from frappe import _
from frappe.utils import bold, flt, now_datetime
from erpnext.stock.doctype.inventory_dimension.inventory_dimension import get_inventory_dimensions
from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import StockReconciliation
from erpnext.stock.utils import get_stock_balance
from qcmc_logic.overrides.putaway_rule_dimension import validate_dimension_putaway_capacity


def physical_count_location_key(result):
    return (
        result.item_code or "",
        result.warehouse or "",
        result.get("location") or result.inventory_location or result.inventory_location_id or "",
        result.get("batch_no") or "",
        result.get("serial_no") or "",
        result.uom or "",
    )


def latest_physical_count_results(results):
    """Return only the latest audit snapshot for every exact inventory key."""
    latest = {}
    for position, result in enumerate(results or []):
        key = physical_count_location_key(result)
        timestamp = str(result.get("submitted_at") or result.get("counted_at") or "")
        rank = (timestamp, int(result.get("idx") or 0), position)
        if key not in latest or rank >= latest[key][0]:
            latest[key] = (rank, result)
    return {key: ranked_result[1] for key, ranked_result in latest.items()}


def physical_count_summary_key(result):
    return (
        result.item_code or "",
        result.warehouse or "",
        result.get("batch_no") or "",
        result.get("serial_no") or "",
        result.uom or "",
    )


class CustomStockReconciliation(StockReconciliation):
    def validate(self):
        if self.get("custom_physical_count"):
            self.purpose = "Stock Reconciliation"
            if self.workflow_state == "For Recon":
                self.capture_for_recon_count_corrections()
            if self.workflow_state == "Close Inventory":
                self.add_missing_location_zero_counts()
            self.rebuild_physical_count_summary()
        super().validate()
        if self.get("custom_physical_count"):
            self.difference_amount = 0

    def capture_for_recon_count_corrections(self):
        """Preserve scanner history when a reviewer changes a physical count."""
        results = self.get("custom_physical_count_results") or []
        latest = latest_physical_count_results(results)
        corrections = []

        for result in results:
            if not result.name or result.is_new():
                continue
            previous_count = frappe.db.get_value(
                "QCMC Physical Count Result", result.name, "physical_count"
            )
            if previous_count is None or flt(previous_count) == flt(result.physical_count):
                continue
            latest_result = latest.get(physical_count_location_key(result))
            corrected_count = flt(result.physical_count)
            if corrected_count < 0:
                frappe.throw(_("Physical Count cannot be negative."))

            # Restore the immutable scanner snapshot and append a reviewed snapshot.
            result.physical_count = flt(previous_count)
            result.status = "Old Count"
            result.adjustment_status = "Old Count"
            if latest_result and latest_result is not result:
                latest_result.status = "Old Count"
                latest_result.adjustment_status = "Old Count"
            values = result.as_dict(no_nulls=False)
            for fieldname in (
                "name", "owner", "creation", "modified", "modified_by", "docstatus",
                "idx", "parent", "parentfield", "parenttype",
            ):
                values.pop(fieldname, None)
            values.update({
                "submission_id": f"ERP-CORRECTION-{uuid.uuid4()}",
                "physical_count": corrected_count,
                "quantity_delta": corrected_count - flt(previous_count),
                "variance": corrected_count - flt(result.erp_quantity_before),
                "adjustment_document_type": "",
                "adjustment_document": "",
                "adjustment_status": "Pending",
                "scanner_user": frappe.session.user,
                "scanner_full_name": (
                    frappe.get_cached_value("User", frappe.session.user, "full_name")
                    or frappe.session.user
                ),
                "device_id": "ERP Review",
                "counted_at": now_datetime(),
                "submitted_at": now_datetime(),
                "transaction_count": 1,
                "scan_history_json": json.dumps({
                    "source": "ERP For Recon review",
                    "previous_physical_count": flt(previous_count),
                    "corrected_physical_count": corrected_count,
                    "reviewed_by": frappe.session.user,
                    "reviewed_at": str(now_datetime()),
                }),
                "status": "Pending adjustment",
            })
            corrections.append(values)

        for values in corrections:
            self.append("custom_physical_count_results", values)

    def add_missing_location_zero_counts(self):
        """Infer zero counts only while closing a completed physical count."""
        results = self.get("custom_physical_count_results") or []
        counted_locations = set()
        scopes = set()
        automatic_rows = {}

        for result in results:
            location = result.get("location") or result.inventory_location
            if not result.item_code or not result.warehouse or not location:
                continue
            scope = (result.item_code, result.warehouse, result.uom or "")
            scopes.add(scope)
            key = (result.item_code, result.warehouse, location)
            if str(result.submission_id or "").startswith("AUTO-ZERO-"):
                automatic_rows[key] = result
            else:
                counted_locations.add(key)

        for item_code, warehouse, uom in sorted(scopes):
            balances = frappe.db.sql(
                """
                select location, coalesce(sum(actual_qty), 0) as quantity
                  from `tabStock Ledger Entry`
                 where item_code = %(item_code)s
                   and warehouse = %(warehouse)s
                   and is_cancelled = 0
                   and ifnull(location, '') != ''
                 group by location
                having coalesce(sum(actual_qty), 0) > 0.000000001
                """,
                {"item_code": item_code, "warehouse": warehouse},
                as_dict=True,
            )
            for balance in balances:
                key = (item_code, warehouse, balance.location)
                if key in counted_locations:
                    if key in automatic_rows:
                        automatic_rows[key].status = "Old Count"
                        automatic_rows[key].adjustment_status = "Old Count"
                    continue

                quantity = flt(balance.quantity)
                existing = automatic_rows.get(key)
                if existing:
                    existing.erp_quantity_before = quantity
                    existing.physical_count = 0
                    existing.variance = -quantity
                    existing.status = "Pending adjustment"
                    existing.adjustment_status = "Pending"
                    continue

                digest = hashlib.sha256(
                    f"{self.name}|{item_code}|{warehouse}|{balance.location}".encode()
                ).hexdigest()[:24]
                self.append("custom_physical_count_results", {
                    "submission_id": f"AUTO-ZERO-{digest}",
                    "item_code": item_code,
                    "item_name": frappe.get_cached_value("Item", item_code, "item_name") or item_code,
                    "warehouse": warehouse,
                    "inventory_location": balance.location,
                    "inventory_location_id": balance.location,
                    "location": balance.location,
                    "location_name": frappe.db.get_value(
                        "Storage Location", balance.location, "location_name"
                    ) or balance.location,
                    "uom": uom or frappe.get_cached_value("Item", item_code, "stock_uom"),
                    "erp_quantity_before": quantity,
                    "physical_count": 0,
                    "variance": -quantity,
                    "adjustment_status": "Pending",
                    "scanner_user": frappe.session.user,
                    "scanner_full_name": "System inferred zero",
                    "device_id": "ERP Auto-Zero",
                    "counted_at": now_datetime(),
                    "submitted_at": now_datetime(),
                    "transaction_count": 0,
                    "scan_history_json": json.dumps({
                        "source": "ERP current location balance",
                        "reason": "Location absent from completed physical count",
                    }),
                    "status": "Pending adjustment",
                })

    def rebuild_physical_count_summary(self):
        """Build one effective Item row from the latest count at each location."""
        latest_by_location = latest_physical_count_results(
            self.get("custom_physical_count_results") or []
        )
        effective_totals = {}
        for result in latest_by_location.values():
            key = physical_count_summary_key(result)
            effective_totals[key] = flt(effective_totals.get(key)) + flt(result.physical_count)

        # Preserve manually entered/unrelated reconciliation rows. For keys covered
        # by Physical Count, retain one row and replace its quantity with the latest
        # effective total across distinct Storage Locations.
        existing_by_key = {}
        unrelated_rows = []
        for row in self.items or []:
            key = (
                row.item_code or "",
                row.warehouse or "",
                row.get("batch_no") or "",
                row.get("serial_no") or "",
                row.stock_uom or "",
            )
            if key in effective_totals and key not in existing_by_key:
                existing_by_key[key] = row
            elif key not in effective_totals:
                unrelated_rows.append(row.as_dict())

        rebuilt_rows = unrelated_rows
        for (item_code, warehouse, batch_no, serial_no, uom), quantity in sorted(effective_totals.items()):
            bin_balance = frappe.db.get_value(
                "Bin",
                {"item_code": item_code, "warehouse": warehouse},
                ["actual_qty", "valuation_rate"],
                as_dict=True,
            ) or {}
            valuation_rate = flt(bin_balance.get("valuation_rate"))
            row = existing_by_key.get((item_code, warehouse, batch_no, serial_no, uom))
            values = row.as_dict() if row else {}
            values.update({
                "item_code": item_code,
                "warehouse": warehouse,
                "qty": effective_totals[(item_code, warehouse, batch_no, serial_no, uom)],
                "current_qty": flt(bin_balance.get("actual_qty")),
                "valuation_rate": valuation_rate,
                "current_valuation_rate": valuation_rate,
                "stock_uom": uom or frappe.get_cached_value("Item", item_code, "stock_uom"),
                "batch_no": batch_no,
                "serial_no": serial_no,
            })
            if "location" in values:
                values["location"] = None
            rebuilt_rows.append(values)

        self.set("items", [])
        for values in rebuilt_rows:
            self.append("items", values)

    def validate_items_exist(self):
        if not self.items:
            return
        super().validate_items_exist()

    def validate_data(self):
        if not self.items:
            return

        def _get_msg(row_num, msg):
            return _("Row #{0}:").format(row_num) + " " + msg

        self.validation_messages = []
        item_warehouse_combinations = []
        default_currency = frappe.db.get_default("currency")

        for row in self.items:
            key = [row.item_code, row.warehouse]
            for field in ["serial_no", "batch_no"]:
                if row.get(field):
                    key.append(row.get(field))

            for dimension in get_inventory_dimensions():
                if row.get(dimension.get("fieldname")):
                    key.append(row.get(dimension.get("fieldname")))

            if key in item_warehouse_combinations:
                self.validation_messages.append(
                    _get_msg(row.idx, _("Same item, warehouse, batch, and bin location combination already entered."))
                )
            else:
                item_warehouse_combinations.append(key)

            self.validate_item(row.item_code, row)

            if row.serial_no and not row.qty:
                self.validation_messages.append(
                    _get_msg(
                        row.idx,
                        f"Quantity should not be zero for the {bold(row.item_code)} since serial nos are specified",
                    )
                )

            if row.qty in ["", None] and row.valuation_rate in ["", None]:
                self.validation_messages.append(
                    _get_msg(row.idx, _("Please specify either Quantity or Valuation Rate or both"))
                )

            if flt(row.qty) < 0:
                self.validation_messages.append(_get_msg(row.idx, _("Negative Quantity is not allowed")))

            if flt(row.valuation_rate) < 0:
                self.validation_messages.append(
                    _get_msg(row.idx, _("Negative Valuation Rate is not allowed"))
                )

            if row.qty and row.valuation_rate in ["", None]:
                row.valuation_rate = get_stock_balance(
                    row.item_code,
                    row.warehouse,
                    self.posting_date,
                    self.posting_time,
                    with_valuation_rate=True,
                )[1]
                if not row.valuation_rate:
                    buying_rate = frappe.db.get_value(
                        "Item Price",
                        {"item_code": row.item_code, "buying": 1, "currency": default_currency},
                        "price_list_rate",
                    )
                    row.valuation_rate = buying_rate or frappe.get_value("Item", row.item_code, "valuation_rate")

        if self.validation_messages:
            for msg in self.validation_messages:
                frappe.msgprint(msg)
            raise frappe.ValidationError(self.validation_messages)

    def remove_items_with_no_change(self):
        if self.get("custom_physical_count") or not self.items:
            return
        super().remove_items_with_no_change()

    def before_submit(self):
        if not self.get("custom_physical_count"):
            return
        from qcmc_logic.api.stock_reconciliation import post_pending_pcount_adjustments

        post_pending_pcount_adjustments(self)
        self.rebuild_physical_count_summary()
        self.difference_amount = 0

    def on_submit(self):
        if self.get("custom_physical_count"):
            # Location-specific variance was posted by before_submit. The standard
            # summary rows are audit-only and must never create a second ledger entry.
            return
        super().on_submit()

    def on_cancel(self):
        if self.get("custom_physical_count"):
            # This audit document owns no ledger entries of its own. Linked
            # adjustment Stock Entries must be cancelled explicitly if required.
            return
        super().on_cancel()

    def validate_putaway_capacity(self):
        if self.get("custom_physical_count"):
            return
        validate_dimension_putaway_capacity(self)
