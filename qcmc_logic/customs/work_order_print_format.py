import re

import frappe


COPY_START = "<!-- qcmc-job-order-two-copies:start -->"
COPY_END = "<!-- qcmc-job-order-two-copies:end -->"
SOURCE_OPEN = '<template class="qcmc-job-order-source">'
SOURCE_CLOSE = "</template>"
MC_FORM_CODE = "F-PP01-6/REV01/11June2018"
QC_FORM_CODE = "PIC-QR-005/rev01/January 19, 2018"
PRINTING_FORM_CODE = "PIC-QR-004 / rev 02 / July 07, 2017"
PRINTING_FORMAT = "PRINTING"
PRINTING_TEMPLATE_FORMAT = "THERMOFORMING"

LARGE_COPY_FORMATS = {"EXPANSION", "EXTRUDER QC"}
MEDIUM_COPY_FORMATS = {"EXTRUDER MC", "PELLETIZING MC", "PELLETIZING QC"}

QC_TRACKING_ROWS = {
	8: 12,
	10: 6,
	15: 12,
}

MULTIPLAST_TRACKING_ROWS = {
	8: 11,
	10: 6,
	15: 12,
}

MULTIPLAST_TWO_COLUMN_CSS = """/* qcmc-job-order-multiplast-two-column */
@media screen {
	.print-preview {
		width: 297mm !important;
		max-width: 297mm !important;
		min-height: 210mm !important;
	}

	.print-format {
		position: relative !important;
		box-sizing: border-box !important;
		width: 297mm !important;
		max-width: 297mm !important;
		height: 210mm !important;
		min-height: 210mm !important;
		margin: 0 auto !important;
		padding: 0 !important;
		overflow: hidden !important;
	}
}

@media print {
	@page {
		size: A4 landscape;
		margin: 0;
	}

	html, body {
		width: 297mm !important;
		height: 210mm !important;
		min-height: 0 !important;
		max-height: 210mm !important;
		margin: 0 !important;
		padding: 0 !important;
		overflow: hidden !important;
	}

	.print-format {
		position: relative !important;
		width: 297mm !important;
		height: 210mm !important;
		min-height: 0 !important;
		margin: 0 !important;
		padding: 0 !important;
		overflow: hidden !important;
	}
}

.print-format > .qcmc-job-order-copy {
	position: absolute !important;
	top: 5mm;
	left: 5mm;
	width: 197.857mm !important;
	transform: scale(0.7);
	transform-origin: top left;
}

.print-format > .qcmc-job-order-copy.qcmc-copy-medium {
	width: 173.125mm !important;
	transform: scale(0.8);
}

.print-format > .qcmc-job-order-copy.qcmc-copy-large {
	width: 138.5mm !important;
	transform: scale(1);
}

.print-format > .qcmc-job-order-copy:first-of-type {
	left: 5mm;
}

.print-format > .qcmc-job-order-copy:last-of-type {
	left: 153.5mm;
}

.print-format > .qcmc-job-order-copy .qcmc-condensed-tracking tbody tr {
	height: 9mm !important;
}

.print-format > .qcmc-job-order-copy.qcmc-copy-medium .qcmc-condensed-tracking tbody tr {
	height: 11mm !important;
}

.print-format > .qcmc-job-order-copy.qcmc-copy-large .qcmc-condensed-tracking tbody tr {
	height: 10mm !important;
}

.print-format > .qcmc-job-order-copy .qcmc-mc-form-code {
	margin-top: 2px !important;
	font-size: 8pt !important;
	line-height: 1.1 !important;
	text-align: right !important;
}

.print-format > .qcmc-job-order-copy table {
	margin-top: 0 !important;
	margin-bottom: 2px !important;
}

.print-format > .qcmc-job-order-copy tr,
.print-format > .qcmc-job-order-copy th,
.print-format > .qcmc-job-order-copy td {
	height: auto !important;
	min-height: 0 !important;
}

.print-format > .qcmc-job-order-copy th,
.print-format > .qcmc-job-order-copy td {
	padding-top: 1px !important;
	padding-bottom: 1px !important;
	line-height: 1.05 !important;
}
"""

QC_TOP_HALF_CSS = """/* qcmc-job-order-qc-top-half */
@media screen {
	.print-format {
		position: relative !important;
		box-sizing: border-box !important;
		width: 210mm !important;
		height: 297mm !important;
		min-height: 297mm !important;
		margin: 0 auto !important;
		padding: 0 !important;
		overflow: hidden !important;
	}
}

@media print {
	@page {
		size: A4 portrait;
		margin: 0;
	}

	html, body,
	.print-format {
		width: 210mm !important;
		height: 297mm !important;
		min-height: 0 !important;
		max-height: 297mm !important;
		margin: 0 !important;
		padding: 0 !important;
		overflow: hidden !important;
	}
}

.print-format > .qcmc-job-order-copy {
	position: absolute !important;
	top: 5mm;
	left: 5mm;
	width: 250mm !important;
	transform: scale(0.8);
	transform-origin: top left;
}

.print-format > .qcmc-job-order-copy.qcmc-copy-medium {
	width: 250mm !important;
	transform: scale(0.8);
}

.print-format > .qcmc-job-order-copy.qcmc-copy-large {
	width: 210.526mm !important;
	transform: scale(0.95);
}

.print-format > .qcmc-job-order-copy .qcmc-condensed-tracking tbody tr {
	height: 7mm !important;
}

.print-format > .qcmc-job-order-copy.qcmc-copy-medium .qcmc-condensed-tracking tbody tr,
.print-format > .qcmc-job-order-copy.qcmc-copy-large .qcmc-condensed-tracking tbody tr {
	height: 7.5mm !important;
}

.print-format > .qcmc-job-order-copy .qcmc-qc-form-code {
	margin-top: 2px !important;
	font-size: 8pt !important;
	line-height: 1.1 !important;
	text-align: right !important;
}

.print-format > .qcmc-job-order-copy table {
	margin-top: 0 !important;
	margin-bottom: 2px !important;
}

.print-format > .qcmc-job-order-copy tr,
.print-format > .qcmc-job-order-copy th,
.print-format > .qcmc-job-order-copy td {
	height: auto !important;
	min-height: 0 !important;
}

.print-format > .qcmc-job-order-copy th,
.print-format > .qcmc-job-order-copy td {
	padding-top: 1px !important;
	padding-bottom: 1px !important;
	line-height: 1.05 !important;
}
"""

NO_SHADE_CSS = """
.print-format > .qcmc-job-order-copy,
.print-format > .qcmc-job-order-copy div,
.print-format > .qcmc-job-order-copy table,
.print-format > .qcmc-job-order-copy thead,
.print-format > .qcmc-job-order-copy tbody,
.print-format > .qcmc-job-order-copy tr,
.print-format > .qcmc-job-order-copy th,
.print-format > .qcmc-job-order-copy td {
	background: #fff !important;
	background-color: #fff !important;
	background-image: none !important;
}

.print-format > .qcmc-job-order-copy,
.print-format > .qcmc-job-order-copy * {
	color: #000 !important;
	opacity: 1 !important;
	font-family: Arial, Helvetica, sans-serif !important;
	text-shadow: none !important;
	-webkit-text-fill-color: #000 !important;
}

.print-format > .qcmc-job-order-copy th,
.print-format > .qcmc-job-order-copy td {
	font-size: 11pt !important;
}

.print-format > .qcmc-job-order-copy th {
	font-weight: 700 !important;
}

.print-format > .qcmc-job-order-copy td {
	font-weight: 400 !important;
}

.print-format > .qcmc-job-order-copy .qcmc-condensed-tracking thead th {
	font-size: 8.5pt !important;
	line-height: 1.15 !important;
	padding: 1px !important;
	white-space: normal !important;
	overflow-wrap: normal !important;
	word-break: normal !important;
}

.qcmc-condensed-tracking tbody tr {
	height: 6mm !important;
}
"""


def ensure_job_order_print_formats_use_a5():
	"""Apply the company-specific half-A4 Job Order layouts."""
	ensure_printing_job_order_format()
	formats = frappe.get_all(
		"Print Format",
		filters={"doc_type": "Work Order"},
		fields=["name", "css", "html"],
	)

	for print_format in formats:
		css = print_format.css or ""
		if "/* qcmc-job-order-a5 */" in css:
			css = css.partition("/* qcmc-job-order-a5 */")[0].rstrip()
		if "/* qcmc-job-order-a4-two-copies */" in css:
			css = css.partition("/* qcmc-job-order-a4-two-copies */")[0].rstrip()
		if "/* qcmc-job-order-a4-single-copy */" in css:
			css = css.partition("/* qcmc-job-order-a4-single-copy */")[0].rstrip()
		if "/* qcmc-job-order-a5-single-copy */" in css:
			css = css.partition("/* qcmc-job-order-a5-single-copy */")[0].rstrip()
		if "/* qcmc-job-order-multiplast-two-column */" in css:
			css = css.partition("/* qcmc-job-order-multiplast-two-column */")[0].rstrip()
		if "/* qcmc-job-order-qc-top-half */" in css:
			css = css.partition("/* qcmc-job-order-qc-top-half */")[0].rstrip()

		html = print_format.html or ""
		if COPY_START in html and COPY_END in html:
			stored = html.partition(SOURCE_OPEN)[2]
			if stored:
				html = stored.partition(SOURCE_CLOSE)[0].strip()
			else:
				# This format already contains the final, directly editable layout.
				continue

		if print_format.name in LARGE_COPY_FORMATS:
			copy_class = "qcmc-job-order-copy qcmc-copy-large"
		elif print_format.name in MEDIUM_COPY_FORMATS:
			copy_class = "qcmc-job-order-copy qcmc-copy-medium"
		else:
			copy_class = "qcmc-job-order-copy"

		def expand_tracking_rows(match, row_counts):
			current_rows = int(match.group(1))
			return f"range({row_counts.get(current_rows, current_rows)})"

		row_pattern = r"range\(\s*(8|10|15)\s*\)"
		multiplast_html = re.sub(
			row_pattern,
			lambda match: expand_tracking_rows(match, MULTIPLAST_TRACKING_ROWS),
			html,
		)
		qc_html = re.sub(
			row_pattern,
			lambda match: expand_tracking_rows(match, QC_TRACKING_ROWS),
			html,
		)

		def condense_material_columns(render_html):
			if "Issuance of Material" not in render_html:
				return render_html
			render_html = re.sub(
				r'class=(["\'])trk\1',
				r'class=\1trk qcmc-condensed-tracking\1',
				render_html,
				count=1,
			)
			replacements = {
				"Col/Add": "Col/<br>Add",
				"Roll Lot<br>No.": "Roll<br>Lot No.",
				"Reject/<br>Overflow": "Reject/<br>Overflow",
				">Balance</th>": ">Bal<br>ance</th>",
				">Operator</th>": ">Oper<br>ator</th>",
			}
			for label, wrapped_label in replacements.items():
				render_html = render_html.replace(label, wrapped_label)
			return render_html

		def remove_legacy_form_code(render_html):
			"""The wrapper supplies the company code, so discard old template footers."""
			return re.sub(
				r"<div\b[^>]*>\s*(?:PIC-QR|F-PP)[\s\S]*?</div>",
				"",
				render_html,
				flags=re.IGNORECASE,
			)

		multiplast_html = remove_legacy_form_code(
			condense_material_columns(multiplast_html)
		)
		qc_html = remove_legacy_form_code(condense_material_columns(qc_html))

		layout_html = (
			f"{COPY_START}\n"
			'{% if doc.company == "Multiplast Corporation" %}\n'
			f'<div class="{copy_class}">\n{multiplast_html}\n'
			f'<div class="qcmc-mc-form-code">{MC_FORM_CODE}</div>\n</div>\n'
			f'<div class="{copy_class}">\n{multiplast_html}\n'
			f'<div class="qcmc-mc-form-code">{MC_FORM_CODE}</div>\n</div>\n'
			f"<style>\n{MULTIPLAST_TWO_COLUMN_CSS}\n{NO_SHADE_CSS}\n</style>\n"
			"{% else %}\n"
			f'<div class="{copy_class}">\n{qc_html}\n'
			f'<div class="qcmc-qc-form-code">{QC_FORM_CODE}</div>\n</div>\n'
			f"<style>\n{QC_TOP_HALF_CSS}\n{NO_SHADE_CSS}\n</style>\n"
			"{% endif %}\n"
			+ COPY_END
		)

		frappe.db.set_value(
			"Print Format",
			print_format.name,
			{
				"css": css,
				"html": layout_html,
			},
			update_modified=False,
		)

	frappe.clear_cache(doctype="Print Format")


def ensure_printing_job_order_format():
	"""Create PRINTING from the maintained Thermoforming Job Order layout."""
	if frappe.db.exists("Print Format", PRINTING_FORMAT):
		assign_printing_format_to_workstations()
		return PRINTING_FORMAT

	if not frappe.db.exists("Print Format", PRINTING_TEMPLATE_FORMAT):
		frappe.throw(
			f"Template Print Format {PRINTING_TEMPLATE_FORMAT} was not found."
		)

	source = frappe.get_doc("Print Format", PRINTING_TEMPLATE_FORMAT)
	printing = frappe.copy_doc(source)
	printing.name = PRINTING_FORMAT
	printing.module = "Manufacturing"
	printing.standard = "No"
	printing.disabled = 0
	printing.html = (printing.html or "").replace(
		">THERMOFORMING<", ">PRINTING JOB ORDER FORM<"
	)
	printing.html = printing.html.replace(
		QC_FORM_CODE, PRINTING_FORM_CODE
	)
	printing.insert(ignore_permissions=True)
	assign_printing_format_to_workstations()
	return printing.name


def assign_printing_format_to_workstations():
	"""Route printer Work Orders to PRINTING through their workstation."""
	workstations = frappe.get_all(
		"Workstation",
		filters=[["name", "like", "PRINTER%"]],
		pluck="name",
	)
	for workstation in workstations:
		frappe.db.set_value(
			"Workstation",
			workstation,
			"custom_print_format",
			PRINTING_FORMAT,
			update_modified=False,
		)


@frappe.whitelist()
def get_work_order_print_format(work_order):
	"""Resolve a Job Order format without requiring Workstation read access."""
	doc = frappe.get_doc("Work Order", work_order)
	if not frappe.has_permission("Work Order", "read", doc=doc):
		frappe.throw("Not permitted", frappe.PermissionError)

	operations = [row for row in (doc.operations or []) if row.workstation]
	final_operation = next(
		(
			row
			for row in operations
			if getattr(row, "is_final_finished_good", 0)
		),
		None,
	)
	workstation = (
		final_operation.workstation
		if final_operation
		else operations[-1].workstation if operations else None
	)

	if not workstation and doc.bom_no:
		bom_operations = frappe.get_all(
			"BOM Operation",
			filters={"parent": doc.bom_no, "parenttype": "BOM"},
			fields=["workstation", "idx"],
			order_by="idx desc",
		)
		workstation = next(
			(row.workstation for row in bom_operations if row.workstation),
			None,
		)

	print_format = (
		frappe.db.get_value("Workstation", workstation, "custom_print_format")
		if workstation
		else None
	)
	if print_format and not frappe.db.exists(
		"Print Format", {"name": print_format, "doc_type": "Work Order", "disabled": 0}
	):
		print_format = None

	return {"workstation": workstation, "print_format": print_format}


def audit_job_order_print_formats():
	"""Return Job Order formats missing any required company-layout component."""
	formats = frappe.get_all(
		"Print Format",
		filters={"doc_type": "Work Order"},
		fields=["name", "html"],
	)
	required_markers = (
		COPY_START,
		'{% if doc.company == "Multiplast Corporation" %}',
		"/* qcmc-job-order-multiplast-two-column */",
		"/* qcmc-job-order-qc-top-half */",
	)
	missing = [
		print_format.name
		for print_format in formats
		if any(marker not in (print_format.html or "") for marker in required_markers)
	]
	return {
		"total": len(formats),
		"applied": len(formats) - len(missing),
		"missing": missing,
	}
