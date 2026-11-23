"""Render a compact, scannable WTS QR code for Jinja print formats.

Encodes the exact Warehouse Transfer document name (no prefix, suffix, or URL).
Uses PyQRCode, which is a declared Frappe dependency.
"""
from html import escape

from markupsafe import Markup
import pyqrcode


def get_wts_qr_svg(value):
    value = str(value or "")
    if not value or len(value) > 128 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return Markup("")

    matrix = pyqrcode.create(value, error="M", encoding="utf-8").code
    module_count = len(matrix)
    quiet = 4
    total = module_count + quiet * 2
    rects = []
    for row_index, row in enumerate(matrix):
        start = None
        for column in range(module_count + 1):
            dark = column < module_count and bool(row[column])
            if dark and start is None:
                start = column
            elif not dark and start is not None:
                rects.append(
                    f'<rect x="{start + quiet}" y="{row_index + quiet}" '
                    f'width="{column - start}" height="1"/>'
                )
                start = None

    return Markup(
        '<svg class="qcmc-wts-qr" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="Warehouse Transfer QR {escape(value, quote=True)}" '
        f'viewBox="0 0 {total} {total}" width="64" height="64" '
        'style="display:block;width:64px;height:64px;max-width:100%;'
        'background:white;shape-rendering:crispEdges" preserveAspectRatio="xMidYMid meet">'
        f'<rect x="0" y="0" width="{total}" height="{total}" fill="#fff"/>'
        '<g fill="#000">' + "".join(rects) + "</g></svg>"
    )
