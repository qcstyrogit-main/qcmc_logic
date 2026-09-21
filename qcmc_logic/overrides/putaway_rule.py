import frappe
from frappe import _
from frappe.utils import flt

from erpnext.stock.doctype.inventory_dimension.inventory_dimension import get_inventory_dimensions
from erpnext.stock.doctype.putaway_rule.putaway_rule import PutawayRule
from qcmc_logic.overrides.putaway_rule_dimension import get_putaway_rule_balance


class CustomPutawayRule(PutawayRule):
	def validate(self):
		self.normalize_item_restriction()
		self.normalize_capacity_restriction()
		self.validate_duplicate_rule()
		self.validate_warehouse_and_company()
		self.validate_storage_location_warehouse()
		# stock_capacity is derived from the visible Capacity and Conversion
		# Factor fields, so calculate it before comparing it with existing stock.
		self.set_stock_capacity()
		self.validate_capacity()
		self.validate_priority()

	def normalize_item_restriction(self):
		if self.get("custom_no_item_restriction"):
			self.item_code = ""
			self.item_name = ""
			self.uom = ""
			self.stock_uom = ""
			self.conversion_factor = 1

	def normalize_capacity_restriction(self):
		if self.get("custom_no_capacity_restriction"):
			self.capacity = 0
			self.stock_capacity = 0

	def set_stock_capacity(self):
		if self.get("custom_no_capacity_restriction"):
			self.stock_capacity = 0
			return
		super().set_stock_capacity()

	def validate_storage_location_warehouse(self):
		location = self.get("location")
		if not location:
			return
		location_warehouse = frappe.db.get_value("Storage Location", location, "custom_warehouse") or ""
		if _normalize_warehouse(self.warehouse) != _normalize_warehouse(location_warehouse):
			frappe.throw(
				_("Putaway Rule warehouse '{0}' does not match Storage Location warehouse '{1}'.\n[PUTAWAY_LOCATION_WAREHOUSE_MISMATCH]").format(
					self.warehouse, location_warehouse
				)
			)

	def validate_capacity(self):
		if not self.get("custom_no_item_restriction") and not self.item_code:
			frappe.throw(_("Item Code is required unless No Item Restriction is checked."))

		if self.get("custom_no_capacity_restriction"):
			return

		if not self.capacity:
			frappe.throw(_("Capacity must be greater than 0"), title=_("Invalid"))

		dimensions = {
			fieldname: self.get(fieldname)
			for fieldname in self.get_inventory_dimension_fields()
			if self.get(fieldname)
		}
		balance_qty = get_putaway_rule_balance(self)

		if flt(self.stock_capacity) < flt(balance_qty):
			location = dimensions.get("location")
			scope = _(" at Location {0}").format(frappe.bold(location)) if location else ""
			stock_uom = frappe.db.get_value("Item", self.item_code, "stock_uom") if self.item_code else ""
			frappe.throw(
				_(
					"Capacity for {0}{1} must not be lower than the existing stock "
					"level of {2} {3}."
				).format(
					frappe.bold(self.item_code) if self.item_code else _("Any Item"),
					scope,
					frappe.bold(balance_qty),
					stock_uom,
				),
				title=_("Insufficient Capacity"),
			)

	def validate_duplicate_rule(self):
		filters, dimension_fields = self.get_duplicate_filters()
		existing_rule = frappe.db.exists("Putaway Rule", filters)

		if existing_rule and existing_rule != self.name:
			frappe.throw(
				self.get_duplicate_message(dimension_fields),
				title=_("Duplicate"),
			)

	def get_duplicate_filters(self):
		filters = {
			"company": self.company,
			"custom_no_item_restriction": 1 if self.get("custom_no_item_restriction") else 0,
		}
		if self.get("custom_no_item_restriction"):
			filters["item_code"] = ["in", ["", None]]
		else:
			filters["item_code"] = self.item_code
		dimension_fields = self.get_inventory_dimension_fields()

		if any(self.get(fieldname) for fieldname in dimension_fields):
			for fieldname in dimension_fields:
				filters[fieldname] = self.get(fieldname) or ("is", "not set")
		else:
			filters["warehouse"] = self.warehouse

		return filters, dimension_fields

	def get_inventory_dimension_fields(self):
		meta = frappe.get_meta(self.doctype)
		fields = []

		for dimension in get_inventory_dimensions():
			fieldname = dimension.get("fieldname")
			if fieldname and meta.has_field(fieldname):
				fields.append(fieldname)

		return fields

	def get_duplicate_message(self, dimension_fields):
		item_label = _("Any Item") if self.get("custom_no_item_restriction") else frappe.bold(self.item_code)
		if not any(self.get(fieldname) for fieldname in dimension_fields):
			return _("Putaway Rule already exists for {0} in Warehouse {1}.").format(
				item_label, frappe.bold(self.warehouse)
			)

		dimensions = ", ".join(
			[
				"{0}: {1}".format(frappe.bold(frappe.unscrub(fieldname)), frappe.bold(self.get(fieldname)))
				for fieldname in dimension_fields
			]
		)
		return _("Putaway Rule already exists for {0} with {1}.").format(
			item_label, dimensions
		)


def _normalize_warehouse(value):
	return "".join(str(value or "").lower().replace("-", "").split())
