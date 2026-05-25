frappe.provide("qcmc_logic.machine_shop_job_request");

console.log("Machine Shop Job Request client script loaded");

frappe.ui.form.on("Machine Shop Job Request", {
    refresh(frm) {
        console.log("Machine Shop Job Request refresh", {
            name: frm.doc.name,
            is_new: frm.is_new(),
            docstatus: frm.doc.docstatus,
            workflow_state: frm.doc.workflow_state,
            can_generate_project_plan: qcmc_logic.machine_shop_job_request.can_generate_project_plan(frm),
        });

        if (qcmc_logic.machine_shop_job_request.can_generate_project_plan(frm)) {
            frm.add_custom_button(
                __("Generate Project Plan"),
                () => qcmc_logic.machine_shop_job_request.make_project_plan(frm),
                __("Create")
            );
        }
    },

    generate_plan(frm) {
        console.log("Generate Project Plan button clicked", frm.doc.name, frm.doc.workflow_state);
        qcmc_logic.machine_shop_job_request.make_project_plan(frm);
    },
});

qcmc_logic.machine_shop_job_request.can_generate_project_plan = function(frm) {
    return !frm.is_new() && frm.doc.workflow_state === "Pending Machine Shop";
};

qcmc_logic.machine_shop_job_request.make_project_plan = function(frm) {
    console.log("make_project_plan called", frm.doc.name, frm.doc.workflow_state);

    if (!qcmc_logic.machine_shop_job_request.can_generate_project_plan(frm)) {
        frappe.msgprint(__("Project Plan can only be generated from a saved request in Pending Machine Shop."));
        return;
    }

    frappe.model.open_mapped_doc({
        method: "qcmc_logic.utils.make_machine_shop_repairs_and_project",
        frm: frm,
    });
};
