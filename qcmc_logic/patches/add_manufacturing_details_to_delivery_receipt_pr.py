import frappe


PRINT_FORMATS = {
	"Delivery Receipt PR": """    <td style=\"width: 200px;\">{{ item.qty }}</td>
    <td style=\"width: 100px;\">{{ item.uom }}</td>
    <td style=\"width: 180px;\">{{ item.item_code }}</td>
    <td style=\"width: 280px;text-align: center;\">{{ item.item_name }}</td>""",
	"Delivery Receipt MC": """    <td style=\"width: 80px;\">{{ item.qty }}</td>
    <td style=\"width: 80px;\">{{ item.uom }}</td>
    <td style=\"width: 150px;\">{{ item.item_code }}</td>
    <td style=\"width: 280px;text-align: center;\">{{ item.item_name }}</td>""",
	"Deliver Receipt QC": """    <td style=\"width: 80px;\">{{ item.qty }}</td>
    <td style=\"width: 80px;\">{{ item.uom }}</td>
    <td style=\"width: 150px;\">{{ item.item_code }}</td>
    <td style=\"width: 280px; text-align:center;\">{{ item.item_name }}</td>""",
}
NEW_ITEM_CELLS = """    <td style=\"width: 60px;\">{{ item.qty }}</td>
    <td style=\"width: 55px;\">{{ item.uom }}</td>
    <td style=\"width: 110px;\">{{ item.item_code }}</td>
    <td style=\"width: 175px; text-align: center;\">{{ item.item_name }}</td>
    <td style=\"width: 75px;\">{{ frappe.utils.formatdate(item.custom_manufacture_date) if item.custom_manufacture_date else '' }}</td>
    <td style=\"width: 75px;\">{{ item.custom_lot_number or '' }}</td>
    <td style=\"width: 50px;\">{{ item.custom_quantity if item.custom_quantity is not none else '' }}</td>"""


def get_labeled_item_rows(original_item_cells):
	return f"""{original_item_cells}
  </tr>
  <tr>
    <td colspan=\"4\" style=\"padding-left: 3px;\">
      Manufacture Date: {{{{ frappe.utils.formatdate(item.custom_manufacture_date) if item.custom_manufacture_date else '' }}}}
      &nbsp;&nbsp; Lot Number: {{{{ item.custom_lot_number or '' }}}}
      &nbsp;&nbsp; Quantity: {{{{ item.custom_quantity if item.custom_quantity is not none else '' }}}}
    </td>"""


def get_target_item_rows(original_item_cells):
	return f"""{original_item_cells}
  </tr>
  <tr>
    <td colspan=\"4\" style=\"padding-left: 3px;\">
      {{{{ frappe.utils.formatdate(item.custom_manufacture_date) if item.custom_manufacture_date else '' }}}}
      &nbsp;&nbsp; {{{{ item.custom_lot_number or '' }}}}
      &nbsp;&nbsp; {{{{ item.custom_quantity if item.custom_quantity is not none else '' }}}}
    </td>"""


def execute():
	for print_format, old_item_cells in PRINT_FORMATS.items():
		html = frappe.db.get_value("Print Format", print_format, "html") or ""
		if not html:
			continue
		normalized_html = html.replace("\r\n", "\n")
		target_item_rows = get_target_item_rows(old_item_cells)
		if target_item_rows in normalized_html:
			continue
		labeled_item_rows = get_labeled_item_rows(old_item_cells)
		if labeled_item_rows in normalized_html:
			updated_html = normalized_html.replace(labeled_item_rows, target_item_rows, 1)
		elif NEW_ITEM_CELLS in normalized_html:
			updated_html = normalized_html.replace(NEW_ITEM_CELLS, target_item_rows, 1)
		elif old_item_cells in normalized_html:
			updated_html = normalized_html.replace(old_item_cells, target_item_rows, 1)
		else:
			frappe.log_error(
				f"The expected item row was not found in {print_format}.",
				"Delivery Receipt update skipped",
			)
			continue

		frappe.db.set_value(
			"Print Format",
			print_format,
			"html",
			updated_html,
			update_modified=False,
		)
	frappe.clear_cache(doctype="Print Format")
