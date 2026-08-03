import frappe
from frappe import _

from qcmc_logic.utils import _get_user_role_profiles


CONFIG_DOCTYPES = {"Role Profile Territory", "Role Profile Territory Detail"}


def get_user_allowed_territories(user=None, require_transactions=False):
    user = user or frappe.session.user
    if user == "Administrator" or not frappe.db.table_exists("Role Profile Territory"):
        return []

    role_profiles = _get_user_role_profiles(user)
    if not role_profiles:
        return []

    filters = {
        "parenttype": "Role Profile Territory",
        "parent": ["in", role_profiles],
    }
    if frappe.utils.cint(require_transactions):
        filters["allow_transactions"] = 1

    return frappe.get_all(
        "Role Profile Territory Detail",
        filters=filters,
        pluck="territory",
        order_by="idx",
    )


def has_territory_access(user=None):
    user = user or frappe.session.user
    if user == "Administrator" or not frappe.db.table_exists("Role Profile Territory"):
        return False

    role_profiles = _get_user_role_profiles(user)
    return bool(
        role_profiles
        and frappe.db.exists(
            "Role Profile Territory", {"role_profile": ["in", role_profiles]}
        )
    )


def validate_territory_access(doc, method=None):
    user = frappe.session.user
    if (
        user == "Administrator"
        or doc.doctype in CONFIG_DOCTYPES
        or not has_territory_access(user)
    ):
        return

    territory_fields = [
        df.fieldname
        for df in doc.meta.fields
        if df.fieldtype == "Link" and df.options == "Territory"
    ]
    if not territory_fields:
        return

    allowed = set(get_user_allowed_territories(user, require_transactions=True))
    for fieldname in territory_fields:
        territory = doc.get(fieldname)
        if territory and territory not in allowed:
            frappe.throw(
                _("{0} is not allowed for Territory.").format(frappe.bold(territory))
            )


def territory_permission_query(doctype, user=None):
    user = user or frappe.session.user
    if not has_territory_access(user) or not frappe.get_meta(doctype).has_field("territory"):
        return ""

    allowed = get_user_allowed_territories(user)
    if not allowed:
        return "1=0"

    values = ", ".join(frappe.db.escape(value) for value in allowed)
    return f"`tab{doctype}`.`territory` IN ({values})"


def territory_has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    if not has_territory_access(user) or ptype == "create":
        return True
    if not doc or not doc.meta.has_field("territory") or not doc.get("territory"):
        return True

    require_transactions = ptype in {"write", "submit", "cancel", "delete", "amend"}
    allowed = set(get_user_allowed_territories(user, require_transactions))
    return doc.get("territory") in allowed

