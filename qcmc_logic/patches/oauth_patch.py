def ensure_fac_oauth_alias():
    import frappe
    import frappe.oauth as frappe_oauth
    import frappe_assistant_core.api.oauth_discovery as oauth_discovery
    import qcmc_logic.overrides.oauth_override as oauth_override

    # FAC imports this helper while handling the MCP request. Frappe's default
    # implementation reads the internal WSGI scheme (HTTP behind Funnel), so
    # its WWW-Authenticate challenge otherwise advertises an insecure URL.
    def get_public_server_url():
        return frappe.utils.get_url().rstrip("/")

    frappe_oauth.get_server_url = get_public_server_url

    oauth_discovery.protected_resource_metadata = oauth_override.protected_resource_metadata
    oauth_discovery.authorization_server_metadata = (
        oauth_override.authorization_server_metadata
    )
    frappe.logger().info(
        f"QCMC oauth patch applied: {oauth_discovery.protected_resource_metadata}"
    )
    
