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

    # Fixture synchronization can leave a stale Document object in request
    # locals after deleting the DB row. Use a fresh DB lookup and avoid saving
    # that stale object during this migration.
    if frappe.db.get_value("Client Script", CLIENT_SCRIPT, "name"):
        values = {
            key: value
            for key, value in script_data.items()
            if key not in {"doctype", "name", "docstatus"}
        }
        frappe.db.set_value("Client Script", CLIENT_SCRIPT, values)
    else:
        frappe.get_doc(script_data).insert(ignore_permissions=True)

    frappe.clear_document_cache("Client Script", CLIENT_SCRIPT)
    frappe.clear_cache(doctype="Client Script")
