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

    if (qcmc_logic.warehouse_access.is_material_request_target_field(frm, fieldname)) {
        return true;
    }

    return qcmc_logic.warehouse_access.is_source_field(fieldname);
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

            if (qcmc_logic.warehouse_access.is_material_transfer_request(frm)) {
                if (!frm.doc.set_warehouse) {
                    frm.set_value("set_warehouse", default_warehouse);
                }
                return;
            }

            (frm.meta.fields || []).forEach(df => {
                if (qcmc_logic.warehouse_access.is_material_request_source_field(frm, df.fieldname)) {
                    return;
                }

                if (
                    df.fieldtype === "Link" &&
                    df.options === "Warehouse" &&
                    df.fieldname &&
                    !frm.doc[df.fieldname] &&
                    qcmc_logic.warehouse_access.requires_transact(frm, df.fieldname)
                ) {
                    frm.set_value(df.fieldname, default_warehouse);
                }
            });
        },
    });
};

$(document).on("form-refresh", (_event, frm) => {
    qcmc_logic.warehouse_access.is_enabled(enabled => {
        if (enabled) {
            qcmc_logic.warehouse_access.apply(frm);
        }
    });
});
