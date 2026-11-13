"""Render a self-contained CODE128-B SVG for Warehouse Transfer document names.

No external service, browser JavaScript or extra Python package is required.
The encoded value is EXACTLY doc.name, including letter case and hyphens.
"""
from html import escape

from markupsafe import Markup

# Code128 patterns indexed by symbol value; each alphabetic width uses
# A/a = 1 module, B/b = 2, C/c = 3, D/d = 4.
_PATTERNS = (
    "BaBbBb|BbBaBb|BbBbBa|AbAbBc|AbAcBb|AcAbBb|AbBbAc|AbBcAb|"
    "AcBbAb|BbAbAc|BbAcAb|BcAbAb|AaBbCb|AbBaCb|AbBbCa|AaCbBb|"
    "AbCaBb|AbCbBa|BbCbAa|BbAaCb|BbAbCa|BaCbAb|BbCaAb|CaBaCa|"
    "CaAbBb|CbAaBb|CbAbBa|CaBbAb|CbBaAb|CbBbAa|BaBaBc|BaBcBa|"
    "BcBaBa|AaAcBc|AcAaBc|AcAcBa|AaBcAc|AcBaAc|AcBcAa|BaAcAc|"
    "BcAaAc|BcAcAa|AaBaCc|AaBcCa|AcBaCa|AaCaBc|AaCcBa|AcCaBa|"
    "CaCaBa|BaAcCa|BcAaCa|BaCaAc|BaCcAa|BaCaCa|CaAaBc|CaAcBa|"
    "CcAaBa|CaBaAc|CaBcAa|CcBaAa|CaDaAa|BbAdAa|DcAaAa|AaAbBd|"
    "AaAdBb|AbAaBd|AbAdBa|AdAaBb|AdAbBa|AaBbAd|AaBdAb|AbBaAd|"
    "AbBdAa|AdBaAb|AdBbAa|BdAbAa|BbAaAd|DaCaAa|BdAaAb|AcDaAa|"
    "AaAbDb|AbAaDb|AbAbDa|AaDbAb|AbDaAb|AbDbAa|DaAbAb|DbAaAb|"
    "DbAbAa|BaBaDa|BaDaBa|DaBaBa|AaAaDc|AaAcDa|AcAaDa|AaDaAc|"
    "AaDcAa|DaAaAc|DaAcAa|AaCaDa|AaDaCa|CaAaDa|DaAaCa|BaAdAb|"
    "BaAbAd|BaAbCb|BcCaAaB"
).split("|")


def get_wts_code128_svg(value):
    """Jinja-safe inline SVG barcode encoding the supplied WTS document name."""
    value = str(value or "")
    if not value or len(value) > 80 or any(ord(ch) < 32 or ord(ch) > 126 for ch in value):
        return Markup("")
    values = [104] + [ord(ch) - 32 for ch in value]  # START_B + Code Set B
    # CODE128 checksum: START code has weight 1, followed by data at positions 1..N.
    checksum = (values[0] + sum(i * symbol for i, symbol in enumerate(values[1:], 1))) % 103
    values += [checksum, 106]
    # Quiet zones: 12 modules on each side.
    x = 12
    bars = []
    for symbol in values:
        for index, char in enumerate(_PATTERNS[symbol]):
            width = ord(char.lower()) - ord("a") + 1
            if index % 2 == 0:
                bars.append(f'<rect x="{x}" y="0" width="{width}" height="48"/>')
            x += width
    total = x + 12
    svg = (
        f'<svg class="qcmc-wts-code128" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="Warehouse Transfer barcode {escape(value, quote=True)}" '
        f'viewBox="0 0 {total} 48" width="300" height="34" '
        f'style="display:block;width:300px;max-width:100%;height:34px;'
        f'background:white;shape-rendering:crispEdges" preserveAspectRatio="none">'
        '<g fill="#000">' + "".join(bars) + "</g></svg>"
    )
    return Markup(svg)
