import frappe
import qrcode
from io import BytesIO
import base64
import barcode
from barcode.writer import ImageWriter

@frappe.whitelist()
def generate_qr(item_code):
    """Generate a QR code for the given item code and return it as a base64-encoded PNG."""
    img = qrcode.make(item_code)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{encoded}"

@frappe.whitelist()
def generate_barcode(item_code):
    """Generate a Code128 barcode for the given item code and return it as a base64-encoded PNG."""
    CODE128 = barcode.get_barcode_class('code128')
    code = CODE128(item_code, writer=ImageWriter())
    buffer = BytesIO()
    code.write(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{encoded}"
