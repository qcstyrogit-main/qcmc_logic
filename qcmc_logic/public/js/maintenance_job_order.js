frappe.ui.form.on("Maintenance Job Order", {
    setup(frm) {
        frm.set_query("request", () => ({
            query: "qcmc_logic.customs.maintenance_job_order.get_non_fabrication_requests",
        }));
    },

    onload(frm) {
        if (frm.is_new()) {
            if (!frm.doc.document_date) frm.set_value("document_date", frappe.datetime.get_today());
            if (!frm.doc.requested_by) frm.set_value("requested_by", frappe.session.user_fullname);
        }
    },
});
