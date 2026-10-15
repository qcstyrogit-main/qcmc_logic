/* Add personal drag widths to editable child tables without changing records. */
(() => {
    const pending = new Set();
    let framePending = false, stylesAdded = false;

    function viewFor(grid) {
        if (!grid.frm?.doctype || !grid.df?.fieldname || !grid.form_grid?.[0] || !grid.header_row?.row?.[0]) return null;
        if (!grid._qcmcGridResizeView) {
            const stickyDefaults = new Map();
            const view = {doctype: grid.frm.doctype, view_name: "Grid", nativeWidths: []};
            const adapter = view.qcmcResizeAdapter = {
                setting: `qcmc_grid_column_widths_${grid.df.fieldname}`,
                minimum: 60, rootClass: "qcmc-resizable-grid",
                header: () => grid.header_row?.row?.[0],
                groups: () => Array.from(view.$result[0].querySelectorAll(".grid-heading-row .data-row, .grid-body .data-row"))
                    .filter(row => row.closest(".form-grid") === view.$result[0]),
                cells: row => view.columns.map(column => Array.from(row.children).find(cell => cell.getAttribute("data-fieldname") === column.df.fieldname)),
                defaultWidth: index => view.nativeWidths[index],
                onRestore: () => {
                    stickyDefaults.forEach((value, cell) => {
                        if (value) cell.style.setProperty("left", value);
                        else cell.style.removeProperty("left");
                    });
                    stickyDefaults.clear();
                },
                afterApply: () => {
                    if (!view.columns.some(column => column.df.sticky)) return;
                    const offsets = new Map();
                    let offset = 0;
                    let dataStarted = false;
                    const stickyFields = new Set(view.columns.filter(column => column.df.sticky).map(column => column.df.fieldname));
                    Array.from(adapter.header().children).forEach(cell => {
                        const fieldname = cell.getAttribute("data-fieldname");
                        if (fieldname) dataStarted = true;
                        if (!dataStarted) offset += cell.getBoundingClientRect().width;
                        else if (stickyFields.has(fieldname)) {
                            offsets.set(fieldname, offset);
                            offset += cell.getBoundingClientRect().width;
                        }
                    });
                    adapter.groups().forEach(row => adapter.cells(row).forEach((cell, index) => {
                        if (!cell || !view.columns[index].df.sticky) return;
                        if (!stickyDefaults.has(cell)) stickyDefaults.set(cell, cell.style.getPropertyValue("left"));
                        cell.style.setProperty("left", `${offsets.get(view.columns[index].df.fieldname) || 0}px`);
                    }));
                },
            };
            grid._qcmcGridResizeView = view;
        }
        return grid._qcmcGridResizeView;
    }

    function enhanceGrid(grid) {
        const view = viewFor(grid);
        const engine = frappe.qcmc_column_resize;
        if (!view || !engine) return;
        engine.restoreAll(view);
        view.$result = grid.form_grid;
        view.columns = (grid.visible_columns || []).map(([df]) => ({type: "Field", df}));
        const headers = view.qcmcResizeAdapter.cells(view.qcmcResizeAdapter.header());
        // Freeze native measured widths for all data columns before changing one,
        // so body rows, filter inputs and the header remain aligned.
        view.nativeWidths = headers.map(cell => cell?.getBoundingClientRect().width || 0);
        if (typeof ResizeObserver !== "undefined" && grid._qcmcObservedRoot !== grid.form_grid[0]) {
            grid._qcmcResizeObserver?.disconnect();
            let previous = grid.form_grid[0].clientWidth || grid.form_grid[0].getBoundingClientRect().width;
            grid._qcmcResizeObserver = new ResizeObserver(entries => {
                const width = entries[0]?.contentRect.width || 0;
                if (width > 0 && Math.abs(width - previous) > 1) {previous = width; schedule(grid);}
            });
            grid._qcmcResizeObserver.observe(grid.form_grid[0]);
            grid._qcmcObservedRoot = grid.form_grid[0];
        }
        // Observe hidden tabs/sections too, so opening them installs handles.
        if (!view.nativeWidths.length || view.nativeWidths.every(width => !width)) return;
        engine.enhance(view);
    }

    function schedule(grid) {
        if (!grid?.frm || grid._qcmcResizeRenderDepth) return;
        pending.add(grid);
        if (framePending) return;
        framePending = true;
        requestAnimationFrame(() => {
            framePending = false;
            const grids = Array.from(pending); pending.clear();
            grids.forEach(enhanceGrid);
        });
    }

    function installGrid(grid) {
        if (!grid?.frm) return;
        const prototype = Object.getPrototypeOf(grid);
        if (!Object.prototype.hasOwnProperty.call(prototype, "_qcmcGridColumnResizeInstalled")) {
            ["refresh", "render_result_rows"].forEach(method => {
                const original = prototype[method];
                if (typeof original !== "function") return;
                prototype[method] = function (...args) {
                    if (!this._qcmcResizeRenderDepth) frappe.qcmc_column_resize?.restoreAll(this._qcmcGridResizeView);
                    this._qcmcResizeRenderDepth = (this._qcmcResizeRenderDepth || 0) + 1;
                    try {return original.apply(this, args);}
                    finally {this._qcmcResizeRenderDepth--; schedule(this);}
                };
            });
            prototype._qcmcGridColumnResizeInstalled = true;
        }
        schedule(grid);
    }

    function installForm(frm = window.cur_frm) {
        if (!stylesAdded) {
            const style = document.createElement("style");
            style.textContent = `
                .qcmc-resizable-grid{width:100%;max-width:100%;overflow-x:auto!important}
                .qcmc-resizable-grid .grid-heading-row .grid-static-col[data-fieldname]:not(.sticky-grid-col){position:relative}
                .qcmc-resizable-grid .grid-heading-row .grid-static-col[data-fieldname]>.static-area{padding-inline-end:8px}
            `;
            document.head.appendChild(style); stylesAdded = true;
        }
        (frm?.grids || []).forEach(control => installGrid(control.grid));
    }

    $(document).on("app_ready", () => installForm());
    $(document).on("form-refresh", (event, frm) => installForm(frm));
    $(document).on("page-change", () => installForm());
    $(document).on("shown.bs.tab", () => installForm());
    $(document).on("grid-row-render", (event, row) => {if (row?.grid) installGrid(row.grid);});
    window.matchMedia?.("(max-width: 767px)").addEventListener?.("change", () => installForm());
})();
