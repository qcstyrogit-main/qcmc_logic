"""
Push updated MSJR client scripts from fixture to live DB.
Run with: bench --site erp.qcstyro.local execute qcmc_logic.patch_msjr_client_scripts.run
"""
import json, os, frappe


def run():
    app_path = frappe.get_app_path("qcmc_logic")
    fixture_path = os.path.join(app_path, "fixtures", "client_script.json")
    with open(fixture_path) as f:
        scripts = json.load(f)

    targets = {
        "Machine Shop Job Request - Auto Series and Project Plan",
        "Machine Shop Job Request Generate Project Plan",
    }

    for cs_data in scripts:
        if cs_data.get("name") not in targets:
            continue
        name = cs_data["name"]
        if not frappe.db.exists("Client Script", name):
            print(f"  SKIP (not in DB): {name}")
            continue
        doc = frappe.get_doc("Client Script", name)
        doc.script = cs_data["script"]
        doc.enabled = 1
        doc.flags.ignore_permissions = True
        doc.save()
        print(f"  Updated: {name}")

    frappe.db.commit()
    frappe.clear_cache(doctype="Machine Shop Job Request")
    print("Done.")
