"""Direct raw ESC/P printing for the locally attached Epson LX-310."""

import base64
import subprocess
import unicodedata

import frappe


PRINTER_CONFIG_KEY = "lx310_printer_name"
PAGE_WIDTH = 80
FOOTER_LINE = 48


def _ascii(value):
    value = str(value or "")
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def _amount(value):
    return f"{float(value or 0):,.2f}"


def _place(line, column, value, width=None):
    value = _ascii(value).replace("\r", " ").replace("\n", " ")
    if width is not None:
        value = value[:width]
    if column >= PAGE_WIDTH:
        return line
    value = value[: PAGE_WIDTH - column]
    return f"{line[:column]}{value}{line[column + len(value):]}"


def _blank_lines(count):
    return [" " * PAGE_WIDTH for _ in range(count)]


def _raw_purchase_order(doc):
    lines = _blank_lines(FOOTER_LINE + 1)
    contact = frappe.db.get_value("Contact", doc.contact_person, "first_name") if doc.contact_person else ""
    warehouse = (doc.items[0].warehouse if doc.items and doc.items[0].warehouse else doc.set_warehouse) or ""
    material_request = (doc.items[0].material_request if doc.items else "") or ""

    lines[0] = _place(lines[0], 7, doc.supplier_name, 43)
    lines[0] = _place(lines[0], 54, frappe.utils.formatdate(doc.transaction_date, "MM/dd/yyyy"), 12)
    lines[0] = _place(lines[0], 68, doc.name, 12)
    lines[1] = _place(lines[1], 7, contact, 43)
    lines[1] = _place(lines[1], 54, doc.payment_terms_template, 12)
    lines[1] = _place(lines[1], 68, warehouse, 12)
    lines[2] = _place(lines[2], 54, doc.schedule_date, 12)
    lines[2] = _place(lines[2], 68, material_request, 12)

    row_number = 7
    for item in doc.items[: FOOTER_LINE - row_number - 3]:
        lines[row_number] = _place(lines[row_number], 0, frappe.utils.flt(item.qty, 0), 5)
        lines[row_number] = _place(lines[row_number], 8, item.uom, 8)
        lines[row_number] = _place(lines[row_number], 18, item.item_name, 41)
        lines[row_number] = _place(lines[row_number], 61, _amount(item.rate), 9)
        lines[row_number] = _place(lines[row_number], 71, _amount(item.amount), 9)
        row_number += 1

    lines[row_number] = _place(lines[row_number], 71, "_" * 9)
    lines[row_number + 1] = _place(lines[row_number + 1], 18, doc.custom_remarks, 41)
    lines[row_number + 1] = _place(lines[row_number + 1], 71, _amount(doc.total), 9)

    owner_name = frappe.db.get_value("User", doc.owner, "full_name") or ""
    request_type = ""
    if material_request:
        request_type = frappe.db.get_value("Material Request", material_request, "custom_request_type") or ""
    approver = "ASC" if doc.custom_is_approved_by_asc_sir_tony else "ALEX S. CHUA"

    lines[FOOTER_LINE] = _place(lines[FOOTER_LINE], 0, doc.custom_request_by, 18)
    lines[FOOTER_LINE] = _place(lines[FOOTER_LINE], 20, owner_name, 18)
    lines[FOOTER_LINE] = _place(
        lines[FOOTER_LINE],
        40,
        "Abe Chua" if request_type == "Office Supplies & Equipment" else "Edith Manuel",
        18,
    )
    lines[FOOTER_LINE] = _place(lines[FOOTER_LINE], 60, approver, 20)

    # ESC @ reset, ESC x 1 Letter Quality, ESC P 10 CPI, CR/LF text, form feed.
    payload = bytearray((27, 64, 27, 120, 1, 27, 80))
    for line in lines:
        payload.extend(_ascii(line).encode("cp437", "replace"))
        payload.extend(b"\r\n")
    payload.append(12)
    return bytes(payload)


def _powershell_command(printer_name, payload):
    encoded_payload = base64.b64encode(payload).decode()
    script = f'''
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class RawPrinter {{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
    public class DOCINFOA {{
        [MarshalAs(UnmanagedType.LPStr)] public string pDocName;
        [MarshalAs(UnmanagedType.LPStr)] public string pOutputFile;
        [MarshalAs(UnmanagedType.LPStr)] public string pDataType;
    }}
    [DllImport("winspool.drv", EntryPoint="OpenPrinterA", SetLastError=true)] public static extern bool OpenPrinter(string name, out IntPtr handle, IntPtr defaults);
    [DllImport("winspool.drv", SetLastError=true)] public static extern bool ClosePrinter(IntPtr handle);
    [DllImport("winspool.drv", EntryPoint="StartDocPrinterA", SetLastError=true)] public static extern int StartDocPrinter(IntPtr handle, int level, [In] DOCINFOA info);
    [DllImport("winspool.drv", SetLastError=true)] public static extern bool EndDocPrinter(IntPtr handle);
    [DllImport("winspool.drv", SetLastError=true)] public static extern bool StartPagePrinter(IntPtr handle);
    [DllImport("winspool.drv", SetLastError=true)] public static extern bool EndPagePrinter(IntPtr handle);
    [DllImport("winspool.drv", SetLastError=true)] public static extern bool WritePrinter(IntPtr handle, byte[] bytes, int count, out int written);
}}
'@
$handle = [IntPtr]::Zero
if (-not [RawPrinter]::OpenPrinter('{printer_name}', [ref]$handle, [IntPtr]::Zero)) {{ throw "OpenPrinter failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())" }}
try {{
    $info = New-Object RawPrinter+DOCINFOA
    $info.pDocName = 'ERPNext Purchase Order'
    $info.pDataType = 'RAW'
    if ([RawPrinter]::StartDocPrinter($handle, 1, $info) -eq 0) {{ throw "StartDocPrinter failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())" }}
    try {{
        if (-not [RawPrinter]::StartPagePrinter($handle)) {{ throw "StartPagePrinter failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())" }}
        try {{
            $bytes = [Convert]::FromBase64String('{encoded_payload}')
            $written = 0
            if (-not [RawPrinter]::WritePrinter($handle, $bytes, $bytes.Length, [ref]$written)) {{ throw "WritePrinter failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())" }}
            Write-Output $written
        }} finally {{ [RawPrinter]::EndPagePrinter($handle) | Out-Null }}
    }} finally {{ [RawPrinter]::EndDocPrinter($handle) | Out-Null }}
}} finally {{ if ($handle -ne [IntPtr]::Zero) {{ [RawPrinter]::ClosePrinter($handle) | Out-Null }} }}
'''
    encoded_script = base64.b64encode(script.encode("utf-16le")).decode()
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_script]


@frappe.whitelist()
def print_purchase_order(name):
    """Print a Purchase Order to the workstation's Epson LX-310 in raw ESC/P."""
    doc = frappe.get_doc("Purchase Order", name)
    doc.check_permission("print")
    printer_name = frappe.conf.get(PRINTER_CONFIG_KEY)
    if not printer_name:
        frappe.throw("LX-310 printer is not configured for this site.")

    try:
        result = subprocess.run(
            _powershell_command(printer_name, _raw_purchase_order(doc)),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        frappe.throw("Windows PowerShell is unavailable; raw LX-310 printing requires this local WSL workstation.")
    except subprocess.TimeoutExpired:
        frappe.throw("The LX-310 raw print job timed out.")

    if result.returncode:
        frappe.throw(result.stderr.strip() or "The LX-310 raw print job failed.")
    return {"message": f"Sent {result.stdout.strip() or 'raw'} bytes to {printer_name}."}
