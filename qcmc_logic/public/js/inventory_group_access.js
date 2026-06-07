frappe.provide("qcmc_logic.inventory_group_access");

qcmc_logic.inventory_group_access.doctypes = new Set([
    "Delivery Note",
    "Material Request",
    "Pick List",
    "Purchase Invoice",
    "Purchase Order",
    "Purchase Receipt",
    "Sales Invoice",
    "Stock Entry",
    "Stock Reconciliation",
    "Warehouse Transfer",
]);

qcmc_logic.inventory_group_access.filter = null;

qcmc_logic.inventory_group_access.apply = function(frm) {
    if (
        !frm ||
        !frm.meta ||
        !qcmc_logic.inventory_group_access.doctypes.has(frm.doctype)
    ) {
        return;
    }

    qcmc_logic.inventory_group_access.get_filter(inventory_group_filter => {
        qcmc_logic.inventory_group_access.apply_item_queries(frm, inventory_group_filter);
        setTimeout(() => {
            qcmc_logic.inventory_group_access.apply_item_queries(frm, inventory_group_filter);
        }, 300);
        setTimeout(() => {
            qcmc_logic.inventory_group_access.apply_item_queries(frm, inventory_group_filter);
        }, 1000);
    });
};

qcmc_logic.inventory_group_access.get_filter = function(callback) {
    if (qcmc_logic.inventory_group_access.filter !== null) {
        callback(qcmc_logic.inventory_group_access.filter);
        return;
    }

    frappe.call({
        method: "qcmc_logic.utils.get_inventory_group_item_query_filter",
        args: {
            user: frappe.session.user,
            require_transact: 1,
        },
        callback(r) {
            qcmc_logic.inventory_group_access.filter = r.message || {};
            callback(qcmc_logic.inventory_group_access.filter);
        },
    });
};

qcmc_logic.inventory_group_access.apply_item_queries = function(frm, inventory_group_filter) {
    qcmc_logic.inventory_group_access.apply_child_item_queries(frm, inventory_group_filter);
};

qcmc_logic.inventory_group_access.apply_child_item_queries = function(frm, inventory_group_filter) {
    (frm.meta.fields || []).forEach(table_df => {
        if (table_df.fieldtype !== "Table" || !table_df.options) {
            return;
        }

        const child_meta = frappe.get_meta(table_df.options);
        if (!child_meta) {
            return;
        }

        (child_meta.fields || []).forEach(df => {
            if (df.fieldtype !== "Link" || df.options !== "Item" || !df.fieldname) {
                return;
            }

            frm.set_query(df.fieldname, table_df.fieldname, function(doc) {
                return {
                    query: "erpnext.controllers.queries.item_query",
                    filters: qcmc_logic.inventory_group_access.get_item_filters(
                        frm,
                        doc,
                        df.fieldname,
                        inventory_group_filter
                    ),
                };
            });
        });
    });
};

qcmc_logic.inventory_group_access.get_item_filters = function(
    frm,
    doc,
    fieldname,
    inventory_group_filter
) {
    let filters = {};

    if (frm.doctype === "Material Request") {
        filters = qcmc_logic.inventory_group_access.get_material_request_item_filters(doc);
    } else if ([
        "Pick List",
        "Stock Entry",
        "Stock Reconciliation",
    ].includes(frm.doctype)) {
        filters = { is_stock_item: 1 };
    } else if ([
        "Purchase Invoice",
        "Purchase Order",
        "Purchase Receipt",
    ].includes(frm.doctype)) {
        filters = { is_purchase_item: 1 };
    } else if ([
        "Delivery Note",
        "Sales Invoice",
    ].includes(frm.doctype)) {
        filters = { is_sales_item: 1 };
        if (doc && doc.customer) {
            filters.customer = doc.customer;
        }
    } else if (frm.doctype === "Warehouse Transfer") {
        filters = { is_stock_item: 1 };
    }

    return Object.assign(filters, inventory_group_filter || {});
};

qcmc_logic.inventory_group_access.get_material_request_item_filters = function(doc) {
    if (doc.material_request_type === "Customer Provided") {
        return {
            customer: doc.customer,
        };
    }

    if (
        doc.material_request_type === "Purchase" ||
        doc.material_request_type === "Subcontracting"
    ) {
        return {
            is_purchase_item: 1,
        };
    }

    if (doc.material_request_type === "Manufacture") {
        return {
            include_item_in_manufacturing: 1,
        };
    }

    return {
        is_stock_item: 1,
    };
};

$(document).on("form-refresh", (_event, frm) => {
    qcmc_logic.inventory_group_access.apply(frm);
});

$(document).on("form-load", (_event, frm) => {
    qcmc_logic.inventory_group_access.apply(frm);
});
