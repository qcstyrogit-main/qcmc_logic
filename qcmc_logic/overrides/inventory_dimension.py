import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from erpnext.stock.doctype.inventory_dimension.inventory_dimension import (
	InventoryDimension,
	field_exists,
	get_inventory_documents as get_erpnext_inventory_documents,
)


WAREHOUSE_TRANSFER_DETAIL_DOCTYPE = "Warehouse Transfer Details"
PICK_LIST_ITEM_DOCTYPE = "Pick List Item"


class CustomInventoryDimension(InventoryDimension):
	def on_update(self):
		super().on_update()
		self.add_warehouse_transfer_detail_fields()
		self.add_pick_list_item_fields()

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

	def add_pick_list_item_fields(self):
		if not self.apply_to_all_doctypes and self.document_type != PICK_LIST_ITEM_DOCTYPE:
			return
		if not frappe.db.exists("DocType", PICK_LIST_ITEM_DOCTYPE):
			return

		fields = self.get_dimension_fields(PICK_LIST_ITEM_DOCTYPE)
		for field in fields:
			if field.get("fieldname") == self.source_fieldname:
				field.update(in_list_view=1, columns=2, allow_on_submit=1)
		meta = frappe.get_meta(PICK_LIST_ITEM_DOCTYPE, cached=False)
		fields = [field for field in fields if not meta.has_field(field["fieldname"])]
		if fields:
			create_custom_fields({PICK_LIST_ITEM_DOCTYPE: fields})

		field_name = f"{PICK_LIST_ITEM_DOCTYPE}-{self.source_fieldname}"
		if frappe.db.exists("Custom Field", field_name):
			frappe.db.set_value(
				"Custom Field",
				field_name,
				{"in_list_view": 1, "columns": 2, "allow_on_submit": 1, "hidden": 0},
				update_modified=False,
			)
		frappe.clear_cache(doctype=PICK_LIST_ITEM_DOCTYPE)


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
