from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import StockReconciliation


class CustomStockReconciliation(StockReconciliation):
    def validate_items_exist(self):
        if not self.items:
            return
        super().validate_items_exist()

    def validate_data(self):
        if not self.items:
            return
        super().validate_data()

    def remove_items_with_no_change(self):
        if not self.items:
            return
        super().remove_items_with_no_change()
