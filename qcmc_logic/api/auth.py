# qcmc_logic/api/auth.py
import frappe

@frappe.whitelist(allow_guest=True)
def check_log_user():
    """Check if the user is logged in and return user information."""
    if frappe.session.user == "Guest":
        return {"logged_in": False}
    return {
        "logged_in": True,
        "user": frappe.session.user,
        "full_name": frappe.get_value("User", frappe.session.user, "full_name")
    }
