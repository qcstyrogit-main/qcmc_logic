import frappe

def get_context(context):
    """Check if user is logged in and has appropriate roles to access the courses page."""
    user = frappe.session.user

    # Allow System Managers & LMS Managers
    allowed_roles = ["System Manager", "LMS Manager"]

    if not any(role in frappe.get_roles(user) for role in allowed_roles):
        frappe.local.flags.redirect_location = "/lms/my-courses"
        raise frappe.Redirect

    context.no_cache = 1