frappe.ui.form.on('Generate Logs', {
    generate_logs(frm) {
        if (frm.is_new()) {
            frappe.msgprint(__('Please save this document first.'));
            return;
        }

        frappe.call({
            method: 'qcmc_logic.qcmc_logics.doctype.generate_logs.generate_logs.generate_logs',
            args: {
                name: frm.doc.name
            },
            freeze: true,
            callback(r) {
                if (r && r.message && r.message.count !== undefined) {
                    frappe.show_alert({
                        message: __('Generated {0} rows', [r.message.count]),
                        indicator: 'green'
                    });
                }
                frm.reload_doc();
            }
        });
    }
});
