frappe.provide("qcmc_logic.machine_shop_job_request_output");

frappe.ui.form.on("Machine Shop Job Request", {
    setup(frm) {
        frm.set_query("item_code", () => ({
            query: "qcmc_logic.customs.machine_shop_job_request.get_msjr_item_query",
        }));
    },

    refresh(frm) {
        qcmc_logic.machine_shop_job_request_output.apply_field_rules(frm, false);
        qcmc_logic.machine_shop_job_request_output.apply_quantity_produced_permission(frm);
        qcmc_logic.machine_shop_job_request_output.render_repairs_projects(frm);
    },

    request(frm) {
        qcmc_logic.machine_shop_job_request_output.apply_field_rules(frm, true);
    },

    not_in_master_file(frm) {
        qcmc_logic.machine_shop_job_request_output.apply_field_rules(frm, true);
    },

    validate(frm) {
        return qcmc_logic.machine_shop_job_request_output.validate_fabrication_fields(frm);
    },

});

qcmc_logic.machine_shop_job_request_output.render_repairs_projects = async function(frm) {
    const field = frm.fields_dict.repairs_projects_html;
    if (!field) return;
    const wrapper = field.$wrapper;
    const escape = value => frappe.utils.escape_html(String(value ?? ""));
    if (frm.is_new()) {
        wrapper.html(`<p class="text-muted">${__("Save this request to monitor its repairs and projects.")}</p>`);
        return;
    }

    const request_id = (frm._repairs_projects_request_id || 0) + 1;
    frm._repairs_projects_request_id = request_id;
    const name = frm.doc.name;
    wrapper.html(`<p class="text-muted">${__("Loading repairs and projects…")}</p>`);
    let content;
    try {
        const response = await frappe.call({
            method: "qcmc_logic.customs.machine_shop_job_request.get_linked_repairs_projects",
            args: { msjr_no: name },
        });
        const rows = response.message || [];
        const date = value => value ? escape(frappe.datetime.str_to_user(value)) : "—";
        const headings = ["Repair / Project", "Project No", "Workflow State", "Status", "Completed (%)", "Start Date", "Commitment Date"];
        content = rows.length ? `
            <p class="text-muted">${__("Linked records: {0}", [rows.length])}</p>
            <div class="table-responsive"><table class="table table-bordered">
                <thead><tr>${headings.map(label => `<th>${__(label)}</th>`).join("")}</tr></thead>
                <tbody>${rows.map(row => `<tr>
                    <td>${frappe.utils.get_form_link("Machine Shop Repairs and Project", row.name, true, escape(row.name))}</td>
                    <td>${escape(row.project_no || "—")}</td>
                    <td>${escape(row.docstatus === 2 ? __("Cancelled") : row.workflow_state || "—")}</td>
                    <td>${escape(row.status || "—")}</td>
                    <td>${escape(row.percentage_completed ?? "—")}</td>
                    <td>${date(row.start_date)}</td>
                    <td>${date(row.commitment_date)}</td>
                </tr>`).join("")}</tbody>
            </table></div>` : `<p class="text-muted">${__("No linked repairs or projects are available to view.")}</p>`;
    } catch (error) {
        content = `<p class="text-muted">${__("Unable to load repairs and projects. Please try refreshing.")}</p>`;
    }
    if (frm.doc.name !== name || frm._repairs_projects_request_id !== request_id) return;
    wrapper.html(`<div class="mb-3"><button type="button" class="btn btn-default btn-sm" data-refresh-projects>${__("Refresh")}</button></div>${content}`);
    wrapper.find("[data-refresh-projects]").on("click", () => {
        qcmc_logic.machine_shop_job_request_output.render_repairs_projects(frm);
    });
};

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
        const item_types = ["FABRICATION - ITEM", "FABRICATION - MACHINE PART"];
        const is_item_fabrication = item_types.includes(request_type);
        const is_mould_fabrication = request_type === "FABRICATION - MOULD";
        const is_legacy_parts = request_type === "PARTS FABRICATION";
        const missing_master = !!frm.doc.not_in_master_file;
        const use_item = !missing_master;
        const is_fabrication = is_item_fabrication || is_mould_fabrication;

        frm.toggle_display("item_code", use_item);
        frm.toggle_display("item_name", use_item);
        frm.toggle_display("quantity_request", is_item_fabrication);
        frm.toggle_display("quantity_produced", is_fabrication || is_legacy_parts);
        frm.set_df_property("item_code", "read_only", !use_item);
        frm.set_df_property("item_code", "reqd", false);
        frm.set_df_property("quantity_request", "reqd", is_item_fabrication);

        if (!is_fabrication && !is_legacy_parts && flt(frm.doc.quantity_produced)) {
            frm.set_value("quantity_produced", 0);
        }
    });
};

qcmc_logic.machine_shop_job_request_output.apply_quantity_produced_permission = function(frm) {
    const allowed = (frappe.user_roles || []).some(role => [
        "Machine Shop User",
        "Machine Shop Foreman",
    ].includes(role));
    frm.set_df_property("quantity_produced", "read_only", allowed ? 0 : 1);
};

qcmc_logic.machine_shop_job_request_output.validate_fabrication_fields = function(frm) {
    return qcmc_logic.machine_shop_job_request_output.get_request_type(frm).then(request_type => {
        const item_types = ["FABRICATION - ITEM", "FABRICATION - MACHINE PART"];
        const is_item = item_types.includes(request_type);
        const is_mould = request_type === "FABRICATION - MOULD";

        if (is_item && flt(frm.doc.quantity_request) <= 0) {
            frappe.throw(__("Quantity Request is required and must be greater than zero."));
        }
        if (frm.doc.workflow_state !== "Completed") return;

        if (is_item && !frm.doc.item_code) {
            frappe.throw(__("Item Code is required before completing this fabrication request."));
        }
        if (is_mould && !frm.doc.item_code) {
            frappe.throw(__("Item Code is required before completing this fabrication request."));
        }
        if ((is_item || is_mould) && flt(frm.doc.quantity_produced) <= 0) {
            frappe.throw(__("Quantity Produced must be greater than zero before completing this fabrication request."));
        }
    });
};
