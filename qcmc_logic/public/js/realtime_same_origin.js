/* Development tunnels use the same socket URL as a production reverse proxy. */
(() => {
    if (!frappe.boot?.qcmc_realtime_same_origin || !window.dev_server || !frappe.realtime) return;
    try {
        if (new URL(frappe.boot.qcmc_realtime_proxy_origin).origin !== window.location.origin) return;
    } catch (error) {return;}
    frappe.realtime.get_host = () => `${window.location.origin}/${frappe.boot.sitename}`;
})();
