import frappe
from frappe import _

from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry

from qcmc_logic.overrides.putaway_rule_dimension import (
	RECEIVING_STOCK_ENTRY_PURPOSES,
	apply_dimension_putaway_rule,
	validate_dimension_putaway_capacity,
)


class CustomStockEntry(StockEntry):
	def extend(self, key, value):
		if key == 'custom_storage_allocation':
			from frappe.model.base_document import BaseDocument
			for row in value:
				BaseDocument.append(self, key, row)
			return
		return super().extend(key, value)

	@property
	def custom_storage_allocation(self):
		from qcmc_logic.material_receipt_allocation import get_allocation_grid_rows
		return get_allocation_grid_rows(self)

	def on_update(self):
		super().on_update()
		if self.docstatus == 0:
			from qcmc_logic.material_receipt_allocation import sync_allocations
			sync_allocations(self)

	def before_submit(self):
		from qcmc_logic.material_receipt_allocation import prepare_receipt, sync_allocations
		prepare_receipt(self)
		sync_allocations(self, require_complete=True)

	def on_submit(self):
		super().on_submit()
		from qcmc_logic.material_receipt_allocation import submit_allocations
		submit_allocations(self)

	def before_cancel(self):
		from qcmc_logic.material_receipt_allocation import linked_allocations, uses_allocation
		from qcmc_logic.warehouse_capacity import lock_warehouses
		allocations = linked_allocations(self.name)
		if uses_allocation(self) or allocations:
			lock_warehouses([r.t_warehouse for r in self.items] + [r.s_warehouse for r in self.items]
			                + [a.warehouse for a in allocations])
		super().before_cancel()

	def on_cancel(self):
		from qcmc_logic.material_receipt_allocation import cancel_allocations
		cancel_allocations(self)
		super().on_cancel()

	def on_trash(self):
		from qcmc_logic.material_receipt_allocation import delete_draft_allocations
		delete_draft_allocations(self)
		super().on_trash()

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
		from qcmc_logic.material_receipt_allocation import clear_bulk_storage_locations
		clear_bulk_storage_locations(self)

	def before_validate(self):
		from qcmc_logic.material_receipt_allocation import prepare_receipt, uses_allocation
		prepare_receipt(self)
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

		if self.get("items") and apply_rule and not uses_allocation(self):
			apply_dimension_putaway_rule(self.doctype, self.get("items"), self.company, purpose=self.purpose)

		if self.project:
			for item in self.items:
				if not item.project:
					item.project = self.project

	def validate_putaway_capacity(self):
		from qcmc_logic.material_receipt_allocation import uses_allocation
		if uses_allocation(self):
			return
		# Receive Finished Goods starts from an existing Draft Manufacture Stock
		# Entry. Its finished row is intentionally unallocated at draft creation;
		# the scanner API later resolves all Putaway Rules, splits the row, locks the
		# document, and submits it. Do not compare that unsplit total against only
		# the first rule while inserting/saving the draft. A direct manual Submit
		# still runs the normal capacity validation.
		if self.purpose == "Manufacture":
			# Checker confirmation submits the reviewed Pullout before Putaway is
			# performed. This in-memory flag is set only by that backend workflow;
			# ordinary Desk/API submissions must still pass capacity validation.
			if getattr(self, "flags", None) and self.flags.get("skip_putaway_capacity_for_handover"):
				return
			if getattr(self, "_action", None) != "submit":
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
