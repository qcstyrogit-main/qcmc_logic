/* Bulk WRR items and the linked allocation plan saved by the server. */
var qcmc_wrr_allocation = {
    configure(frm) {
        const bulk = Boolean(frm.doc.custom_wrr_allocation_enabled || (!frm.doc.is_return && frm.doc.docstatus === 0));
        const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
        if (grid) {
            ['location', 'from_location', 'rejected_location', 'putaway_rule', 'inventory_dimension', 'inventory_dimension_col_break'].forEach((field) => {
                if (grid.docfields && !grid.docfields.some(df => df.fieldname === field)) return;
                grid.update_docfield_property(field, 'hidden', bulk ? 1 : 0);
                if (['location', 'from_location', 'rejected_location'].includes(field)) {
                    grid.update_docfield_property(field, 'in_list_view', bulk ? 0 : 1);
                }
            });
            grid.refresh();
        }
        frm.set_df_property('location', 'hidden', bulk ? 1 : 0);
        frm.set_df_property('apply_putaway_rule', 'read_only', 0);
        frm.set_df_property('custom_warehouse_allocation_section', 'hidden',
            frm.doc.__islocal || !frm.doc.custom_wrr_allocation_enabled ? 1 : 0);
    },
    load(frm) {
        if (frm.doc.__islocal || !frm.doc.custom_wrr_allocation_enabled) return;
        frm.set_df_property('custom_warehouse_allocation', 'description',
            !frm.doc.is_return && !frm.doc.apply_putaway_rule
                ? __('Apply Putaway Rule is unchecked. Automatic allocation is disabled.') : '');
        frm.refresh_field('custom_warehouse_allocation');
    },
};

frappe.ui.form.on('Purchase Receipt', {
    apply_putaway_rule(frm) {
        wrr_allocation_dirty(frm);
    },
    refresh(frm) {
        qcmc_wrr_allocation.configure(frm);
        qcmc_wrr_allocation.load(frm);
    },
    after_save(frm) {
        qcmc_wrr_allocation.configure(frm);
        qcmc_wrr_allocation.load(frm);
    },
});
frappe.ui.form.on('Purchase Receipt Item', {
    item_code: wrr_allocation_dirty, qty: wrr_allocation_dirty,
    warehouse: wrr_allocation_dirty, conversion_factor: wrr_allocation_dirty,
    items_remove: wrr_allocation_dirty,
});
function wrr_allocation_dirty(frm) {
    if (frm.doc.custom_wrr_allocation_enabled && !frm.doc.__islocal && frm.doc.docstatus === 0) {
        frm.set_df_property('custom_warehouse_allocation', 'description',
            __('Save WRR to refresh the Storage Allocation for your changes.'));
    }
}
