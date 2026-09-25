import json

import frappe


CLIENT_SCRIPT = "Purchase Order LX-310 Raw Print"


def execute():
    """Install the workstation-only LX-310 Purchase Order print action."""
    fixture_path = frappe.get_app_path("qcmc_logic", "fixtures", "client_script.json")
    with open(fixture_path) as fixture_file:
        script_data = next(
            row for row in json.load(fixture_file) if row.get("name") == CLIENT_SCRIPT
        )

    if frappe.db.exists("Client Script", CLIENT_SCRIPT):
        doc = frappe.get_doc("Client Script", CLIENT_SCRIPT)
    else:
        doc = frappe.new_doc("Client Script")
        doc.name = CLIENT_SCRIPT

    doc.update(script_data)
    doc.save(ignore_permissions=True)
    frappe.clear_cache(doctype="Client Script")
