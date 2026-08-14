import frappe
from frappe import _
from frappe.utils import bold, flt
from erpnext.stock.doctype.inventory_dimension.inventory_dimension import get_inventory_dimensions
from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import StockReconciliation
from erpnext.stock.utils import get_stock_balance
from qcmc_logic.overrides.putaway_rule_dimension import validate_dimension_putaway_capacity


SCAN_LOCATION_FIELDS = ("bldg", "aisle", "rack", "bin")


class CustomStockReconciliation(StockReconciliation):
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

            for field in SCAN_LOCATION_FIELDS:
                key.append(row.get(field) or "")

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
        if not self.items:
            return
        super().remove_items_with_no_change()

    def validate_putaway_capacity(self):
        validate_dimension_putaway_capacity(self)
