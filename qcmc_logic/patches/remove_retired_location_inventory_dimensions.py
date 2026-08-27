import json

import frappe


RETIRED_SOURCE_FIELDNAMES = {"bin", "bldg", "rack", "room", "aisle"}
IGNORED_INVENTORY_DOCTYPES = {
	"Serial and Batch Bundle",
	"Serial and Batch Entry",
	"Pick List Item",
	"Maintenance Visit Purpose",
}
RETIRED_GENERATED_FIELDNAMES = RETIRED_SOURCE_FIELDNAMES | {
	fieldname
	for source_fieldname in RETIRED_SOURCE_FIELDNAMES
	for fieldname in (
		f"to_{source_fieldname}",
		f"from_{source_fieldname}",
		f"rejected_{source_fieldname}",
	)
}
DISPLAY_FIELDS_AFTER_DIMENSIONS = {
	"Stock Reconciliation Item": ["custom_scanned_device", "custom_scanned_by"],
}
INVENTORY_DIMENSION_LAYOUT_ANCHORS = {
	# Delivery Note Item's standard anchor is the final Page Break checkbox,
	# which leaves Location at the bottom of the row form and last in the grid.
	"Delivery Note Item": "warehouse",
}


def _active_inventory_dimension_names():
	"""Support ERPNext versions both with and without Inventory Dimension.disabled."""
	filters = (
		{"disabled": 0}
		if frappe.get_meta("Inventory Dimension").has_field("disabled")
		else None
	)
	return frappe.get_all("Inventory Dimension", filters=filters, pluck="name")


def execute():
	affected_doctypes = set()

	# Location is the active Inventory Dimension. Remove only generated fields
	# left behind by the retired dimensions, on every document where they linger.
	for field in frappe.get_all(
		"Custom Field",
		filters={
			"fieldname": ("in", tuple(RETIRED_GENERATED_FIELDNAMES)),
			"is_system_generated": 1,
		},
		fields=["name", "dt"],
	):
		affected_doctypes.add(field.dt)
		frappe.delete_doc(
			"Custom Field",
			field.name,
			ignore_permissions=True,
			force=True,
		)

	for setter in frappe.get_all(
		"Property Setter",
		filters={"property": "field_order"},
		fields=["name", "doc_type", "value"],
	):
		try:
			field_order = json.loads(setter.value)
		except (TypeError, ValueError):
			continue

		if not isinstance(field_order, list):
			continue

		cleaned_field_order = [
			fieldname
			for fieldname in field_order
			if fieldname not in RETIRED_GENERATED_FIELDNAMES
		]
		if cleaned_field_order != field_order:
			affected_doctypes.add(setter.doc_type)
			frappe.db.set_value(
				"Property Setter",
				setter.name,
				"value",
				json.dumps(cleaned_field_order),
				update_modified=False,
			)

	for doctype in affected_doctypes:
		frappe.clear_cache(doctype=doctype)

	dimension_layouts = sync_active_inventory_dimensions()
	sync_inventory_dimension_visibility(dimension_layouts)
	sync_inventory_dimension_field_order(dimension_layouts)


def sync_active_inventory_dimensions():
	"""Reapply the standard ERPNext field layout after custom fixtures are synced."""
	from erpnext.stock.doctype.inventory_dimension.inventory_dimension import get_inventory_documents

	dimension_layouts = {}
	for dimension_name in _active_inventory_dimension_names():
		dimension = frappe.get_doc("Inventory Dimension", dimension_name)
		try:
			dimension.add_custom_fields()
		except frappe.ValidationError as exc:
			# Some upgraded sites contain an unrelated legacy Dynamic Link whose
			# options fail current Frappe validation whenever any Custom Field is
			# saved. The preceding Location migration has already generated the
			# dimension fields; continue with the targeted synchronization below.
			if "Options 'Dynamic Link' type of field" not in str(exc):
				raise
			frappe.log_error(
				title="Inventory Dimension legacy Dynamic Link validation",
				message=str(exc),
			)
		# ERPNext creates ledger fields separately from the inventory-document
		# loop. Existing generated fields are not refreshed when the dimension's
		# reference document changes, so keep their Link target authoritative too.
		for ledger_doctype in ("Stock Ledger Entry", "Stock Closing Balance"):
			frappe.db.set_value(
				"Custom Field",
				{"dt": ledger_doctype, "fieldname": dimension.target_fieldname},
				"options",
				dimension.reference_document,
				update_modified=False,
			)
			frappe.clear_cache(doctype=ledger_doctype)

		if dimension.apply_to_all_doctypes:
			doctypes = [row[0] for row in get_inventory_documents()]
		else:
			doctypes = [dimension.document_type]

		for doctype in doctypes:
			if not doctype or doctype in IGNORED_INVENTORY_DOCTYPES:
				continue

			fields = dimension.get_dimension_fields(doctype)
			dimension.add_transfer_field(doctype, fields)
			# Fixtures from older Inventory Dimensions may retain the same fieldname
			# with stale Link options (for example ERPNext Location). Existing fields
			# are not updated by add_custom_fields(), so synchronize them explicitly.
			for field in fields:
				if field.get("fieldtype") == "Link":
					frappe.db.set_value(
						"Custom Field",
						{"dt": doctype, "fieldname": field["fieldname"]},
						"options",
						dimension.reference_document,
						update_modified=False,
					)
			layout = dimension_layouts.setdefault(
				doctype,
				{"anchor": fields[0]["insert_after"], "fieldnames": []},
			)
			for field in fields:
				if field["fieldname"] not in layout["fieldnames"]:
					layout["fieldnames"].append(field["fieldname"])

	return dimension_layouts


def sync_inventory_dimension_visibility(dimension_layouts):
	"""Make generated dimensions visible on forms and editable child-table grids."""
	for doctype, layout in dimension_layouts.items():
		for fieldname in layout["fieldnames"]:
			values = {"hidden": 0}
			if fieldname == "inventory_dimension":
				# A collapsed section makes the dimension appear to be missing.
				values["collapsible"] = 0
			elif fieldname != "inventory_dimension_col_break":
				# Inventory transactions primarily use child tables. Showing the Link
				# in the grid makes the dimension available without opening every row.
				values["in_list_view"] = 1

			frappe.db.set_value(
				"Custom Field",
				{"dt": doctype, "fieldname": fieldname},
				values,
				update_modified=False,
			)

		frappe.clear_cache(doctype=doctype)


def sync_inventory_dimension_field_order(dimension_layouts):
	"""Keep customized layouts, but place generated dimension fields together."""
	for doctype, layout in dimension_layouts.items():
		setters = frappe.get_all(
			"Property Setter",
			filters={"doc_type": doctype, "property": "field_order"},
			fields=["name", "value"],
		)
		for setter in setters:
			try:
				field_order = json.loads(setter.value)
			except (TypeError, ValueError):
				continue

			if not isinstance(field_order, list):
				continue

			generated_fieldnames = set(layout["fieldnames"]) | {
				"inventory_dimension",
				"inventory_dimension_col_break",
			} | RETIRED_GENERATED_FIELDNAMES
			cleaned_field_order = [
				fieldname
				for fieldname in field_order
				if fieldname not in generated_fieldnames
			]

			anchor = INVENTORY_DIMENSION_LAYOUT_ANCHORS.get(
				doctype, layout["anchor"]
			)
			insert_at = (
				cleaned_field_order.index(anchor) + 1
				if anchor in cleaned_field_order
				else len(cleaned_field_order)
			)
			cleaned_field_order[insert_at:insert_at] = layout["fieldnames"]

			# These operational fields belong beside the inventory dimension and
			# must not disappear when a customized field order is synchronized.
			display_fields = DISPLAY_FIELDS_AFTER_DIMENSIONS.get(doctype, [])
			for fieldname in display_fields:
				if fieldname in cleaned_field_order:
					cleaned_field_order.remove(fieldname)
			insert_at += len(layout["fieldnames"])
			cleaned_field_order[insert_at:insert_at] = [
				fieldname
				for fieldname in display_fields
				if frappe.db.exists(
					"Custom Field", {"dt": doctype, "fieldname": fieldname}
				)
			]

			if cleaned_field_order != field_order:
				frappe.db.set_value(
					"Property Setter",
					setter.name,
					"value",
					json.dumps(cleaned_field_order),
					update_modified=False,
				)
				frappe.clear_cache(doctype=doctype)


def audit_inventory_dimension_visibility():
	"""Return effective visibility for every active, applicable dimension field."""
	from erpnext.stock.doctype.inventory_dimension.inventory_dimension import get_inventory_documents

	applicable_doctypes = {row[0] for row in get_inventory_documents()} - IGNORED_INVENTORY_DOCTYPES
	results = []
	for dimension_name in _active_inventory_dimension_names():
		dimension = frappe.get_doc("Inventory Dimension", dimension_name)
		doctypes = (
			applicable_doctypes
			if dimension.apply_to_all_doctypes
			else {dimension.document_type}
		)
		for doctype in sorted(filter(None, doctypes)):
			fields = dimension.get_dimension_fields(doctype)
			dimension.add_transfer_field(doctype, fields)
			meta = frappe.get_meta(doctype, cached=False)
			for expected in fields:
				field = meta.get_field(expected["fieldname"])
				results.append(
					{
						"doctype": doctype,
						"fieldname": expected["fieldname"],
						"exists": bool(field),
						"hidden": int(field.hidden or 0) if field else None,
						"in_list_view": int(field.in_list_view or 0) if field else None,
						"collapsible": int(field.collapsible or 0) if field else None,
					}
				)
	return results
