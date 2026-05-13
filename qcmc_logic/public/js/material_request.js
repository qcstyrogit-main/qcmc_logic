frappe.provide("qcmc_logic.material_request");

frappe.ui.form.on("Material Request", {
    refresh(frm) {
        qcmc_logic.material_request.replace_material_transfer_button(frm);
    },
});

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

        frm.add_custom_button(
            __("Warehouse Transfer"),
            () => qcmc_logic.material_request.make_warehouse_transfer(frm),
            __("Create")
        );
    });
};

qcmc_logic.material_request.make_warehouse_transfer = function(frm) {
    frappe.model.open_mapped_doc({
        method: "qcmc_logic.utils.make_warehouse_transfer_from_material_request",
        frm: frm,
    });
};
