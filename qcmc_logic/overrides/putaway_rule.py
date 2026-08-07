import frappe
from frappe import _

from erpnext.stock.doctype.inventory_dimension.inventory_dimension import get_inventory_dimensions
from erpnext.stock.doctype.putaway_rule.putaway_rule import PutawayRule


class CustomPutawayRule(PutawayRule):
	def validate(self):
		self.validate_duplicate_rule()
		self.validate_warehouse_and_company()
		self.validate_capacity()
		self.validate_priority()
		self.set_stock_capacity()

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
			"item_code": self.item_code,
			"company": self.company,
		}
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
		if not any(self.get(fieldname) for fieldname in dimension_fields):
			return _("Putaway Rule already exists for Item {0} in Warehouse {1}.").format(
				frappe.bold(self.item_code), frappe.bold(self.warehouse)
			)

		dimensions = ", ".join(
			[
				"{0}: {1}".format(frappe.bold(frappe.unscrub(fieldname)), frappe.bold(self.get(fieldname)))
				for fieldname in dimension_fields
			]
		)
		return _("Putaway Rule already exists for Item {0} with {1}.").format(
			frappe.bold(self.item_code), dimensions
		)
