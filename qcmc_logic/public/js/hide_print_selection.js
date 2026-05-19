$(document).on('app_ready', function() {

    // Override print dialog to skip format selector
    frappe.ui.form.Form.prototype.print_doc = function() {
        let frm = this;
        let print_format = frm.meta.default_print_format || '';

        let url = frappe.urllib.get_full_url(
            '/printview?'
            + 'doctype=' + encodeURIComponent(frm.doc.doctype)
            + '&name=' + encodeURIComponent(frm.doc.name)
            + '&format=' + encodeURIComponent(print_format)
            + '&no_letterhead=0'
            + '&lang=en'
        );

        window.open(url);
    };

});