"""Read-only installed-site preflight for Purchase Invoice VAT Details."""
import frappe

EXPECTED = "qcmc_logic.customs.apv_vat_validation.validate_purchase_invoice"


def run():
    hooks = frappe.get_hooks("doc_events").get("Purchase Invoice", {})
    registered = hooks.get("before_submit", [])
    if isinstance(registered, str):
        registered = [registered]
    registered = list(registered)
    if EXPECTED not in registered:
        raise AssertionError(f"Missing Purchase Invoice before_submit hook: {EXPECTED}; found {registered}")
    resolved = frappe.get_attr(EXPECTED)
    if not callable(resolved):
        raise AssertionError("APV VAT validation hook does not resolve to a callable")
    meta = frappe.get_meta("Purchase Invoice")
    table = meta.get_field("custom_vat_details")
    if not table or table.fieldtype != "Table" or table.options != "Purchase Invoice VAT Detail":
        raise AssertionError("Purchase Invoice VAT Details child table is missing or misconfigured")
    child = frappe.get_meta("Purchase Invoice VAT Detail")
    for fieldname, fieldtype in (("account_name", "Link"), ("cost_center", "Link"), ("amount", "Currency")):
        field = child.get_field(fieldname)
        if not field or field.fieldtype != fieldtype:
            raise AssertionError(f"Child field {fieldname} missing or wrong type")
    print("APV VAT PREFLIGHT PASS: hook resolves; parent and child metadata match; no documents submitted.")
    return True
