import frappe
from frappe import _

from qcmc_logic.api.material_scanner_labels import get_labels


def get_context(context):
    context.no_cache = 1
    context.title = _("Material Scanner QR Labels")
    if frappe.session.user == "Guest":
        frappe.throw(_("Please log in to print Item QR labels."), frappe.AuthenticationError)
    context.labels = get_labels(
        frappe.form_dict.get("items"), frappe.form_dict.get("pack_type") or "big"
    )
    return context
