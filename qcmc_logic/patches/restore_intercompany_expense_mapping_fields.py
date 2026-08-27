import frappe


DOCTYPE = "Intercompany Expense Mapping"

FIELD_DEFS = [
	{
		"fieldname": "inventory_group",
		"label": "Inventory Group",
		"fieldtype": "Link",
		"options": "Inventory Group",
		"in_list_view": 1,
		"reqd": 1,
	},
	{
		"fieldname": "source_company",
		"label": "Source Company",
		"fieldtype": "Link",
		"options": "Company",
		"in_list_view": 1,
		"reqd": 1,
	},
	{
		"fieldname": "target_company",
		"label": "Target Company",
		"fieldtype": "Link",
		"options": "Company",
		"in_list_view": 1,
		"reqd": 1,
	},
]


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	ensure_database_columns()
	ensure_docfields()
	frappe.clear_cache(doctype=DOCTYPE)


def ensure_database_columns():
	for field in FIELD_DEFS:
		if not frappe.db.has_column(DOCTYPE, field["fieldname"]):
			frappe.db.sql_ddl(
				f"alter table `tab{DOCTYPE}` add column `{field['fieldname']}` varchar(140)"
			)


def ensure_docfields():
	existing_fields = frappe.get_all(
		"DocField",
		filters={"parent": DOCTYPE},
		fields=["name", "fieldname", "idx"],
		order_by="idx",
	)
	existing_by_fieldname = {field.fieldname: field for field in existing_fields}
	target_idx = get_insert_idx(existing_fields)

	for offset, field in enumerate(FIELD_DEFS):
		values = {
			"parent": DOCTYPE,
			"parenttype": "DocType",
			"parentfield": "fields",
			"idx": target_idx + offset,
			"fieldname": field["fieldname"],
			"label": field["label"],
			"fieldtype": field["fieldtype"],
			"options": field["options"],
			"in_list_view": field["in_list_view"],
			"reqd": field["reqd"],
		}
		existing = existing_by_fieldname.get(field["fieldname"])
		if existing:
			frappe.db.set_value("DocField", existing.name, values, update_modified=False)
		else:
			frappe.get_doc({"doctype": "DocField", **values}).insert(ignore_permissions=True)

	shift_following_fields(target_idx + len(FIELD_DEFS), existing_fields)
	frappe.db.set_value("DocType", DOCTYPE, "modified", frappe.utils.now(), update_modified=False)


def get_insert_idx(existing_fields):
	for field in existing_fields:
		if field.fieldname == "source_inv_account":
			return field.idx

	return 1


def shift_following_fields(start_idx, existing_fields):
	restored_fieldnames = {field["fieldname"] for field in FIELD_DEFS}
	next_idx = start_idx
	for field in existing_fields:
		if field.fieldname in restored_fieldnames:
			continue
		if field.idx >= get_insert_idx(existing_fields):
			frappe.db.set_value("DocField", field.name, "idx", next_idx, update_modified=False)
			next_idx += 1
