frappe.provide("qcmc_logic.warehouse_access");

qcmc_logic.warehouse_access.skip_doctypes = new Set([
    "Stock Settings",
    "Warehouse Access",
    "Warehouse Transfer",
]);

qcmc_logic.warehouse_access.enabled = null;

qcmc_logic.warehouse_access.is_enabled = function(callback) {
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

qcmc_logic.warehouse_access.get_material_request_source_query = function(frm) {
    return {
        query: "qcmc_logic.utils.get_material_request_source_warehouse_query",
        filters: {
            user: frappe.session.user,
            target_warehouse: frm && frm.doc ? frm.doc.set_warehouse : "",
        },
    };
};

qcmc_logic.warehouse_access.get_material_request_target_query = function(frm) {
    return {
        query: "qcmc_logic.utils.get_material_request_target_warehouse_query",
        filters: {
            user: frappe.session.user,
            source_warehouse: frm && frm.doc ? frm.doc.set_from_warehouse : "",
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
    if (!frm || !frm.meta || qcmc_logic.warehouse_access.skip_doctypes.has(frm.doctype)) {
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

            frm.set_query(df.fieldname, table_df.fieldname, () => {
                if (qcmc_logic.warehouse_access.is_material_request_source_field(frm, df.fieldname)) {
                    return qcmc_logic.warehouse_access.get_material_request_source_query(frm);
                }

                if (qcmc_logic.warehouse_access.is_material_request_target_field(frm, df.fieldname)) {
                    return qcmc_logic.warehouse_access.get_material_request_target_query(frm);
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
