frappe.provide("qcmc_logic.material_request");

frappe.ui.form.on("Material Request", {
    before_workflow_action(frm) {
        if (frm.doc.material_request_type !== "Purchase" ||
            !["Reject", "Return for Correction"].includes(frm.selected_workflow_action)) {
            return;
        }
        frappe.dom.unfreeze();
        return new Promise((resolve, reject) => {
            let accepted = false;
            const dialog = new frappe.ui.Dialog({
                title: __(frm.selected_workflow_action),
                fields: [{fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1}],
                primary_action_label: __(frm.selected_workflow_action),
                primary_action(values) {
                    if (!values.reason || !values.reason.trim()) {
                        frappe.msgprint(__("Please enter a reason."));
                        return;
                    }
                    frm.doc._qcmc_workflow_reason = values.reason.trim();
                    accepted = true;
                    dialog.hide();
                    resolve();
                },
                onhide() {
                    if (!accepted) {
                        delete frm.doc._qcmc_workflow_reason;
                        frm.selected_workflow_action = null;
                        reject(new Error("Workflow action cancelled"));
                    }
                },
            });
            dialog.show();
        });
    },

    setup(frm) {
        qcmc_logic.material_request.apply_warehouse_access(frm);
    },

    refresh(frm) {
        qcmc_logic.material_request.apply_warehouse_access(frm);
        qcmc_logic.material_request.replace_material_transfer_button(frm);
        if (frm.doc.material_request_type === "Purchase" && frm.doc.workflow_state === "Rejected") {
            frm.set_read_only();
            frm.disable_save();
        }
    },

    material_request_type(frm) {
        qcmc_logic.material_request.apply_warehouse_access(frm);
    },

    set_from_warehouse(frm) {
        qcmc_logic.material_request.apply_warehouse_access(frm);
    },

    set_warehouse(frm) {
        qcmc_logic.material_request.apply_warehouse_access(frm);
    },
});

qcmc_logic.material_request.apply_warehouse_access = function(frm) {
    if (qcmc_logic.warehouse_access && qcmc_logic.warehouse_access.apply) {
        qcmc_logic.warehouse_access.apply(frm);
    }
};

qcmc_logic.material_request.replace_material_transfer_button = function(frm) {
    const float_precision = frappe.defaults.get_default("float_precision");

    if (
        frm.doc.docstatus !== 1 ||
        frm.doc.material_request_type !== "Material Transfer" ||
        flt(frm.doc.per_ordered, float_precision) >= 100
    ) {
        return;
    }

    setTimeout(() => {
        frm.remove_custom_button(__("Material Transfer"), __("Create"));
        frm.remove_custom_button(__("Material Transfer (In Transit)"), __("Create"));

        qcmc_logic.material_request.can_make_warehouse_transfer(frm, can_make => {
            if (!can_make) return;

            frm.add_custom_button(
                __("Warehouse Transfer"),
                () => qcmc_logic.material_request.make_warehouse_transfer(frm),
                __("Create")
            );
        });
    });
};

qcmc_logic.material_request.can_make_warehouse_transfer = function(frm, callback) {
    frappe.call({
        method: "qcmc_logic.utils.can_create_warehouse_transfer_from_material_request",
        args: {
            material_request: frm.doc.name,
            user: frappe.session.user,
        },
        callback(r) {
            callback(!!r.message);
        },
    });
};

qcmc_logic.material_request.make_warehouse_transfer = function(frm) {
    frappe.model.open_mapped_doc({
        method: "qcmc_logic.utils.make_warehouse_transfer_from_material_request",
        frm: frm,
    });
};
