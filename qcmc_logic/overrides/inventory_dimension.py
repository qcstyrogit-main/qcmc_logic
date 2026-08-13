import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from erpnext.stock.doctype.inventory_dimension.inventory_dimension import (
	InventoryDimension,
	field_exists,
	get_inventory_documents as get_erpnext_inventory_documents,
)


WAREHOUSE_TRANSFER_DETAIL_DOCTYPE = "Warehouse Transfer Details"


class CustomInventoryDimension(InventoryDimension):
	def on_update(self):
		super().on_update()
		self.add_warehouse_transfer_detail_fields()

	def add_warehouse_transfer_detail_fields(self):
		if not should_add_warehouse_transfer_detail_fields(self):
			return

		if not frappe.db.exists("DocType", WAREHOUSE_TRANSFER_DETAIL_DOCTYPE):
			return

		fields = self.get_dimension_fields(WAREHOUSE_TRANSFER_DETAIL_DOCTYPE)
		fields = [field for field in fields if not field_exists(WAREHOUSE_TRANSFER_DETAIL_DOCTYPE, field["fieldname"])]

		if not fields:
			return

		create_custom_fields({WAREHOUSE_TRANSFER_DETAIL_DOCTYPE: fields})
		frappe.clear_cache(doctype=WAREHOUSE_TRANSFER_DETAIL_DOCTYPE)


def should_add_warehouse_transfer_detail_fields(dimension):
	return dimension.apply_to_all_doctypes or dimension.document_type == WAREHOUSE_TRANSFER_DETAIL_DOCTYPE


@frappe.whitelist()
def get_inventory_documents(doctype=None, txt=None, searchfield=None, start=None, page_len=None, filters=None):
	documents = list(
		get_erpnext_inventory_documents(
			doctype=doctype,
			txt=txt,
			searchfield=searchfield,
			start=start,
			page_len=page_len,
			filters=filters,
		)
	)

	if (
		frappe.db.exists("DocType", WAREHOUSE_TRANSFER_DETAIL_DOCTYPE)
		and (not txt or txt.lower() in WAREHOUSE_TRANSFER_DETAIL_DOCTYPE.lower())
	):
		row = [WAREHOUSE_TRANSFER_DETAIL_DOCTYPE]
		if row not in documents:
			documents.append(row)

	return documents
