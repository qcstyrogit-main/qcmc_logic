frappe.provide("qcmc_logic.machine_shop_job_request_output");

frappe.ui.form.on("Machine Shop Job Request", {
    setup(frm) {
        frm.set_query("item_code", () => ({
            query: "qcmc_logic.utils.get_allowed_item_query",
            filters: {
                user: frappe.session.user,
                require_transact: 1,
                inventory_group: "CMMS",
            },
        }));
    },

    refresh(frm) {
        qcmc_logic.machine_shop_job_request_output.apply_field_rules(frm, false);
        qcmc_logic.machine_shop_job_request_output.add_stock_entry_button(frm);
    },

    request(frm) {
        qcmc_logic.machine_shop_job_request_output.apply_field_rules(frm, true);
    },

    not_in_master_file(frm) {
        qcmc_logic.machine_shop_job_request_output.apply_field_rules(frm, true);
    },
});

qcmc_logic.machine_shop_job_request_output.get_request_type = function(frm) {
    if (!frm.doc.request) return Promise.resolve("");

    return frappe.db.get_value(
        "Machine Shop Request Code",
        frm.doc.request,
        "description"
    ).then(r => String((r.message && r.message.description) || "").trim().toUpperCase());
};

qcmc_logic.machine_shop_job_request_output.apply_field_rules = function(frm, clear_inactive) {
    return qcmc_logic.machine_shop_job_request_output.get_request_type(frm).then(request_type => {
        const is_parts = request_type === "PARTS FABRICATION";
        const missing_master = !!frm.doc.not_in_master_file;
        const use_item = is_parts && !missing_master;
        const use_asset = !is_parts && !missing_master;

        frm.toggle_display("item_code", use_item);
        frm.toggle_display("asset", use_asset);
        frm.toggle_display("asset_name", use_asset);
        frm.set_df_property("item_code", "read_only", !use_item);
        frm.set_df_property("asset", "read_only", !use_asset);
        frm.set_df_property("item_code", "reqd", false);
        frm.set_df_property("asset", "reqd", false);

        if (clear_inactive && !use_item && frm.doc.item_code) {
            frm.set_value("item_code", "");
        }
        if (clear_inactive && !use_asset && frm.doc.asset) {
            frm.set_value("asset", "");
        }
    });
};

qcmc_logic.machine_shop_job_request_output.add_stock_entry_button = function(frm) {
    if (
        frm.is_new() ||
        frm.doc.workflow_state !== "Completed" ||
        !frappe.model.can_create("Stock Entry")
    ) {
        return;
    }

    frm.add_custom_button(__("Output Stock Entry"), () => {
        frappe.model.open_mapped_doc({
            method: "qcmc_logic.utils.make_completed_output_stock_entry",
            frm,
        });
    }, __("Create"));
};
