import json

import frappe
from frappe import _
from frappe.twofactor import get_qr_svg_code


def get_context(context):
	context.no_cache = 1
	context.title = _("Storage Location QR Labels")

	# Require logged-in user
	if frappe.session.user == "Guest":
		frappe.throw(
			_("Please log in to print storage location QR labels."),
			frappe.AuthenticationError,
		)

	# Check permission
	if not frappe.has_permission("Storage Location", "read"):
		frappe.throw(
			_("You do not have permission to view Storage Locations."),
			frappe.PermissionError,
		)

	# The list-view action passes exact selected document names. In this mode,
	# print those documents only—never infer parents, children, or siblings.
	selected_names = _get_selected_location_names()
	filters = {
		"disabled": 0,
	}
	if selected_names:
		filters["name"] = ["in", selected_names]
	else:
		# Preserve the legacy all/branch behavior for direct page access.
		filters["is_group"] = 0

	# Limit printing to the selected branch. Nested-set boundaries ensure only
	# the selected parent and its descendants are considered; unrelated sibling
	# branches are never included. Selecting a posting leaf prints that leaf.
	parent_location = frappe.form_dict.get("parent_location") if not selected_names else None
	selected_location = None
	if parent_location:
		if not frappe.db.exists("Storage Location", parent_location):
			frappe.throw(_("Storage Location {0} does not exist.").format(parent_location))

		selected_location = frappe.get_doc("Storage Location", parent_location)
		if not selected_location.has_permission("read"):
			frappe.throw(
				_("You do not have permission to view Storage Location {0}.").format(
					parent_location
				),
				frappe.PermissionError,
			)
		if selected_location.disabled:
			frappe.throw(_("Storage Location {0} is disabled.").format(parent_location))

		filters["lft"] = [">=", selected_location.lft]
		filters["rgt"] = ["<=", selected_location.rgt]

	# Warehouse ownership comes directly from Storage Location.
	warehouse = frappe.form_dict.get("warehouse")
	if warehouse:
		filters["custom_warehouse"] = warehouse

	# Get Storage Locations
	locations = frappe.get_all(
		"Storage Location",
		filters=filters,
		fields=[
			"name",
			"location_code",
			"location_name",
			"location_type",
			"full_path",
			"is_group",
			"lft",
			"rgt",
			"custom_warehouse",
		],
		order_by="lft asc, full_path asc, location_code asc",
	)
	if selected_names:
		locations_by_name = {location.name: location for location in locations}
		locations = [locations_by_name[name] for name in selected_names if name in locations_by_name]
		for location in locations:
			if not frappe.has_permission("Storage Location", "read", doc=location.name):
				frappe.throw(
					_("You do not have permission to view Storage Location {0}.").format(location.name),
					frappe.PermissionError,
				)

	# Generate a fresh QR payload from the CURRENT database values.
	# Do NOT use location.qr_payload here because it may contain
	# an old Warehouse name.
	for location in locations:
		payload = _make_qr_payload(location)

		encoded_svg = get_qr_svg_code(payload)

		if isinstance(encoded_svg, bytes):
			encoded_svg = encoded_svg.decode()

		location.qr_data_uri = (
			f"data:image/svg+xml;base64,{encoded_svg}"
		)

		# Optional: expose the exact generated payload to the template
		# for debugging/display.
		location.generated_qr_payload = payload

	# Pass data to template
	context.locations = locations
	context.warehouse = warehouse
	context.parent_location = selected_location

	return context


def _get_selected_location_names():
	raw_locations = frappe.form_dict.get("locations")
	if not raw_locations:
		return []
	try:
		locations = json.loads(raw_locations)
	except (TypeError, ValueError):
		frappe.throw(_("Invalid Storage Location selection."))
	if not isinstance(locations, list):
		frappe.throw(_("Invalid Storage Location selection."))

	# Retain checkbox order while removing blanks and duplicates.
	selected = []
	seen = set()
	for location in locations:
		location = str(location or "").strip()
		if location and location not in seen:
			seen.add(location)
			selected.append(location)
	if not selected:
		frappe.throw(_("Select at least one Storage Location to print."))
	if len(selected) > 500:
		frappe.throw(_("Select no more than 500 Storage Locations at one time."))

	missing = [name for name in selected if not frappe.db.exists("Storage Location", name)]
	if missing:
		frappe.throw(_("Storage Location {0} does not exist.").format(missing[0]))
	return selected


def _make_qr_payload(location):
	"""
	Create a compact QR payload. Full descriptive details remain visible beside
	the QR and are resolved from ERPNext after scanning by location_id.
	"""

	location = frappe.get_doc("Storage Location", location.name)
	return json.dumps(
		{
			"type": "storage_location",
			"location_id": location.name,
			"warehouse": location.custom_warehouse or "",
		},
		separators=(",", ":"),
	)
