"""
Add Stock Entry client script to manage msjr_no field visibility/read-only.
Run with: bench --site erp.qcstyro.local execute qcmc_logic.patch_se_msjr_script.run
"""
import json, os
import frappe

SCRIPT_NAME = "Stock Entry - MSJR No Field"

SCRIPT_JS = """
frappe.ui.form.on("Stock Entry", {
    refresh(frm) {
        const has_msjr = !!frm.doc.msjr_no;
        frm.set_df_property("msjr_no", "hidden", !has_msjr);
        frm.set_df_property("msjr_no", "read_only", 1);
        if (has_msjr) frm.refresh_field("msjr_no");
    },
});
"""


def run():
    if frappe.db.exists("Client Script", SCRIPT_NAME):
        doc = frappe.get_doc("Client Script", SCRIPT_NAME)
        doc.script = SCRIPT_JS
        doc.enabled = 1
        doc.flags.ignore_permissions = True
        doc.save()
        print(f"Client Script '{SCRIPT_NAME}' updated.")
    else:
        frappe.get_doc({
            "doctype": "Client Script",
            "name": SCRIPT_NAME,
            "dt": "Stock Entry",
            "view": "Form",
            "script": SCRIPT_JS,
            "enabled": 1,
        }).insert(ignore_permissions=True)
        print(f"Client Script '{SCRIPT_NAME}' created.")

    frappe.db.commit()

    # Sync fixture
    app_path = frappe.get_app_path("qcmc_logic")
    fixture_path = os.path.join(app_path, "fixtures", "client_script.json")
    with open(fixture_path) as f:
        scripts = json.load(f)

    existing = next((s for s in scripts if s.get("name") == SCRIPT_NAME), None)
    if existing:
        existing["script"] = SCRIPT_JS
        existing["enabled"] = 1
    else:
        scripts.append({
            "name": SCRIPT_NAME,
            "dt": "Stock Entry",
            "view": "Form",
            "script": SCRIPT_JS,
            "enabled": 1,
            "doctype": "Client Script",
        })

    with open(fixture_path, "w") as f:
        json.dump(scripts, f, indent=1, ensure_ascii=False)

    # Also update custom_field fixture to reflect removed read_only / depends_on
    cf_path = os.path.join(app_path, "fixtures", "custom_field.json")
    with open(cf_path) as f:
        cfields = json.load(f)
    for cf in cfields:
        if cf.get("name") == "Stock Entry-msjr_no":
            cf["read_only"] = 0
            cf["depends_on"] = None
            break
    with open(cf_path, "w") as f:
        json.dump(cfields, f, indent=1, ensure_ascii=False)

    frappe.clear_cache(doctype="Stock Entry")
    print("Fixtures updated. Done.")
