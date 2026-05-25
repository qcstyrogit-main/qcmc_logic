frappe.ui.form.on("Machine Shop Job Request", {
    refresh(frm) {
        if (frm.doc.workflow_state === "Pending Machine Shop") {
            frm.add_custom_button(__("Generate Project Plan"), () => {
                frappe.call({
                    method: "qcmc_logic.utils.make_machine_shop_repairs_and_project",
                    args: { source_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Creating Project Plan..."),
                    callback(r) {
                        if (r.message) {
                            frappe.model.sync(r.message);
                            frappe.set_route("Form", r.message.doctype, r.message.name);
                        }
                    },
                });
            }, __("Create"));
        }
    },
});
