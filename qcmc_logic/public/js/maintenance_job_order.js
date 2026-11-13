frappe.ui.form.on("Maintenance Job Order", {
    onload(frm) {
        if (frm.is_new()) {
            if (!frm.doc.document_date) frm.set_value("document_date", frappe.datetime.get_today());
            if (!frm.doc.requested_by) frm.set_value("requested_by", frappe.session.user_fullname);
        }
    },
});

const maintenance_job_roles = {SMB: "Maintenance - SMB", STCLA: "Maintenance - STCLA", MC: "Maintenance - MC"};
const maintenance_job_sections = {
    "GUYONG - PRODUCTION": ["SMB", "Production Encoder - SMB", "Production Foreman - SMB"],
    "STA CLARA - PRODUCTION": ["STCLA", "Production Encoder - STCLA", "Production Foreman - STCLA"],
    "MC - PRODUCTION": ["MC", "Production Foreman - MC", "Production Foreman - MC"],
    "MC - RM": ["MC", "RM - MC", "RM - MC"],
    "GUYONG - RM": ["SMB", "RM - SMB", "RM - SMB"],
    "STA CLARA - RM": ["STCLA", "RM - STCLA", "RM - STCLA"],
};
function maintenance_job_edit_control(frm) {
    const route = maintenance_job_sections[(frm.doc.section || "").trim().toUpperCase()];
    const state = frm.doc.workflow_state || "Draft";
    const role = route && ({Draft: route[1], Submitted: route[2],
        Approved: maintenance_job_roles[route[0]], Active: maintenance_job_roles[route[0]]})[state];
    const can_edit = role && frappe.user_roles.includes(role);
    frm._maintenance_read_only = frm._maintenance_read_only || {};
    frm.meta.fields.forEach((df) => {
        if (!(df.fieldname in frm._maintenance_read_only)) frm._maintenance_read_only[df.fieldname] = df.read_only || 0;
        const allowed = ["work_instruction", "breakdown_code"].includes(df.fieldname);
        const locked = !can_edit || (state === "Approved" && !allowed) || (df.fieldname === "section" && !frm.is_new());
        frm.set_df_property(df.fieldname, "read_only", locked ? 1 : frm._maintenance_read_only[df.fieldname]);
    });
}
frappe.ui.form.on("Maintenance Job Order", {
    refresh: maintenance_job_edit_control,
    section: maintenance_job_edit_control,
    workflow_state: maintenance_job_edit_control,
});
