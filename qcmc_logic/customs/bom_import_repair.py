import csv
from pathlib import Path

import frappe
from frappe.utils import flt
from frappe.utils.file_manager import save_file


PARENT_DEFAULTS = {
	"Roll Yield": 1,
	"Standard Weight (g)": 1,
	"Stabilizer %": 0,
	"Reject %": 0,
}

CHILD_DEFAULT_COLUMNS = (
	"Include in Formulation (Components)",
	"Material Ratio % (Components)",
	"Do Not Explode (Components)",
)


def prepare_local_bom_repair(source_file="/private/files/BOM.csv"):
	"""Prepare a pragmatic local-only BOM insert file and create missing Item masters."""
	source_path = Path(frappe.get_site_path(source_file.lstrip("/")))
	output_path = source_path.with_name("BOM_fixed_new.csv")

	with source_path.open(newline="", encoding="utf-8-sig") as source:
		reader = csv.DictReader(source)
		fieldnames = list(reader.fieldnames or [])
		rows = list(reader)

	for column in (*PARENT_DEFAULTS, *CHILD_DEFAULT_COLUMNS):
		if column not in fieldnames:
			fieldnames.append(column)

	groups = _group_bom_rows(rows)
	new_groups = [group for group in groups if not frappe.db.exists("BOM", group[0]["ID"])]
	skipped_existing = len(groups) - len(new_groups)

	missing_items = _create_missing_items(new_groups)
	fixed_rows = []
	for group in new_groups:
		_apply_defaults(group)
		fixed_rows.extend(group)

	with output_path.open("w", newline="", encoding="utf-8") as output:
		writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
		writer.writeheader()
		writer.writerows(fixed_rows)

	return {
		"source_boms": len(groups),
		"new_boms": len(new_groups),
		"skipped_existing_boms": skipped_existing,
		"created_missing_items": missing_items,
		"output_file": f"/private/files/{output_path.name}",
		"output_rows": len(fixed_rows),
	}


def start_repaired_bom_import(import_file="/private/files/BOM_fixed_new.csv"):
	"""Create and start a new Insert Data Import for the repaired local BOM file."""
	file_path = Path(frappe.get_site_path(import_file.lstrip("/")))
	file_doc = save_file(file_path.name, file_path.read_bytes(), None, None, is_private=1)
	frappe.db.commit()

	data_import = frappe.get_doc(
		{
			"doctype": "Data Import",
			"reference_doctype": "BOM",
			"import_type": "Insert New Records",
			"import_file": file_doc.file_url,
			"mute_emails": 1,
		}
	)
	data_import.insert(ignore_permissions=True)
	data_import.start_import()
	return {
		"name": data_import.name,
		"status": data_import.status,
		"payload_count": data_import.payload_count,
	}


def audit_repaired_bom_file(import_file="/private/files/BOM_fixed_new.csv"):
	file_path = Path(frappe.get_site_path(import_file.lstrip("/")))
	with file_path.open(newline="", encoding="utf-8-sig") as source:
		ids = [row["ID"] for row in csv.DictReader(source) if row.get("ID")]
	missing = [bom_name for bom_name in ids if not frappe.db.exists("BOM", bom_name)]
	return {
		"total": len(ids),
		"existing": len(ids) - len(missing),
		"missing_count": len(missing),
		"missing_sample": missing[:20],
	}


def _group_bom_rows(rows):
	groups = []
	current = None
	for row in rows:
		if (row.get("ID") or "").strip():
			current = [row]
			groups.append(current)
		elif current is not None:
			current.append(row)
	return groups


def _create_missing_items(groups):
	usage = {}
	for group in groups:
		parent = group[0]
		parent_code = (parent.get("Item to Manufacture") or "").strip()
		if parent_code:
			usage.setdefault(parent_code, "Nos")
		for row in group:
			item_code = (row.get("Item Code (Components)") or "").strip()
			if item_code:
				usage.setdefault(item_code, (row.get("UOM (Components)") or "Nos").strip() or "Nos")

	missing = [item_code for item_code in usage if not frappe.db.exists("Item", item_code)]
	if not missing:
		return []

	item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
	for item_code in missing:
		uom = usage[item_code]
		if not frappe.db.exists("UOM", uom):
			uom = "Nos"
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"item_group": item_group,
				"stock_uom": uom,
				"is_stock_item": 1,
			}
		)
		item.insert(ignore_permissions=True)

	frappe.db.commit()
	return missing


def _apply_defaults(group):
	parent = group[0]
	for column, value in PARENT_DEFAULTS.items():
		if not flt(parent.get(column)):
			parent[column] = value

	component_rows = [row for row in group if (row.get("Item Code (Components)") or "").strip()]
	total_qty = sum(abs(flt(row.get("Qty (Components)"))) for row in component_rows) or 1
	remaining = 100.0
	for index, row in enumerate(component_rows):
		row["Include in Formulation (Components)"] = 1
		row["Do Not Explode (Components)"] = 1
		if index == len(component_rows) - 1:
			ratio = remaining
		else:
			ratio = round(abs(flt(row.get("Qty (Components)"))) / total_qty * 100, 6)
			remaining -= ratio
		row["Material Ratio % (Components)"] = round(ratio, 6)
