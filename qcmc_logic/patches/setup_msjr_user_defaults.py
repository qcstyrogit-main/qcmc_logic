"""Install the MSJR form code with user-based Section and Company defaults."""

import frappe

from qcmc_logic.customs.machine_shop_job_request import ensure_msjr_client_script


def execute():
    if not frappe.db.exists("DocType", "Machine Shop Job Request"):
        return

    # Custom DocTypes use the saved Client Script rather than doctype_js hooks.
    # Reuse the installer to update existing sites without duplicating form code.
    # Section mappings and user Company defaults remain site-managed settings.
    ensure_msjr_client_script()
