/* Hide Location from Purchase Invoice Items (Accounts Payable Voucher) only.
 * The dimension, its saved values and all other DocTypes are retained.
 * Install through app_include_js so it runs even if DocType JS is cached.
 */
(() => {
    if (window.qcmc_purchase_invoice_location_hide_installed) return;
    window.qcmc_purchase_invoice_location_hide_installed = true;

    // custom_location is the branch Location; location is the stock dimension.
    const hiddenFields = new Set(["location", "custom_location"]);

    function apply(frm) {
        if (!frm || frm.doctype !== "Purchase Invoice") return;
        const grid = frm.fields_dict?.items?.grid;
        if (!grid || grid.doctype !== "Purchase Invoice Item") return;

        // Explicitly edit the grid's actual field definitions (not only rows).
        const hideField = (df) => {
            if (!df || !hiddenFields.has(df.fieldname)) return;
            df.hidden = 1;
            df.reqd = 0;
            df.in_list_view = 0;
        };
        (grid.docfields || []).forEach(hideField);
        hiddenFields.forEach(fieldname => hideField(grid.fields_map?.[fieldname]));
        (grid.user_defined_columns || []).forEach(hideField);
        for (const row of grid.grid_rows || []) {
            (row.docfields || []).forEach(hideField);
        }

        if (!grid._qcmcLocationFilterInstalled) {
            grid._qcmcLocationFilterInstalled = true;
            const original = grid.setup_visible_columns;
            grid.setup_visible_columns = function (...args) {
                const result = original.apply(this, args);
                this.visible_columns = (this.visible_columns || []).filter(
                    ([df]) => !hiddenFields.has(df.fieldname)
                );
                return result;
            };
            grid.visible_columns = [];
            grid.refresh();
        } else if (grid.visible_columns?.some(([df]) => hiddenFields.has(df.fieldname))) {
            grid.visible_columns = [];
            grid.refresh();
        }

        // The expanded row is a distinct GridRowForm. Keep it in sync too.
        const open = frm.cur_grid;
        if (open?.grid === grid) {
            hiddenFields.forEach(fieldname => {
                open.toggle_reqd?.(fieldname, false);
                open.toggle_display?.(fieldname, false);
            });
        }
    }

    function applyCurrent() {
        apply(window.cur_frm);
    }

    $(document).on("form-refresh", (_event, frm) => apply(frm || window.cur_frm));
    $(document).on("grid-row-render", (_event, row) => {
        const frm = window.cur_frm;
        if (frm?.doctype === "Purchase Invoice" &&
            row?.grid === frm.fields_dict?.items?.grid) {
            (row.docfields || []).filter(df => hiddenFields.has(df.fieldname))
                .forEach(df => { df.hidden = 1; df.reqd = 0; df.in_list_view = 0; });
        }
    });
    $(document).on("page-change", () => requestAnimationFrame(applyCurrent));
    $(document).on("app_ready", applyCurrent);
    applyCurrent();
})();
