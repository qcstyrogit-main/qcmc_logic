frappe.provide("qcmc_logic.material_request");

frappe.ui.form.on("Material Request", {
    setup(frm) {
        qcmc_logic.material_request.apply_warehouse_access(frm);
    },

    refresh(frm) {
        qcmc_logic.material_request.apply_warehouse_access(frm);
        qcmc_logic.material_request.replace_material_transfer_button(frm);
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
