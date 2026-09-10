frappe.ui.form.on("Maintenance Job Order", {
    onload(frm) {
        if (frm.is_new()) {
            if (!frm.doc.document_date) frm.set_value("document_date", frappe.datetime.get_today());
            if (!frm.doc.requested_by) frm.set_value("requested_by", frappe.session.user_fullname);
        }
    },
});
