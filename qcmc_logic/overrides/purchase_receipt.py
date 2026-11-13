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
	@property
	def custom_warehouse_allocation(self):
		from qcmc_logic.wrr_allocation import get_allocation_grid_rows
		return get_allocation_grid_rows(self)

	def before_validate(self):
		from qcmc_logic.wrr_allocation import prepare_receipt
		prepare_receipt(self)

	def validate_putaway_capacity(self):
		from qcmc_logic.wrr_allocation import uses_allocation
		if not uses_allocation(self):
			validate_dimension_putaway_capacity(self)

	def on_update(self):
		super().on_update()
		if self.docstatus == 0:
			from qcmc_logic.wrr_allocation import sync_allocations
			sync_allocations(self)

	def before_submit(self):
		from qcmc_logic.wrr_allocation import sync_allocations
		sync_allocations(self, require_complete=True)

	def on_submit(self):
		super().on_submit()
		from qcmc_logic.wrr_allocation import submit_allocations
		submit_allocations(self)

	def before_cancel(self):
		from qcmc_logic.warehouse_capacity import lock_warehouses
		lock_warehouses(item.warehouse for item in self.items)
		super().before_cancel()

	def on_cancel(self):
		from qcmc_logic.wrr_allocation import cancel_allocations
		cancel_allocations(self)
		super().on_cancel()

	def on_trash(self):
		from qcmc_logic.wrr_allocation import delete_draft_allocations
		delete_draft_allocations(self)
		super().on_trash()
