import frappe

from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt
from qcmc_logic.overrides.putaway_rule_dimension import (
	apply_dimension_putaway_rule,
	validate_dimension_putaway_capacity,
)


def _make_erpnext_purchase_invoice(source_name, target_doc=None, args=None):
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

	return make_purchase_invoice(source_name, target_doc, args)


@frappe.whitelist()
def make_purchase_invoice(source_name, target_doc=None, args=None):
	"""Map a Purchase Receipt and carry its supplier invoice details to the invoice."""
	purchase_invoice = _make_erpnext_purchase_invoice(source_name, target_doc, args)
	invoice_number, posting_date = frappe.db.get_value(
		"Purchase Receipt",
		source_name,
		["custom_invoice_number", "posting_date"],
	)

	purchase_invoice.bill_no = invoice_number
	purchase_invoice.bill_date = posting_date
	purchase_invoice.posting_date = posting_date
	return purchase_invoice


class CustomPurchaseReceipt(PurchaseReceipt):
	def before_validate(self):
		if self.get("items") and self.apply_putaway_rule and not self.get("is_return"):
			apply_dimension_putaway_rule(self.doctype, self.get("items"), self.company)

	def validate_putaway_capacity(self):
		validate_dimension_putaway_capacity(self)
