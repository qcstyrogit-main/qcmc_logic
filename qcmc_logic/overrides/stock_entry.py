import frappe
from frappe import _

from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry

from qcmc_logic.overrides.putaway_rule_dimension import (
	RECEIVING_STOCK_ENTRY_PURPOSES,
	apply_dimension_putaway_rule,
	validate_dimension_putaway_capacity,
)


class CustomStockEntry(StockEntry):
	def validate(self):
		if not self.get("items"):
			if self._action == "submit":
				frappe.throw(_("Stock Entry cannot be submitted without Items."), frappe.EmptyTableError)
			# Allow an operator to prepare and save the Stock Entry header as Draft.
			# Framework mandatory validation still protects all other required fields.
			self.validate_posting_time()
			self.validate_purpose()
			self.set_purpose_for_stock_entry()
			return
		super().validate()

	def before_validate(self):
		# Rows created or split by the scanner do not pass through the Desk Link
		# field fetch that normally populates item_code.weight_uom. Populate it on
		# the server so manual and scanner-created finished rows behave identically.
		weight_uoms = {}
		for item in self.get("items") or []:
			if not item.is_finished_item or item.get("custom_actual_weight_uom") or not item.item_code:
				continue
			if item.item_code not in weight_uoms:
				weight_uoms[item.item_code] = frappe.db.get_value("Item", item.item_code, "weight_uom")
			if weight_uoms[item.item_code]:
				item.custom_actual_weight_uom = weight_uoms[item.item_code]

		apply_rule = self.apply_putaway_rule and self.purpose in RECEIVING_STOCK_ENTRY_PURPOSES

		if self.get("items") and apply_rule:
			apply_dimension_putaway_rule(self.doctype, self.get("items"), self.company, purpose=self.purpose)

		if self.project:
			for item in self.items:
				if not item.project:
					item.project = self.project

	def validate_putaway_capacity(self):
		# Receive Finished Goods starts from an existing Draft Manufacture Stock
		# Entry. Its finished row is intentionally unallocated at draft creation;
		# the scanner API later resolves all Putaway Rules, splits the row, locks the
		# document, and submits it. Do not compare that unsplit total against only
		# the first rule while inserting/saving the draft. A direct manual Submit
		# still runs the normal capacity validation.
		if self.purpose == "Manufacture" and self._action != "submit":
			finished_rows = [row for row in self.items if row.is_finished_item and row.t_warehouse]
			if finished_rows and not any(row.putaway_rule or row.get("to_location") for row in finished_rows):
				return
		validate_dimension_putaway_capacity(self)

	def update_work_order(self):
		"""Preserve ERPNext updates and cover tracked final-goods receipts."""
		super().update_work_order()
		_sync_tracked_final_work_order(self)


def _sync_tracked_final_work_order(stock_entry):
	"""Synchronize final output when ERPNext skips tracked-semi Work Orders.

	ERPNext's WorkOrder.update_work_order_qty intentionally returns early when
	track_semi_finished_goods is enabled. QCMC can still create a final Manufacture
	entry for the production item, so derive the authoritative quantity from all
	submitted Manufacture entries and update the Work Order after submit/cancel.
	"""
	if isinstance(stock_entry, str):
		stock_entry = frappe.get_doc("Stock Entry", stock_entry)
	if not stock_entry.work_order or stock_entry.purpose != "Manufacture":
		return
	work_order = frappe.get_doc("Work Order", stock_entry.work_order)
	if not work_order.track_semi_finished_goods:
		return
	if not any(
		row.is_finished_item and row.item_code == work_order.production_item
		for row in stock_entry.get("items") or []
	):
		return
	produced_qty = work_order.get_transferred_or_manufactured_qty("Manufacture", "produced_qty")
	work_order.db_set("produced_qty", produced_qty)
	work_order.set_process_loss_qty()
	work_order.run_method("update_planned_qty")
	work_order.run_method("update_status")
