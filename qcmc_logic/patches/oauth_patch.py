def ensure_fac_oauth_alias():
    import frappe
    import frappe_assistant_core.api.oauth_discovery as oauth_discovery
    import qcmc_logic.overrides.oauth_override as oauth_override

    oauth_discovery.protected_resource_metadata = oauth_override.protected_resource_metadata
    frappe.logger().info(
        f"QCMC oauth patch applied: {oauth_discovery.protected_resource_metadata}"
    )
    