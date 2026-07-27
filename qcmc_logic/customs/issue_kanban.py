import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


BOARD_NAME = "Company Tickets"
COLUMNS = (
	("Open", "Red"),
	("Replied", "Blue"),
	("In Progress", "Purple"),
	("On Hold", "Orange"),
	("Resolved", "Green"),
	("Closed", "Gray"),
)
CARD_FIELDS = [
	"priority",
	"issue_type",
	"custom_requesting_department",
	"custom_due_date",
	"raised_by",
	"modified",
]
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def ensure_company_ticket_kanban():
	"""Create the shared drag-and-drop board for internal Issue tickets."""
	create_custom_fields(
		{
			"Issue": [
				{
					"fieldname": "custom_internal_ticket_section",
					"label": "Internal Ticket Details",
					"fieldtype": "Section Break",
					"insert_after": "description",
				},
				{
					"fieldname": "custom_requesting_department",
					"label": "Requesting Department",
					"fieldtype": "Link",
					"options": "Department",
					"in_list_view": 1,
					"in_standard_filter": 1,
					"insert_after": "custom_internal_ticket_section",
				},
				{
					"fieldname": "custom_location",
					"label": "Location",
					"fieldtype": "Data",
					"in_standard_filter": 1,
					"insert_after": "custom_requesting_department",
				},
				{
					"fieldname": "custom_ticket_details_column",
					"fieldtype": "Column Break",
					"insert_after": "custom_location",
				},
				{
					"fieldname": "custom_due_date",
					"label": "Due Date",
					"fieldtype": "Date",
					"in_list_view": 1,
					"in_standard_filter": 1,
					"insert_after": "custom_ticket_details_column",
				},
				{
					"fieldname": "custom_affected_asset",
					"label": "Affected Asset",
					"fieldtype": "Link",
					"options": "Asset",
					"in_standard_filter": 1,
					"insert_after": "custom_due_date",
				},
				{
					"fieldname": "custom_kanban_image",
					"label": "Kanban Image",
					"fieldtype": "Attach Image",
					"hidden": 1,
					"read_only": 1,
					"no_copy": 1,
					"insert_after": "attachment",
				}
			]
		},
		ignore_validate=True,
	)
	make_property_setter(
		"Issue",
		None,
		"image_field",
		"custom_kanban_image",
		"Data",
		for_doctype=True,
	)

	# Kanban only fetches standard/list fields. Without this, the card renders the
	# Issue Type label but receives no value even when the Issue has one.
	make_property_setter("Issue", "issue_type", "in_list_view", 1, "Check")
	make_property_setter("Issue", "issue_type", "reqd", 1, "Check")
	for fieldname in (
		"priority",
		"description",
		"custom_requesting_department",
		"custom_location",
		"custom_due_date",
		"custom_affected_asset",
	):
		make_property_setter(
			"Issue", fieldname, "allow_in_quick_entry", 1, "Check"
		)
	make_property_setter(
		"Issue",
		"status",
		"options",
		"Open\nReplied\nIn Progress\nOn Hold\nResolved\nClosed",
		"Text",
	)

	if frappe.db.exists("Kanban Board", BOARD_NAME):
		board = frappe.get_doc("Kanban Board", BOARD_NAME)
		_update_board(board)
		backfill_issue_kanban_images()
		frappe.clear_cache(doctype="Issue")
		return

	board = frappe.new_doc("Kanban Board")
	board.kanban_board_name = BOARD_NAME
	board.reference_doctype = "Issue"
	board.field_name = "status"
	board.private = 0
	board.show_labels = 1
	board.fields = frappe.as_json(CARD_FIELDS)

	for column_name, indicator in COLUMNS:
		board.append(
			"columns",
			{
				"column_name": column_name,
				"indicator": indicator,
			},
		)

	board.insert(ignore_permissions=True)
	backfill_issue_kanban_images()
	frappe.clear_cache(doctype="Issue")


def _update_board(board):
	board.private = 0
	board.show_labels = 1
	board.fields = frappe.as_json(CARD_FIELDS)
	existing_columns = {column.column_name: column for column in board.columns}
	board.columns = []

	for column_name, indicator in COLUMNS:
		existing = existing_columns.get(column_name)
		board.append(
			"columns",
			{
				"column_name": column_name,
				"indicator": indicator,
				"status": "Active",
				"order": existing.order if existing else None,
			},
		)

	board.save(ignore_permissions=True)


def sync_issue_kanban_image(file_doc, method=None):
	"""Use the first image attached through the Issue sidebar as its thumbnail."""
	if file_doc.attached_to_doctype != "Issue" or not file_doc.attached_to_name:
		return

	if not _is_image(file_doc.file_url or file_doc.file_name):
		return

	if not frappe.db.get_value("Issue", file_doc.attached_to_name, "custom_kanban_image"):
		frappe.db.set_value(
			"Issue",
			file_doc.attached_to_name,
			"custom_kanban_image",
			file_doc.file_url,
			update_modified=False,
		)


def replace_deleted_issue_kanban_image(file_doc, method=None):
	if file_doc.attached_to_doctype != "Issue" or not file_doc.attached_to_name:
		return

	current = frappe.db.get_value("Issue", file_doc.attached_to_name, "custom_kanban_image")
	if current != file_doc.file_url:
		return

	remaining_files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Issue",
			"attached_to_name": file_doc.attached_to_name,
			"name": ["!=", file_doc.name],
		},
		fields=["file_url", "file_name"],
		order_by="creation asc",
	)
	next_image = next(
		(file.file_url for file in remaining_files if _is_image(file.file_url or file.file_name)),
		None,
	)
	frappe.db.set_value(
		"Issue",
		file_doc.attached_to_name,
		"custom_kanban_image",
		next_image,
		update_modified=False,
	)


def backfill_issue_kanban_images():
	for issue_name in frappe.get_all(
		"Issue",
		filters={"custom_kanban_image": ["is", "not set"]},
		pluck="name",
	):
		files = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Issue", "attached_to_name": issue_name},
			fields=["file_url", "file_name"],
			order_by="creation asc",
		)
		image = next(
			(file.file_url for file in files if _is_image(file.file_url or file.file_name)),
			None,
		)
		if image:
			frappe.db.set_value(
				"Issue", issue_name, "custom_kanban_image", image, update_modified=False
			)


def _is_image(file_path):
	return bool(file_path) and file_path.lower().split("?", 1)[0].endswith(IMAGE_EXTENSIONS)
