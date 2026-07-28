frappe.provide("qcmc_logic.warehouse_access");

qcmc_logic.warehouse_access.skip_doctypes = new Set([
    "Allowed Warehouse",
    "BOM",
    "BOM Creator",
    "BOM Explosion Item",
    "BOM Item",
    "BOM Operation",
    "Bin",
    "Company",
    "Cost Center Warehouse Mapping",
    "Delivery Schedule Item",
    "Error Log",
    "Item Default",
    "Item Reorder",
    "Job Card",
    "Job Card Item",
    "Master Production Schedule",
    "Master Production Schedule Item",
    "Material Request Plan Item",
    "Packed Item",
    "Plant Floor",
    "Pricing Rule",
    "Production Employee Advance Schedule",
    "Production Plan",
    "Production Plan Item",
    "Production Plan Material Request Warehouse",
    "Production Plan Sub Assembly Item",
    "Production Plantilla",
    "Promotional Scheme Price Discount",
    "Promotional Scheme Product Discount",
    "Putaway Rule",
    "Quick Stock Balance",
    "Quotation Item",
    "Repost Item Valuation",
    "Request for Quotation Item",
    "Role Profile Warehouse Access",
    "Sales Forecast",
    "Sales Forecast Item",
    "Serial and Batch Bundle",
    "Serial and Batch Entry",
    "Serial No",
    "Stock Closing Balance",
    "Stock Settings",
    "Stock Ledger Entry",
    "Stock Reservation Entry",
    "Supplier Quotation Item",
    "User Permission",
    "Warehouse",
    "Warehouse Access",
    "Warehouse Transfer",
    "Work Order",
    "Workstation",
]);

qcmc_logic.warehouse_access.transaction_doctypes = new Set([
    "Delivery Note",
    "Material Request",
    "Pick List",
    "POS Invoice",
    "Purchase Invoice",
    "Purchase Order",
    "Purchase Receipt",
    "Sales Invoice",
    "Sales Order",
    "Stock Entry",
    "Stock Reconciliation",
    "Subcontracting Order",
    "Subcontracting Receipt",
    "Warehouse Transfer",
]);

qcmc_logic.warehouse_access.enabled = null;

qcmc_logic.warehouse_access.is_administrator = function() {
    return frappe.session && frappe.session.user === "Administrator";
};

qcmc_logic.warehouse_access.is_enabled = function(callback) {
    if (qcmc_logic.warehouse_access.is_administrator()) {
        callback(false);
        return;
    }

    if (qcmc_logic.warehouse_access.enabled !== null) {
        callback(qcmc_logic.warehouse_access.enabled);
        return;
    }

    frappe.call({
        method: "qcmc_logic.utils.is_global_warehouse_access_enabled",
        callback(r) {
            qcmc_logic.warehouse_access.enabled = !!r.message;
            callback(qcmc_logic.warehouse_access.enabled);
        },
    });
};

qcmc_logic.warehouse_access.get_query = function(require_transact) {
    return {
        query: "qcmc_logic.utils.get_allowed_warehouse_query",
        filters: {
            user: frappe.session.user,
            require_transact: require_transact ? 1 : 0,
        },
    };
};

qcmc_logic.warehouse_access.get_material_request_source_query = function(frm, row) {
    return {
        query: "qcmc_logic.utils.get_material_request_source_warehouse_query",
        filters: {
            target_warehouse: (row && row.warehouse) || (frm && frm.doc ? frm.doc.set_warehouse : ""),
        },
    };
};

qcmc_logic.warehouse_access.get_material_request_target_query = function(frm) {
    return {
        query: "qcmc_logic.utils.get_material_request_target_warehouse_query",
        filters: {
            user: frappe.session.user,
        },
    };
};

qcmc_logic.warehouse_access.get_stock_entry_source_query = function(frm, row) {
    return {
        query: "qcmc_logic.utils.get_stock_entry_source_warehouse_query",
        filters: {
            user: frappe.session.user,
            purpose: frm && frm.doc ? frm.doc.purpose : "",
            target_warehouse: (row && row.t_warehouse) || (frm && frm.doc ? frm.doc.to_warehouse : ""),
        },
    };
};

qcmc_logic.warehouse_access.get_stock_entry_target_query = function(frm, row) {
    return {
        query: "qcmc_logic.utils.get_stock_entry_target_warehouse_query",
        filters: {
            user: frappe.session.user,
            purpose: frm && frm.doc ? frm.doc.purpose : "",
            source_warehouse: (row && row.s_warehouse) || (frm && frm.doc ? frm.doc.from_warehouse : ""),
        },
    };
};

qcmc_logic.warehouse_access.is_source_field = function(fieldname) {
    return [
        "from_warehouse",
        "set_from_warehouse",
        "source_warehouse",
        "s_warehouse",
    ].includes(fieldname);
};

qcmc_logic.warehouse_access.is_target_field = function(fieldname) {
    return [
        "to_warehouse",
        "set_warehouse",
        "target_warehouse",
        "t_warehouse",
        "warehouse",
    ].includes(fieldname);
};

qcmc_logic.warehouse_access.stock_entry_source_purposes = new Set([
    "Material Issue",
    "Material Transfer",
    "Send to Subcontractor",
    "Material Transfer for Manufacture",
    "Material Consumption for Manufacture",
    "Return Raw Material to Customer",
    "Subcontracting Delivery",
    "Manufacture",
    "Repack",
    "Disassemble",
]);

qcmc_logic.warehouse_access.stock_entry_target_purposes = new Set([
    "Material Receipt",
    "Material Transfer",
    "Send to Subcontractor",
    "Material Transfer for Manufacture",
    "Receive from Customer",
    "Subcontracting Return",
    "Manufacture",
    "Repack",
    "Disassemble",
]);

qcmc_logic.warehouse_access.is_material_transfer_request = function(frm) {
    return frm && frm.doctype === "Material Request" && frm.doc.material_request_type === "Material Transfer";
};

qcmc_logic.warehouse_access.is_material_request_source_field = function(frm, fieldname) {
    return qcmc_logic.warehouse_access.is_material_transfer_request(frm) && [
        "from_warehouse",
        "set_from_warehouse",
    ].includes(fieldname);
};

qcmc_logic.warehouse_access.is_material_request_target_field = function(frm, fieldname) {
    return qcmc_logic.warehouse_access.is_material_transfer_request(frm) && [
        "warehouse",
        "set_warehouse",
    ].includes(fieldname);
};

qcmc_logic.warehouse_access.requires_transact = function(frm, fieldname) {
    if (qcmc_logic.warehouse_access.is_material_request_source_field(frm, fieldname)) {
        return false;
    }

    if (frm && frm.doctype === "Stock Entry") {
        return qcmc_logic.warehouse_access.stock_entry_requires_transact(frm, fieldname);
    }

    if (frm && frm.doctype === "Material Request") {
        return qcmc_logic.warehouse_access.is_material_request_target_field(frm, fieldname);
    }

    if (frm && ["Delivery Note", "Sales Invoice", "Pick List"].includes(frm.doctype)) {
        return fieldname === "warehouse";
    }

    if (
        frm &&
        ["Purchase Invoice", "Purchase Order", "Purchase Receipt"].includes(frm.doctype)
    ) {
        return ["set_warehouse", "warehouse"].includes(fieldname);
    }

    if (frm && frm.doctype === "Stock Reconciliation") {
        return fieldname === "warehouse";
    }

    return (
        qcmc_logic.warehouse_access.is_source_field(fieldname) ||
        qcmc_logic.warehouse_access.is_target_field(fieldname)
    );
};

qcmc_logic.warehouse_access.stock_entry_requires_transact = function(frm, fieldname) {
    const purpose = frm.doc ? frm.doc.purpose : "";

    if (["from_warehouse", "s_warehouse"].includes(fieldname)) {
        return qcmc_logic.warehouse_access.stock_entry_source_purposes.has(purpose);
    }

    if (["to_warehouse", "t_warehouse"].includes(fieldname)) {
        return qcmc_logic.warehouse_access.stock_entry_target_purposes.has(purpose);
    }

    return false;
};

qcmc_logic.warehouse_access.apply = function(frm) {
    if (
        qcmc_logic.warehouse_access.is_administrator() ||
        !frm ||
        !frm.meta ||
        qcmc_logic.warehouse_access.skip_doctypes.has(frm.doctype) ||
        !qcmc_logic.warehouse_access.transaction_doctypes.has(frm.doctype)
    ) {
        return;
    }

    qcmc_logic.warehouse_access.apply_top_level_queries(frm);
    qcmc_logic.warehouse_access.apply_child_table_queries(frm);
    qcmc_logic.warehouse_access.apply_single_warehouse_defaults(frm);
};

qcmc_logic.warehouse_access.apply_top_level_queries = function(frm) {
    (frm.meta.fields || []).forEach(df => {
        if (df.fieldtype !== "Link" || df.options !== "Warehouse" || !df.fieldname) {
            return;
        }

        frm.set_query(df.fieldname, () => {
            if (qcmc_logic.warehouse_access.is_material_request_source_field(frm, df.fieldname)) {
                return qcmc_logic.warehouse_access.get_material_request_source_query(frm);
            }

            if (qcmc_logic.warehouse_access.is_material_request_target_field(frm, df.fieldname)) {
                return qcmc_logic.warehouse_access.get_material_request_target_query(frm);
            }

            if (frm.doctype === "Stock Entry" && df.fieldname === "from_warehouse") {
                return qcmc_logic.warehouse_access.get_stock_entry_source_query(frm);
            }

            if (frm.doctype === "Stock Entry" && df.fieldname === "to_warehouse") {
                return qcmc_logic.warehouse_access.get_stock_entry_target_query(frm);
            }

            return qcmc_logic.warehouse_access.get_query(
                qcmc_logic.warehouse_access.requires_transact(frm, df.fieldname)
            );
        });
    });
};

qcmc_logic.warehouse_access.apply_child_table_queries = function(frm) {
    (frm.meta.fields || []).forEach(table_df => {
        if (table_df.fieldtype !== "Table" || !table_df.options) {
            return;
        }

        const child_meta = frappe.get_meta(table_df.options);
        if (!child_meta) {
            return;
        }

        (child_meta.fields || []).forEach(df => {
            if (df.fieldtype !== "Link" || df.options !== "Warehouse" || !df.fieldname) {
                return;
            }

            frm.set_query(df.fieldname, table_df.fieldname, (_doc, cdt, cdn) => {
                const row = locals[cdt] && locals[cdt][cdn];

                if (qcmc_logic.warehouse_access.is_material_request_source_field(frm, df.fieldname)) {
                    return qcmc_logic.warehouse_access.get_material_request_source_query(frm, row);
                }

                if (qcmc_logic.warehouse_access.is_material_request_target_field(frm, df.fieldname)) {
                    return qcmc_logic.warehouse_access.get_material_request_target_query(frm);
                }

                if (frm.doctype === "Stock Entry" && df.fieldname === "s_warehouse") {
                    return qcmc_logic.warehouse_access.get_stock_entry_source_query(frm, row);
                }

                if (frm.doctype === "Stock Entry" && df.fieldname === "t_warehouse") {
                    return qcmc_logic.warehouse_access.get_stock_entry_target_query(frm, row);
                }

                return qcmc_logic.warehouse_access.get_query(
                    qcmc_logic.warehouse_access.requires_transact(frm, df.fieldname)
                );
            });
        });
    });
};

qcmc_logic.warehouse_access.apply_single_warehouse_defaults = function(frm) {
    if ((frm.doc && frm.doc.docstatus !== 0) || !frm.is_new()) {
        return;
    }

    qcmc_logic.warehouse_access.apply_default_company(frm);

    frappe.call({
        method: "qcmc_logic.utils.get_default_warehouse_for_user",
        args: {
            user: frappe.session.user,
            require_transact: 1,
        },
        callback(r) {
            const default_warehouse = r.message;
            if (!default_warehouse) {
                return;
            }

            (frm.meta.fields || []).forEach(df => {
                if (
                    df.fieldtype === "Link" &&
                    df.options === "Warehouse" &&
                    df.fieldname &&
                    !frm.doc[df.fieldname] &&
                    qcmc_logic.warehouse_access.should_default_warehouse(frm, df.fieldname)
                ) {
                    frm.set_value(df.fieldname, default_warehouse);
                }
            });
        },
    });
};

qcmc_logic.warehouse_access.apply_default_company = function(frm) {
    if (!frm || !frm.doc || frm.doc.company || !frm.fields_dict.company) {
        return;
    }

    frappe.call({
        method: "qcmc_logic.utils.get_default_company_from_default_warehouse",
        args: {
            user: frappe.session.user,
            require_transact: 1,
        },
        callback(r) {
            if (r.message && !frm.doc.company) {
                frm.set_value("company", r.message);
            }
        },
    });
};

qcmc_logic.warehouse_access.should_default_warehouse = function(frm, fieldname) {
    if (!frm || !frm.doc) {
        return false;
    }

    if (frm.doctype === "Stock Entry") {
        if (frm.doc.purpose === "Material Issue") {
            return fieldname === "from_warehouse";
        }

        if (frm.doc.purpose === "Material Receipt") {
            return fieldname === "to_warehouse";
        }

        return false;
    }

    if (frm.doctype === "Material Request") {
        return fieldname === "set_warehouse";
    }

    if (["Purchase Order", "Purchase Receipt"].includes(frm.doctype)) {
        return fieldname === "set_warehouse";
    }

    return false;
};

qcmc_logic.warehouse_access.clear_stock_entry_warehouses = function(frm) {
    if (!frm || !frm.doc || frm.doctype !== "Stock Entry" || frm.doc.docstatus !== 0) {
        return;
    }

    ["from_warehouse", "to_warehouse"].forEach(fieldname => {
        if (frm.doc[fieldname]) {
            frm.set_value(fieldname, "");
        }
    });

    (frm.doc.items || []).forEach(row => {
        ["s_warehouse", "t_warehouse"].forEach(fieldname => {
            if (row[fieldname]) {
                frappe.model.set_value(row.doctype, row.name, fieldname, "");
            }
        });
    });
};

qcmc_logic.warehouse_access.handle_stock_entry_type_change = function(frm) {
    qcmc_logic.warehouse_access.is_enabled(enabled => {
        if (!enabled) {
            return;
        }

        qcmc_logic.warehouse_access.clear_stock_entry_warehouses(frm);

        setTimeout(() => {
            qcmc_logic.warehouse_access.apply(frm);
        }, 300);
    });
};

$(document).on("form-refresh", (_event, frm) => {
    qcmc_logic.warehouse_access.is_enabled(enabled => {
        if (enabled) {
            qcmc_logic.warehouse_access.apply(frm);
        }
    });
});

frappe.ui.form.on("Stock Entry", {
    stock_entry_type(frm) {
        qcmc_logic.warehouse_access.handle_stock_entry_type_change(frm);
    },

    purpose(frm) {
        qcmc_logic.warehouse_access.is_enabled(enabled => {
            if (enabled) {
                qcmc_logic.warehouse_access.apply(frm);
            }
        });
    },
});
