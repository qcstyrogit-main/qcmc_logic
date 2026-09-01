import base64
import html
import json
from pathlib import Path

import frappe
from frappe import _
from frappe.twofactor import get_qr_svg_code
from frappe.utils import flt
from weasyprint import HTML


QCSC_PACKING_TAG_CUSTOMERS = {"EPE", "EPE1"}


@frappe.whitelist()
def get_packing_label_defaults(job_card):
	if not job_card or not frappe.db.exists("Job Card", job_card):
		frappe.throw(_("Job Card is required and must exist."))
	if not frappe.has_permission("Job Card", "read", job_card):
		frappe.throw(_("You do not have permission to read Job Card {0}.").format(job_card), frappe.PermissionError)

	item_code = frappe.db.get_value("Job Card", job_card, "production_item")
	return {
		"qa_code": frappe.db.get_value("EPS QA Code", {"item": item_code}, "qa_code") or "",
		"supported_customers": sorted(QCSC_PACKING_TAG_CUSTOMERS),
	}


@frappe.whitelist()
def generate_packing_label_pdf(job_card, pack_type, orientation="Portrait", label_data=None, master_sheet=0):
	"""Return a complete packing-label PDF without creating a File document."""
	if not job_card or not frappe.db.exists("Job Card", job_card):
		frappe.throw(_("Job Card is required and must exist."))
	if not frappe.has_permission("Job Card", "read", job_card):
		frappe.throw(_("You do not have permission to read Job Card {0}.").format(job_card), frappe.PermissionError)

	doc = frappe.get_doc("Job Card", job_card)
	item = frappe.get_doc("Item", doc.production_item)
	bom = frappe.get_doc("BOM", doc.bom_no)
	pack_type = (pack_type or "").strip()
	if pack_type not in {"Standard Pack", "Big Pack"}:
		frappe.throw(_("Pack Type must be Standard Pack or Big Pack."))

	pack_quantity = flt(bom.custom_standard_pack if pack_type == "Standard Pack" else bom.quantity)
	pack_quantity_prefix = "Big Pack " if pack_type == "Big Pack" else ""
	job_quantity = flt(doc.for_quantity)
	if pack_quantity <= 0 or job_quantity <= 0:
		frappe.throw(_("Job Card and pack quantities must be greater than zero."))
	label_count = job_quantity / pack_quantity
	if abs(label_count - round(label_count)) > 0.000001:
		frappe.throw(
			_("Job Card quantity {0} cannot be divided evenly by pack quantity {1}.").format(
				job_quantity, pack_quantity
			)
		)
	label_count = int(round(label_count))

	data = frappe.parse_json(label_data) if isinstance(label_data, str) else (label_data or {})
	customer = (data.get("customer") or "").strip()
	if customer not in QCSC_PACKING_TAG_CUSTOMERS:
		frappe.throw(_("QCSC Packing Tag is available only for Customer EPE or EPE1."))
	customer_name = frappe.db.get_value("Customer", customer, "customer_name")
	if not customer_name:
		frappe.throw(_("Customer {0} does not exist.").format(customer))
	qa_code = frappe.db.get_value("EPS QA Code", {"item": doc.production_item}, "qa_code")
	if not qa_code:
		frappe.throw(_("No EPS QA Code is configured for Item {0}.").format(doc.production_item))
	payload = ";".join(
		(doc.production_item, str(pack_quantity), item.stock_uom, doc.work_order, doc.name)
	)
	qr_encoded = get_qr_svg_code(payload)
	if isinstance(qr_encoded, bytes):
		qr_encoded = qr_encoded.decode()
	qr_src = f"data:image/svg+xml;base64,{qr_encoded}"
	logo_path = Path(frappe.get_app_path("qcmc_logic")) / "public" / "images" / "QC.webp"
	logo_src = "data:image/webp;base64," + base64.b64encode(logo_path.read_bytes()).decode()

	escape = lambda value: html.escape(str(value or ""))
	line = lambda label, value: (
		'<div class="line"><b>' + escape(label) + ':</b><span>' + escape(value) + "</span></div>"
	)
	label = f"""
	<div class="packing-tag">
		<div class="top">
			<div class="logo"><img src="{logo_src}"></div>
			<div class="header">
				<div class="control">PDN-QR-042 / rev 03 / {escape(frappe.utils.today())}</div>
				<div class="title">QCSC PACKING TAG</div>
				{line('QA PASSED', data.get('qa_passed'))}
				{line('PACKED DATE', data.get('packed_date'))}
				{line('INSPECTION DATE', data.get('inspection_date'))}
				{line('DR No.', data.get('dr_no'))}
				{line('PACKED BY', data.get('packed_by'))}
			</div>
		</div>
		<div class="pack-code">{escape(qa_code)}</div>
		<div class="customer"><b>Customer:</b><span>{escape(customer_name)}</span></div>
		<div class="bottom">
			<img class="qr" src="{qr_src}">
			<table>
				<tr><th>Lot No.:</th><td>{escape(data.get('lot_no'))}</td></tr>
				<tr><th>Part Name / No. / Code:</th><td>{escape(data.get('part_name'))}</td></tr>
				<tr><th>Quantity:</th><td class="quantity">{escape(pack_quantity_prefix)}{escape(pack_quantity)} {escape(item.stock_uom)}</td></tr>
			</table>
		</div>
	</div>"""

	landscape = (orientation or "").strip() == "Landscape"
	columns = 3 if landscape else 2
	label_width = "88mm" if landscape else "90mm"
	# A4 has room for two 95 mm landscape rows or three 92 mm portrait rows.
	# The previous 88 mm height clipped the 37 mm QR at the bottom of the tag.
	label_height = "95mm" if landscape else "92mm"
	page_orientation = "landscape" if landscape else "portrait"
	styles = f"""
	@page {{ size: A4 {page_orientation}; margin: 6mm; }}
	* {{ box-sizing: border-box; }}
	body {{ margin: 0; font-family: Arial, sans-serif; color: #222; display: flex;
		flex-wrap: wrap; gap: 4mm; align-items: flex-start; justify-content: center; }}
	body.forced-pages {{ display: block; }}
	.sheet {{ display: flex; flex-wrap: wrap; gap: 4mm; align-items: flex-start; justify-content: center;
		page-break-after: always; break-after: page; }}
	.sheet:last-child {{ page-break-after: auto; break-after: auto; }}
	.packing-tag {{ width: {label_width}; height: {label_height}; border: 1mm solid #333; padding: 2mm; break-inside: avoid; overflow: hidden; }}
	.top {{ display: grid; grid-template-columns: 17mm 1fr; gap: 2mm; border-bottom: .25mm solid #777; padding-bottom: 1.5mm; }}
	.logo {{ display:flex; align-items:center; justify-content:center; }}
	.logo img {{ max-width: 16mm; max-height: 16mm; object-fit: contain; }}
	.control {{ text-align:right; font-size: 5.5pt; white-space:nowrap; color:#555; }}
	.title {{ text-align:center; font-size: 10pt; font-weight:800; letter-spacing:.2mm; margin:1.2mm 0; }}
	.line {{ display:grid; grid-template-columns: 25mm 1fr; gap:1mm; align-items:end; margin:1mm 0; font-size:6.5pt; }}
	.line span {{ min-height:3mm; border-bottom:.25mm solid #777; font-weight:600; padding:0 .5mm .4mm; }}
	.pack-code {{ border:.8mm solid #555; display:inline-block; min-width:24mm; text-align:center; padding:1mm 2mm; margin:2mm 0; font-size:11pt; font-weight:800; }}
	.customer {{ display:grid; grid-template-columns:17mm 1fr; gap:2mm; align-items:end; font-size:6.5pt; margin-bottom:1mm; }}
	.customer span {{ text-align:center; border-bottom:.25mm solid #777; font-size:8pt; font-weight:700; padding-bottom:.4mm; }}
	.bottom {{ display:grid; grid-template-columns:38mm 1fr; gap:2mm; align-items:start; }}
	.qr {{ width:37mm; height:37mm; }}
	table {{ width:100%; border-collapse:collapse; table-layout:fixed; font-size:6.5pt; }}
	th {{ width:17mm; text-align:left; vertical-align:top; padding:1.2mm 1mm 1.2mm 0; line-height:1.35; }}
	td {{ vertical-align:top; padding:1.2mm .5mm; overflow-wrap:anywhere; line-height:1.35; }}
	td.quantity {{ border-bottom:.25mm solid #777; font-size:7.5pt; font-weight:700; }}
	"""

	def render_pdf(number_of_labels, document_title, sheet_counts=None):
		if sheet_counts:
			body = "".join(
				'<section class="sheet">' + "".join(label for _ in range(count)) + "</section>"
				for count in sheet_counts
				if count
			)
			body_class = ' class="forced-pages"'
		else:
			body = "".join(label for _ in range(number_of_labels))
			body_class = ""
		return HTML(
			string=f"<html><head><title>{escape(document_title)}</title><style>{styles}</style></head><body{body_class}>{body}</body></html>"
		).write_pdf()

	if frappe.utils.cint(master_sheet):
		labels_per_sheet = 6 if landscape else 4
		full_sheet_copies, remaining_labels = divmod(label_count, labels_per_sheet)
		master_label_count = labels_per_sheet if full_sheet_copies else remaining_labels
		copies_required = full_sheet_copies or 1
		master_title = f"{doc.name} - PAGE 1 ENTER {copies_required} {'COPY' if copies_required == 1 else 'COPIES'}"
		pdf = render_pdf(master_label_count, master_title, sheet_counts=[master_label_count])
		remaining_title = f"{doc.name} - REMAINDER ENTER 1 COPY"
		remaining_pdf = (
			render_pdf(remaining_labels, remaining_title, sheet_counts=[remaining_labels])
			if remaining_labels
			else b""
		)
		return {
			"success": True,
			"filename": f"{master_title}.pdf",
			"remainder_filename": f"{remaining_title}.pdf" if remaining_pdf else "",
			"label_count": label_count,
			"labels_per_sheet": labels_per_sheet,
			"copies_required": copies_required,
			"remaining_labels": remaining_labels if full_sheet_copies else 0,
			"pdf_base64": base64.b64encode(pdf).decode(),
			"remaining_pdf_base64": base64.b64encode(remaining_pdf).decode() if remaining_pdf else "",
		}

	pdf = render_pdf(label_count, f"{doc.name} - {label_count} PACKING LABELS")
	return {
		"success": True,
		"filename": f"{doc.name}-packing-labels.pdf",
		"label_count": label_count,
		"pdf_base64": base64.b64encode(pdf).decode(),
	}
