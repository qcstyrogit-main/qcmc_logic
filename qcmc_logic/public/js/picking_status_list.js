// Keep Picking Status visible as an actual column even with a saved
// ERPNext List View column layout that predates the new Custom Field.
(function() {
    for (const doctype of ["Delivery Note", "Stock Entry"]) {
    const settings = frappe.listview_settings[doctype] || {};
    const previous = settings.onload;
    settings.add_fields = [...new Set([...(settings.add_fields || []), "custom_picking_status"])];
    settings.onload = function(listview) {
        if (typeof previous === "function") previous(listview);
        if (listview.__qcmc_picking_column_installed) return;
        listview.__qcmc_picking_column_installed = true;
        const original = listview.setup_columns.bind(listview);
        listview.setup_columns = function() {
            original();
            const field = frappe.meta.get_docfield(this.doctype, "custom_picking_status");
            if (!field || this.columns.some(column => column.df?.fieldname === field.fieldname)) return;
            const index = Math.min(3, this.columns.length);
            this.columns.splice(index, 0, {type: "Field", df: field});
        };
        listview.setup_columns();
        listview.refresh();
    };
    settings.formatters = settings.formatters || {};
    settings.formatters.custom_picking_status = function(value) {
        if (!value) return '<span class="text-muted">—</span>';
        const color = {
            "Not Started": "grey", "Pending Picking": "orange",
            "Picking Completed": "green", "Submitted": "blue",
            "Cancelled": "red",
        }[value] || "grey";
        return '<span class="indicator-pill ' + color + '">' +
            frappe.utils.escape_html(__(value)) + '</span>';
    };
    frappe.listview_settings[doctype] = settings;
    }
})();
