from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry

from qcmc_logic.overrides.putaway_rule_dimension import (
	RECEIVING_STOCK_ENTRY_PURPOSES,
	apply_dimension_putaway_rule,
	validate_dimension_putaway_capacity,
)


class CustomStockEntry(StockEntry):
	def before_validate(self):
		apply_rule = self.apply_putaway_rule and self.purpose in RECEIVING_STOCK_ENTRY_PURPOSES

		if self.get("items") and apply_rule:
			apply_dimension_putaway_rule(self.doctype, self.get("items"), self.company, purpose=self.purpose)

		if self.project:
			for item in self.items:
				if not item.project:
					item.project = self.project

	def validate_putaway_capacity(self):
		validate_dimension_putaway_capacity(self)
