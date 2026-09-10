import frappe


PRINT_FORMATS = {
	"Charge Invoice Receipt MC": "sold_to",
	"Charge Invoice Receipt PR": "sold_to",
	"Charge Invoice Receipt QC": "charge_to",
}
LEGACY_MC_CODES = (
	"GAANT", "GACAR", "GADIG", "GADMP", "GAEX", "GAIBA", "GAIDI", "GAIGM",
	"GAIJA", "GAIKA", "GAIMT", "GAINO", "GAIP", "GAIPO", "GAIRM", "GAIRX",
	"GAISD", "GAISI", "GAIST", "GAITO", "GAMAN", "GBAYU", "GCATA", "GCORD",
	"GCSM", "GCT", "GDIG", "GFM", "GGBAL", "GGCA", "GGCAL", "GGDUM", "GGEST",
	"GGPM", "GGSC", "GGSF", "GGTOR", "GKIDA", "GKORO", "GLILO", "GMALL", "GMCEB",
	"GMING", "GMOAL", "GMTOR", "GNABU", "GSARA", "GTALA", "GTIBU", "OSLOB",
)
PR_ORIGINAL_ITEM_ROW = """    <td style=\"width:80px;\">{{ item.item_code }}</td>
    <td style=\"width:250px; text-align:center;\">{{ item.item_name }}</td>
    <td style=\"width:120px; text-align:center;\">{{ item.qty }}</td>
    <td style=\"width:60px;\">{{ item.uom }}</td>
    <td style=\"width:80px; text-align:right;\">{{ item.rate }}</td>
    <td style=\"width:110px; text-align:right;\">{{ item.amount }}</td>"""
PR_SEQUENCED_ITEM_ROW = """    <td style=\"width:250px; text-align:center;\">{{ item.item_name }}</td>
    <td style=\"width:120px; text-align:center;\">{{ item.qty }}</td>
    <td style=\"width:80px;\">{{ item.item_code }}</td>
    <td style=\"width:60px;\">{{ item.uom }}</td>
    <td style=\"width:80px; text-align:right;\">{{ item.rate }}</td>
    <td style=\"width:110px; text-align:right;\">{{ item.amount }}</td>"""


def execute():
	for print_format, field_id in PRINT_FORMATS.items():
		html = frappe.db.get_value("Print Format", print_format, "html") or ""
		if not html:
			continue

		normalized_html = html.replace("\r\n", "\n")
		original_field = (
			f'<div id="{field_id}" class="field">{{{{ doc.customer_name }}}}</div>'
		)
		formatted_field = (
			f'<div id="{field_id}" class="field"'
			f"{{% if ((tin.custom_legacy_mc_code or '')|trim|upper) in {LEGACY_MC_CODES!r} %}}"
			' style="transform: translateY(-20px); white-space: normal; '
			'line-height: 12px; width: 470px; height: auto; overflow: visible;"'
			"{% endif %}>"
			f"{{% if ((tin.custom_legacy_mc_code or '')|trim|upper) in {LEGACY_MC_CODES!r} %}}"
			"{{ ((doc.customer_name or '')|upper|replace(' GAISANO', '<br>GAISANO'))|safe }}"
			"{% else %}{{ doc.customer_name }}{% endif %}</div>"
		)
		legacy_code_formatted_field = (
			f'<div id="{field_id}" class="field"'
			f"{{% if ((tin.custom_legacy_mc_code or '')|trim|upper) in {LEGACY_MC_CODES!r} %}}"
			' style="transform: translateY(-20px); white-space: normal; '
			'line-height: 12px; height: auto; overflow: visible;"'
			"{% endif %}>{{ doc.customer_name }}</div>"
		)
		legacy_formatted_field = (
			f'<div id="{field_id}" class="field"'
			"{% if 'GAISANO' in (doc.customer_name or '')|upper %}"
			' style="transform: translateY(-20px); white-space: normal; '
			'line-height: 12px; height: auto; overflow: visible;"'
			"{% endif %}>{{ doc.customer_name }}</div>"
		)

		updated_html = normalized_html.replace(
			"transform: translateY(20px)",
			"transform: translateY(-20px)",
		)
		if print_format == "Charge Invoice Receipt PR":
			updated_html = updated_html.replace(
				PR_ORIGINAL_ITEM_ROW,
				PR_SEQUENCED_ITEM_ROW,
				1,
			)
		updated_html = updated_html.replace(
			"line-height: 12px; height: auto; overflow: visible;",
			"line-height: 12px; width: 470px; height: auto; overflow: visible;",
		)
		if legacy_formatted_field in updated_html:
			updated_html = updated_html.replace(
				legacy_formatted_field,
				formatted_field,
				1,
			)
		if legacy_code_formatted_field in updated_html:
			updated_html = updated_html.replace(
				legacy_code_formatted_field,
				formatted_field,
				1,
			)
		if formatted_field in updated_html:
			if updated_html != normalized_html:
				frappe.db.set_value(
					"Print Format",
					print_format,
					"html",
					updated_html,
					update_modified=False,
				)
			continue
		if original_field not in normalized_html:
			frappe.log_error(
				f"The customer field was not found in {print_format}.",
				"Gaisano charge-invoice formatting skipped",
			)
			continue

		frappe.db.set_value(
			"Print Format",
			print_format,
			"html",
			normalized_html.replace(original_field, formatted_field, 1),
			update_modified=False,
		)

	frappe.clear_cache(doctype="Print Format")
