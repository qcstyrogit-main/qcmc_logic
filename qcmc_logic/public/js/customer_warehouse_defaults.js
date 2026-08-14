frappe.provide("qcmc_logic.customer_warehouse_defaults");

frappe.ui.form.on("Customer", {
    setup(frm) {
        if (!frm.fields_dict.custom_company_warehouse_defaults) {
            return;
        }

        frm.set_query(
            "warehouse",
            "custom_company_warehouse_defaults",
            (_doc, cdt, cdn) => {
                const row = locals[cdt] && locals[cdt][cdn];
                return {
                    filters: {
                        is_group: 0,
                        company: row && row.company ? row.company : "",
                    },
                };
            }
        );
    },
});

frappe.ui.form.on("Customer Company Warehouse Default", {
    company(frm, cdt, cdn) {
        const row = locals[cdt] && locals[cdt][cdn];
        if (row && row.warehouse) {
            frappe.model.set_value(cdt, cdn, "warehouse", "");
        }
    },
});

qcmc_logic.customer_warehouse_defaults.doctypes = [
    "Delivery Note",
    "POS Invoice",
    "Sales Invoice",
    "Sales Order",
];

qcmc_logic.customer_warehouse_defaults.doctypes.forEach(doctype => {
    frappe.ui.form.on(doctype, {
        onload(frm) {
            qcmc_logic.customer_warehouse_defaults.apply(frm);
        },
        refresh(frm) {
            qcmc_logic.customer_warehouse_defaults.apply(frm);
        },
        customer(frm) {
            qcmc_logic.customer_warehouse_defaults.apply(frm);
        },
        company(frm) {
            qcmc_logic.customer_warehouse_defaults.apply(frm);
        },
        items_add(frm, cdt, cdn) {
            qcmc_logic.customer_warehouse_defaults.apply_to_row(frm, cdt, cdn);
        },
    });
});

qcmc_logic.customer_warehouse_defaults.apply = function(frm) {
    if (!frm || !frm.doc || frm.doc.docstatus !== 0) {
        return;
    }

    if (!frm.doc.customer || !frm.doc.company) {
        return;
    }

    if (frm.doc.set_warehouse && frm.doc.set_warehouse !== frm.__customer_default_warehouse) {
        qcmc_logic.customer_warehouse_defaults.apply_to_blank_item_warehouses(
            frm,
            frm.doc.set_warehouse
        );
        return;
    }

    const request_key = [frm.doctype, frm.doc.name, frm.doc.customer, frm.doc.company].join("|");
    frm.__customer_warehouse_default_request = request_key;

    frappe.call({
        method: "qcmc_logic.customs.customer_warehouse_defaults.get_customer_company_default_warehouse",
        args: {
            customer: frm.doc.customer,
            company: frm.doc.company,
        },
        callback(r) {
            if (frm.__customer_warehouse_default_request !== request_key) {
                return;
            }

            const warehouse = r.message;
            if (!warehouse) {
                return;
            }

            qcmc_logic.customer_warehouse_defaults.apply_warehouse(frm, warehouse);
        },
    });
};

qcmc_logic.customer_warehouse_defaults.apply_warehouse = function(frm, warehouse) {
    const previous_default = frm.__customer_default_warehouse;

    if (
        frm.fields_dict.set_warehouse &&
        (!frm.doc.set_warehouse || frm.doc.set_warehouse === previous_default)
    ) {
        frm.set_value("set_warehouse", warehouse);
        frm.__customer_default_warehouse = warehouse;
    }

    qcmc_logic.customer_warehouse_defaults.apply_to_blank_item_warehouses(
        frm,
        warehouse,
        previous_default
    );
};

qcmc_logic.customer_warehouse_defaults.apply_to_blank_item_warehouses = function(
    frm,
    warehouse,
    previous_default
) {
    if (!warehouse || !frm.fields_dict.items || !Array.isArray(frm.doc.items)) {
        return;
    }

    frm.doc.items.forEach(row => {
        qcmc_logic.customer_warehouse_defaults.set_row_warehouse(
            row,
            warehouse,
            previous_default
        );
    });
};

qcmc_logic.customer_warehouse_defaults.apply_to_row = function(frm, cdt, cdn) {
    const warehouse = frm && (frm.doc.set_warehouse || frm.__customer_default_warehouse);
    const row = locals[cdt] && locals[cdt][cdn];

    qcmc_logic.customer_warehouse_defaults.set_row_warehouse(row, warehouse);
};

qcmc_logic.customer_warehouse_defaults.set_row_warehouse = function(
    row,
    warehouse,
    previous_default
) {
    if (row && warehouse && (!row.warehouse || row.warehouse === previous_default)) {
        frappe.model.set_value(row.doctype, row.name, "warehouse", warehouse);
    }
};
