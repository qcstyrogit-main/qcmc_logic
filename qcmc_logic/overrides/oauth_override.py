import frappe

@frappe.whitelist(allow_guest=True)
def protected_resource_metadata():
    base = frappe.utils.get_url()

    return {
        "resource": base + "/api/method/frappe_assistant_core.api.fac_endpoint.handle_mcp",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "resource_name": "Frappe Assistant Core",
        "resource_documentation": "https://github.com/buildswithpaul/Frappe_Assistant_Core"
    }