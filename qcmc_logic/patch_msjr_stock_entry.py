"""
Add MSJR No reference field to Stock Entry, wire DocType Link, update client script.
Run with: bench --site erp.qcstyro.local execute qcmc_logic.patch_msjr_stock_entry.run
"""
import json, os
import frappe


def run():
    _add_custom_field()
    _add_doctype_link()
    _update_client_script()
    frappe.db.commit()
    frappe.clear_cache()
    print("Done.")


# ---------------------------------------------------------------------------
# 1. Custom field: Stock Entry.msjr_no
# ---------------------------------------------------------------------------

def _add_custom_field():
    if frappe.db.exists("Custom Field", "Stock Entry-msjr_no"):
        print("Custom field Stock Entry-msjr_no already exists — skipping.")
        return

    frappe.get_doc({
        "doctype": "Custom Field",
        "dt": "Stock Entry",
        "fieldname": "msjr_no",
        "label": "MSJR No",
        "fieldtype": "Data",
        "insert_after": "custom_request_form_no",
        "read_only": 1,
        "in_standard_filter": 1,
        "depends_on": "eval:doc.msjr_no",
        "no_copy": 1,
    }).insert(ignore_permissions=True)
    print("Custom field Stock Entry-msjr_no created.")


# ---------------------------------------------------------------------------
# 2. DocType Link: Machine Shop Job Request → Stock Entry
# ---------------------------------------------------------------------------

def _add_doctype_link():
    exists = frappe.db.exists(
        "DocType Link",
        {"parent": "Machine Shop Job Request", "link_doctype": "Stock Entry"},
    )
    if exists:
        print("DocType Link MSJR → Stock Entry already exists — skipping.")
        return

    frappe.get_doc({
        "doctype": "DocType Link",
        "parent": "Machine Shop Job Request",
        "parenttype": "DocType",
        "parentfield": "links",
        "link_doctype": "Stock Entry",
        "link_fieldname": "msjr_no",
        "group": "References",
    }).insert(ignore_permissions=True)
    print("DocType Link MSJR → Stock Entry created.")


# ---------------------------------------------------------------------------
# 3. Update client script with Material Issuance button
# ---------------------------------------------------------------------------

NEW_SCRIPT = '''frappe.provide("qcmc_logic.machine_shop_job_request");

frappe.ui.form.on("Machine Shop Job Request", {
    refresh(frm) {
        if (frm.is_new() || frm.doc.docstatus === 2) return;

        if (["Acknowledge", "Received"].includes(frm.doc.workflow_state)) {
            frm.add_custom_button(__("Material Request"), function () {
                frappe.new_doc("Material Request", { msjr_reference: frm.doc.name });
            }, __("Create"));

            frm.add_custom_button(__("Material Issuance"), function () {
                frappe.new_doc("Stock Entry", {
                    stock_entry_type: "Material Issue",
                    msjr_no: frm.doc.name,
                    company: frm.doc.company,
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
'''


def _update_client_script():
    name = "Machine Shop Job Request Generate Project Plan"
    if not frappe.db.exists("Client Script", name):
        print(f"Client Script '{name}' not found — skipping.")
        return

    doc = frappe.get_doc("Client Script", name)
    doc.script = NEW_SCRIPT
    doc.enabled = 1
    doc.flags.ignore_permissions = True
    doc.save()
    print(f"Client Script '{name}' updated.")

    # Also sync fixture file
    app_path = frappe.get_app_path("qcmc_logic")
    fixture_path = os.path.join(app_path, "fixtures", "client_script.json")
    with open(fixture_path) as f:
        scripts = json.load(f)
    for cs in scripts:
        if cs.get("name") == name:
            cs["script"] = NEW_SCRIPT
            break
    with open(fixture_path, "w") as f:
        json.dump(scripts, f, indent=1, ensure_ascii=False)
    print("Fixture client_script.json updated.")
