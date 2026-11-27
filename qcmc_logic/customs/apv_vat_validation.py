"""Server-side APV VAT reference-table checks. No GL or invoice amount mutations."""
import frappe
from frappe import _
from frappe.utils import flt
from decimal import Decimal, ROUND_HALF_UP


def calculate_vat_detail(amount):
    value = Decimal(str(amount or 0))
    vat = (value * Decimal("12") / Decimal("112")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(vat), float(value - vat)


def update_vat_detail_amounts(doc, method=None):
    """Reference-only fields; never changes invoice totals, taxes, or GL."""
    for row in doc.get("custom_vat_details") or []:
        vat, pv = calculate_vat_detail(row.get("amount"))
        row.custom_vat_inclusive = vat
        row.custom_pv_amount = pv

SUPPORTED_COMPANIES = {"QC Styropackaging Corporation", "Multiplast Corporation"}


def validate_purchase_invoice(doc, method=None):
    """Validate only when submitting an invoice with VAT Detail rows."""
    if doc.company not in SUPPORTED_COMPANIES or not doc.get("custom_vat_details"):
        return
    is_return = bool(doc.get("is_return"))
    for idx, row in enumerate(doc.get("custom_vat_details"), 1):
        account = row.get("account_name")
        center = row.get("cost_center")
        amount = flt(row.get("amount"))
        if not account:
            frappe.throw(_("VAT Details row {0}: Expense Account is required.").format(idx))
        account_doc = frappe.db.get_value(
            "Account", account, ["company", "root_type", "is_group", "disabled"], as_dict=True
        )
        if not account_doc or account_doc.company != doc.company or account_doc.root_type != "Expense" or account_doc.is_group or account_doc.disabled:
            frappe.throw(_("VAT Details row {0}: select an enabled, non-group Expense Account for this company.").format(idx))
        if not center:
            frappe.throw(_("VAT Details row {0}: Cost Center is required.").format(idx))
        cc = frappe.db.get_value(
            "Cost Center", center, ["company", "is_group", "disabled"], as_dict=True
        )
        if not cc or cc.company != doc.company or cc.is_group or cc.disabled:
            frappe.throw(_("VAT Details row {0}: select an enabled, non-group Cost Center for this company.").format(idx))
        if (is_return and amount >= 0) or (not is_return and amount <= 0):
            frappe.throw(_("VAT Details row {0}: VAT amount must be {1}.").format(
                idx, _("negative for returns") if is_return else _("positive for normal invoices")
            ))
