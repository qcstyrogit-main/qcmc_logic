import frappe
from frappe.twofactor import get_qr_svg_code

@frappe.whitelist()
def generate_qr(item_code):
	"""Generate QR using Frappe's bundled implementation (no optional package)."""
	encoded = get_qr_svg_code(str(item_code or "").strip())
	if isinstance(encoded, bytes):
		encoded = encoded.decode()
	return f"data:image/svg+xml;base64,{encoded}"

@frappe.whitelist()
def generate_barcode(item_code):
	"""Generate a Code128 barcode for the given item code and return it as a base64-encoded PNG."""
	import base64
	from io import BytesIO

	import barcode
	from barcode.writer import ImageWriter

	code128 = barcode.get_barcode_class("code128")
	code = code128(item_code, writer=ImageWriter())
	buffer = BytesIO()
	code.write(buffer)
	encoded = base64.b64encode(buffer.getvalue()).decode()
	return f"data:image/png;base64,{encoded}"
