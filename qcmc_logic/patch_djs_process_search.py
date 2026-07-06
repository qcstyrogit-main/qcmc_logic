"""
Update Daily Job Schedule client script to use a custom server-side search
for the Process field, so the dropdown shows readable machine names.

Run with:
    bench --site erp.qcstyro.local execute qcmc_logic.patch_djs_process_search.run
"""
import json
import os
import frappe

SCRIPT_NAME = "Daily Job Schedule - Filters and Auto-populate"

NEW_SCRIPT_JS = r"""frappe.ui.form.on("Daily Job Schedule", {
    refresh(frm) {
        qcmc_logic.djs.set_queries(frm);
        qcmc_logic.djs.ensure_process_titles(frm);
    },
    onload(frm) {
        qcmc_logic.djs.set_queries(frm);
    },
    shift(frm) {
        var times = {DS: ["07:00:00", "19:00:00"], NS: ["19:00:00", "07:00:00"]};
        var t = times[frm.doc.shift];
        if (t) { frm.set_value("time_from", t[0]); frm.set_value("time_to", t[1]); }
    },
    before_save(frm) {
        // Auto-fill time_from / time_to based on shift
        var times = {DS: ["07:00:00", "19:00:00"], NS: ["19:00:00", "07:00:00"]};
        var t = times[frm.doc.shift];
        if (t) { frm.doc.time_from = t[0]; frm.doc.time_to = t[1]; }
        if (!frm.doc.sched_date || !frm.doc.shift) return;
        return frappe.db.get_list("Daily Job Schedule", {
            filters: {
                sched_date: frm.doc.sched_date,
                shift: frm.doc.shift,
                name: ["!=", frm.doc.name || ""]
            },
            limit: 1
        }).then(function(results) {
            if (results && results.length > 0) {
                frappe.throw(
                    __("A {0} shift already exists for {1}. Only one {0} shift is allowed per day.",
                        [frm.doc.shift, frm.doc.sched_date])
                );
            }
        });
    }
});

frappe.ui.form.on("Job Schedule", {
    msrp_no(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        frappe.model.set_value(cdt, cdn, "msjr_no", "");
        frappe.model.set_value(cdt, cdn, "process", "");
        frappe.model.set_value(cdt, cdn, "activity", "");
        frappe.model.set_value(cdt, cdn, "machine", "");
        frappe.model.set_value(cdt, cdn, "bal_hr", 0);
        frappe.model.set_value(cdt, cdn, "quantity", 0);
        if (!row || !row.msrp_no) {
            frm.refresh_field("job_schedule");
            return;
        }
        frappe.db.get_value("Machine Shop Repairs and Project", row.msrp_no, "msjr_no", function(val) {
            if (val && val.msjr_no) {
                frappe.model.set_value(cdt, cdn, "msjr_no", val.msjr_no);
            }
            frm.refresh_field("job_schedule");
        });
    },

    msjr_no(frm, cdt, cdn) {
        frappe.model.set_value(cdt, cdn, "process", "");
        frappe.model.set_value(cdt, cdn, "activity", "");
        frappe.model.set_value(cdt, cdn, "machine", "");
        frappe.model.set_value(cdt, cdn, "bal_hr", 0);
        frappe.model.set_value(cdt, cdn, "quantity", 0);
        frm.refresh_field("job_schedule");
    },

    process(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        if (!row || !row.process) {
            frappe.model.set_value(cdt, cdn, "activity", "");
            frappe.model.set_value(cdt, cdn, "machine", "");
            frappe.model.set_value(cdt, cdn, "bal_hr", 0);
            frappe.model.set_value(cdt, cdn, "quantity", 0);
            return;
        }
        frappe.call({
            method: "qcmc_logic.utils.get_process_schedule_details",
            args: { process_no: row.process },
            callback: function(r) {
                if (r && r.message) {
                    frappe.model.set_value(cdt, cdn, "activity", r.message.process_name || "");
                    frappe.model.set_value(cdt, cdn, "machine", r.message.machine || "");
                    frappe.model.set_value(cdt, cdn, "bal_hr", r.message.bal_hr || 0);
                    frappe.model.set_value(cdt, cdn, "quantity", r.message.remaining_qty || 0);
                    if (r.message.process_name) {
                        qcmc_logic.djs.cache_process_title(row.process, r.message.process_name);
                    }
                    frm.fields_dict.job_schedule.grid.refresh();
                }
            }
        });
    },

    form_render(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        if (row && row.process) {
            frappe.call({
                method: "qcmc_logic.utils.get_process_schedule_details",
                args: { process_no: row.process },
                callback: function(r) {
                    if (r && r.message && r.message.process_name) {
                        qcmc_logic.djs.cache_process_title(row.process, r.message.process_name);
                        frm.refresh_field("job_schedule");
                    }
                }
            });
        }
        qcmc_logic.djs.set_process_query(frm, cdt, cdn);
    }
});

frappe.provide("qcmc_logic.djs");

qcmc_logic.djs.cache_process_title = function(process_no, process_name) {
    frappe.utils.add_link_title("Machine Shop Repairs and Project Process", process_no, process_name);
    if (!frappe.boot.link_title_doctypes) frappe.boot.link_title_doctypes = [];
    if (!frappe.boot.link_title_doctypes.includes("Machine Shop Repairs and Project Process")) {
        frappe.boot.link_title_doctypes.push("Machine Shop Repairs and Project Process");
    }
};

qcmc_logic.djs.ensure_process_titles = function(frm) {
    if (!frappe.boot.link_title_doctypes) frappe.boot.link_title_doctypes = [];
    if (!frappe.boot.link_title_doctypes.includes("Machine Shop Repairs and Project Process")) {
        frappe.boot.link_title_doctypes.push("Machine Shop Repairs and Project Process");
    }
    var rows = (frm.doc.job_schedule || []).filter(function(r) { return r.process; });
    if (!rows.length) return;
    var pending = rows.length;
    rows.forEach(function(row) {
        frappe.call({
            method: "qcmc_logic.utils.get_process_schedule_details",
            args: { process_no: row.process },
            callback: function(r) {
                if (r && r.message && r.message.process_name) {
                    qcmc_logic.djs.cache_process_title(row.process, r.message.process_name);
                }
                pending--;
                if (pending === 0) {
                    frm.fields_dict.job_schedule.grid.refresh();
                }
            }
        });
    });
};

qcmc_logic.djs.set_queries = function(frm) {
    frm.set_query("leadman", () => ({
        filters: {
            status: "Active",
            designation: ["in", ["Engineering Foreman", "Engineering Leadman"]]
        }
    }));

    frm.set_query("employee", "job_schedule", () => ({
        filters: {
            status: "Active",
            department: ["like", "%Engineering%"]
        }
    }));

    frm.set_query("msrp_no", "job_schedule", () => ({
        filters: { workflow_state: "Active" }
    }));

    frm.set_query("process", "job_schedule", (doc, cdt, cdn) => {
        var row = locals[cdt][cdn];
        return {
            query: "qcmc_logic.utils.search_msrp_process",
            filters: {
                parent: (row && row.msrp_no) || "",
                parenttype: "Machine Shop Repairs and Project"
            }
        };
    });
};

qcmc_logic.djs.set_process_query = function(frm, cdt, cdn) {
    frm.fields_dict.job_schedule.grid.get_field("process").get_query = (doc, cdt, cdn) => {
        var row = locals[cdt][cdn];
        return {
            query: "qcmc_logic.utils.search_msrp_process",
            filters: {
                parent: (row && row.msrp_no) || "",
                parenttype: "Machine Shop Repairs and Project"
            }
        };
    };
};

// Direct model-level autofill for shift field
frappe.model.on("Daily Job Schedule", "shift", function(fieldname, value, doc) {
    var times = {DS: ["07:00:00", "19:00:00"], NS: ["19:00:00", "07:00:00"]};
    var t = times[value];
    if (!t) return;
    frappe.model.set_value(doc.doctype, doc.name, "time_from", t[0]);
    frappe.model.set_value(doc.doctype, doc.name, "time_to", t[1]);
});
"""


def run():
    if frappe.db.exists("Client Script", SCRIPT_NAME):
        doc = frappe.get_doc("Client Script", SCRIPT_NAME)
        doc.script = NEW_SCRIPT_JS
        doc.enabled = 1
        doc.flags.ignore_permissions = True
        doc.save()
        print(f"Updated: {SCRIPT_NAME}")
    else:
        frappe.get_doc({
            "doctype": "Client Script",
            "name": SCRIPT_NAME,
            "dt": "Daily Job Schedule",
            "view": "Form",
            "script": NEW_SCRIPT_JS,
            "enabled": 1,
        }).insert(ignore_permissions=True)
        print(f"Created: {SCRIPT_NAME}")

    frappe.db.commit()

    # Sync fixture
    app_path = frappe.get_app_path("qcmc_logic")
    fixture_path = os.path.join(app_path, "fixtures", "client_script.json")
    with open(fixture_path) as f:
        scripts = json.load(f)

    updated = False
    for cs in scripts:
        if cs.get("name") == SCRIPT_NAME:
            cs["script"] = NEW_SCRIPT_JS
            cs["enabled"] = 1
            updated = True
            break

    if not updated:
        scripts.append({
            "doctype": "Client Script",
            "name": SCRIPT_NAME,
            "dt": "Daily Job Schedule",
            "view": "Form",
            "script": NEW_SCRIPT_JS,
            "enabled": 1,
        })

    with open(fixture_path, "w") as f:
        json.dump(scripts, f, indent=1, ensure_ascii=False)

    frappe.clear_cache(doctype="Daily Job Schedule")
    print("Fixture client_script.json updated. Done.")
