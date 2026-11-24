"""One-time standard-pack import; preserve existing Item packing defaults."""
import json
from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({"Item": [
        {"fieldname": "custom_material_scanner_pack_qty", "label": "Big Pack Qty",
         "fieldtype": "Float", "insert_after": "stock_uom", "non_negative": 1, "description": ""},
        {"fieldname": "custom_standard_pack_qty", "label": "Standard Pack Qty",
         "fieldtype": "Float", "insert_after": "custom_material_scanner_pack_qty",
         "non_negative": 1, "description": ""},
    ]}, update=True)
    path = Path(__file__).resolve().parents[1] / "data" / "material_scanner_standard_pack_quantities.json"
    quantities = json.loads(path.read_text())["quantities"]
    for item in frappe.get_all("Item", fields=["name", "item_code", "custom_standard_pack_qty"]):
        quantity = quantities.get(item.item_code)
        if quantity is not None and not item.get("custom_standard_pack_qty"):
            frappe.db.set_value("Item", item.name, "custom_standard_pack_qty", quantity, update_modified=False)
