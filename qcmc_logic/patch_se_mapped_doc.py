"""
Switch Material Issuance to open_mapped_doc; update SE client script to hide work_order.
Run with: bench --site erp.qcstyro.local execute qcmc_logic.patch_se_mapped_doc.run
"""
import json, os
import frappe

MSJR_SCRIPT_NAME = "Machine Shop Job Request Generate Project Plan"
SE_SCRIPT_NAME = "Stock Entry - MSJR No Field"

MSJR_SCRIPT_JS = """frappe.provide("qcmc_logic.machine_shop_job_request");

frappe.ui.form.on("Machine Shop Job Request", {
    refresh(frm) {
        if (frm.is_new() || frm.doc.docstatus === 2) return;

        if (["Acknowledge", "Received"].includes(frm.doc.workflow_state)) {
            frm.add_custom_button(__("Material Request"), function () {
                frappe.new_doc("Material Request", { msjr_reference: frm.doc.name });
            }, __("Create"));

            frm.add_custom_button(__("Material Issuance"), function () {
                frappe.model.open_mapped_doc({
                    method: "qcmc_logic.utils.make_material_issuance",
                    frm: frm,
                });
            }, __("Create"));

            frm.add_custom_button(__("Generate Project Plan"),
                () => qcmc_logic.machine_shop_job_request.make_project_plan(frm),
                __("Create")
            );
        }
    },
});

qcmc_logic.machine_shop_job_request.can_generate_project_plan = function (frm) {
    return !frm.is_new() && ["Acknowledge", "Received"].includes(frm.doc.workflow_state);
};

qcmc_logic.machine_shop_job_request.make_project_plan = function (frm) {
    if (!qcmc_logic.machine_shop_job_request.can_generate_project_plan(frm)) {
        frappe.msgprint(__("Project Plan can only be generated from a request in Acknowledge or Received state."));
        return;
    }
    frappe.model.open_mapped_doc({
        method: "qcmc_logic.utils.make_machine_shop_repairs_and_project",
        frm: frm,
    });
};
"""

SE_SCRIPT_JS = """
frappe.ui.form.on("Stock Entry", {
    refresh(frm) {
        const has_msjr = !!frm.doc.msjr_no;
        frm.set_df_property("msjr_no", "hidden", !has_msjr);
        frm.set_df_property("msjr_no", "read_only", 1);
        frm.set_df_property("work_order", "hidden", has_msjr);
        if (has_msjr) frm.refresh_field("msjr_no");
    },
});
"""


def _update_script(name, dt, js):
    if frappe.db.exists("Client Script", name):
        doc = frappe.get_doc("Client Script", name)
        doc.script = js
        doc.enabled = 1
        doc.flags.ignore_permissions = True
        doc.save()
        print(f"Updated: {name}")
    else:
        frappe.get_doc({
            "doctype": "Client Script",
            "name": name,
            "dt": dt,
            "view": "Form",
            "script": js,
            "enabled": 1,
        }).insert(ignore_permissions=True)
        print(f"Created: {name}")


def run():
    _update_script(MSJR_SCRIPT_NAME, "Machine Shop Job Request", MSJR_SCRIPT_JS)
    _update_script(SE_SCRIPT_NAME, "Stock Entry", SE_SCRIPT_JS)
    frappe.db.commit()

    # Sync fixture
    app_path = frappe.get_app_path("qcmc_logic")
    fixture_path = os.path.join(app_path, "fixtures", "client_script.json")
    with open(fixture_path) as f:
        scripts = json.load(f)

    updates = {
        MSJR_SCRIPT_NAME: MSJR_SCRIPT_JS,
        SE_SCRIPT_NAME: SE_SCRIPT_JS,
    }
    names_seen = set()
    for cs in scripts:
        n = cs.get("name")
        if n in updates:
            cs["script"] = updates[n]
            cs["enabled"] = 1
            names_seen.add(n)

    for name, js in updates.items():
        if name not in names_seen:
            dt = "Machine Shop Job Request" if "MSJR" in name or "Machine Shop" in name else "Stock Entry"
            scripts.append({
                "doctype": "Client Script",
                "name": name,
                "dt": dt,
                "view": "Form",
                "script": js,
                "enabled": 1,
            })

    with open(fixture_path, "w") as f:
        json.dump(scripts, f, indent=1, ensure_ascii=False)

    frappe.clear_cache()
    print("Fixtures synced. Done.")
