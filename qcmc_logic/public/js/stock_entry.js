frappe.provide("qcmc_logic.stock_entry");

qcmc_logic.stock_entry.supported_purposes = new Set([
    "Material Transfer for Manufacture",
    "Material Consumption for Manufacture",
    "Manufacture",
]);

frappe.ui.form.on("Stock Entry", {
    setup(frm) {
        qcmc_logic.stock_entry.setup_manufacture_row_lock(frm);
        qcmc_logic.stock_entry.apply_manufacturing_warehouse_queries(frm);
    },

    refresh(frm) {
        qcmc_logic.stock_entry.apply_manufacturing_warehouse_queries(frm);
        qcmc_logic.stock_entry.apply_job_card_field_rules(frm);
        qcmc_logic.stock_entry.add_job_card_button(frm);
        qcmc_logic.stock_entry.refresh_manufacture_row_locks(frm);
        qcmc_logic.stock_entry.refresh_warehouse_code(frm);
    },

    company(frm) {
        qcmc_logic.stock_entry.apply_manufacturing_warehouse_queries(frm);
    },

    production_item(frm) {
        qcmc_logic.stock_entry.apply_manufacturing_warehouse_queries(frm);
    },

    purpose(frm) {
        qcmc_logic.stock_entry.apply_manufacturing_warehouse_queries(frm);
        qcmc_logic.stock_entry.apply_job_card_field_rules(frm);
        qcmc_logic.stock_entry.add_job_card_button(frm);
        qcmc_logic.stock_entry.refresh_manufacture_row_locks(frm);
        qcmc_logic.stock_entry.refresh_warehouse_code(frm);
    },

    stock_entry_type(frm) {
        qcmc_logic.stock_entry.apply_job_card_field_rules(frm);
        qcmc_logic.stock_entry.refresh_warehouse_code(frm);
    },

    from_warehouse(frm) {
        qcmc_logic.stock_entry.refresh_warehouse_code(frm);
    },

    to_warehouse(frm) {
        qcmc_logic.stock_entry.refresh_warehouse_code(frm);
    },
});

qcmc_logic.stock_entry.apply_manufacturing_warehouse_queries = function(frm) {
    frm.set_query("work_order", () => ({
        query: "qcmc_logic.customs.manufacturing_warehouse_access.work_order_query",
        filters: {
            company: frm.doc.company,
            production_item: frm.doc.production_item,
            bom_no: frm.doc.bom_no,
        },
    }));

    frm.set_query("bom_no", () => ({
        query: "qcmc_logic.customs.manufacturing_warehouse_access.bom_query",
        filters: {
            company: frm.doc.company,
            item: frm.doc.production_item,
        },
    }));
};

frappe.ui.form.on("Stock Entry Detail", {
    s_warehouse(frm) {
        qcmc_logic.stock_entry.refresh_warehouse_code(frm);
    },

    t_warehouse(frm, cdt, cdn) {
        qcmc_logic.stock_entry.refresh_warehouse_code(frm);
    },
});

qcmc_logic.stock_entry.incoming_purposes = new Set([
    "Material Receipt",
    "Manufacture",
    "Receive from Customer",
    "Subcontracting Return",
]);

qcmc_logic.stock_entry.issuance_purposes = new Set([
    "Material Issue",
    "Material Consumption for Manufacture",
    "Send to Subcontractor",
    "Return Raw Material to Customer",
    "Subcontracting Delivery",
]);

qcmc_logic.stock_entry.refresh_warehouse_code = function(frm) {
    const warehouse_field = qcmc_logic.stock_entry.get_wh_code_warehouse_field(frm);
    if (!warehouse_field) {
        return Promise.resolve();
    }

    const warehouse = qcmc_logic.stock_entry.get_single_warehouse(frm, warehouse_field);
    if (!warehouse) {
        if (frm.doc.custom_wh_code) {
            return frm.set_value("custom_wh_code", "");
        }
        return Promise.resolve();
    }

    return frappe.db.get_value("Warehouse", warehouse, "custom_wh_code")
        .then(r => {
            const warehouse_code = r.message && r.message.custom_wh_code;
            if ((warehouse_code || "") !== (frm.doc.custom_wh_code || "")) {
                return frm.set_value("custom_wh_code", warehouse_code);
            }
        });
};

qcmc_logic.stock_entry.get_wh_code_warehouse_field = function(frm) {
    if (qcmc_logic.stock_entry.incoming_purposes.has(frm.doc.purpose)) {
        return "t_warehouse";
    }
    if (qcmc_logic.stock_entry.issuance_purposes.has(frm.doc.purpose)) {
        return "s_warehouse";
    }

    if (["Material Transfer", "Material Transfer for Manufacture", "Repack", "Disassemble"]
        .includes(frm.doc.purpose)) {
        if (qcmc_logic.stock_entry.get_single_warehouse(frm, "s_warehouse")) {
            return "s_warehouse";
        }
        if (qcmc_logic.stock_entry.get_single_warehouse(frm, "t_warehouse")) {
            return "t_warehouse";
        }
    }
};

qcmc_logic.stock_entry.get_single_warehouse = function(frm, warehouse_field) {
    const header_field = warehouse_field === "t_warehouse" ? "to_warehouse" : "from_warehouse";
    const warehouses = new Set(
        (frm.doc.items || [])
            .map(row => row[warehouse_field])
            .filter(Boolean)
    );

    if (frm.doc[header_field]) {
        warehouses.add(frm.doc[header_field]);
    }

    return warehouses.size === 1 ? Array.from(warehouses)[0] : null;
};

qcmc_logic.stock_entry.apply_job_card_field_rules = function(frm) {
    const show_job_card = qcmc_logic.stock_entry.supported_purposes.has(frm.doc.purpose);

    frm.toggle_display("job_card", show_job_card);
    frm.set_df_property("job_card", "read_only", 1);

    if (!show_job_card && frm.doc.job_card) {
        frm.set_value("job_card", "");
    }
};

qcmc_logic.stock_entry.add_job_card_button = function(frm) {
    if (!qcmc_logic.stock_entry.can_fetch_from_job_card(frm)) return;

    frm.add_custom_button(__("Job Card"), () => {
        qcmc_logic.stock_entry.open_job_card_dialog(frm);
    }, __("Get Items From"));
};

qcmc_logic.stock_entry.can_fetch_from_job_card = function(frm) {
    return frm.doc.docstatus === 0 && qcmc_logic.stock_entry.supported_purposes.has(frm.doc.purpose);
};

qcmc_logic.stock_entry.open_job_card_dialog = function(frm) {
    const dialog = new frappe.ui.Dialog({
        title: __("Select Job Card"),
        size: "extra-large",
        fields: [
            {
                fieldtype: "Data",
                fieldname: "search",
                label: __("Search Job Card"),
                onchange() {
                    qcmc_logic.stock_entry.load_job_cards(frm, dialog);
                },
            },
            {
                fieldtype: "HTML",
                fieldname: "job_cards_html",
            },
        ],
        primary_action_label: __("Get Items"),
        primary_action() {
            const selected = dialog.$wrapper.find("input[name='qcmc_job_card']:checked").val();
            if (!selected) {
                frappe.msgprint(__("Please select one Job Card."));
                return;
            }

            qcmc_logic.stock_entry.apply_job_card(frm, dialog, selected);
        },
    });

    dialog.$wrapper.on("change", "input[name='qcmc_job_card']", function() {
        dialog.set_primary_action(__("Get Items"), () => {
            qcmc_logic.stock_entry.apply_job_card(frm, dialog, this.value);
        });
    });

    dialog.show();
    qcmc_logic.stock_entry.load_job_cards(frm, dialog);
};

qcmc_logic.stock_entry.load_job_cards = function(frm, dialog) {
    const values = dialog.get_values() || {};

    frappe.call({
        method: "qcmc_logic.api.stock_entry.get_job_cards_for_stock_entry",
        args: {
            purpose: frm.doc.purpose,
            work_order: frm.doc.work_order,
            txt: values.search || "",
            page_len: 20,
        },
        freeze: true,
        callback(r) {
            const rows = r.message || [];
            dialog._qcmc_job_cards_by_name = Object.fromEntries(
                rows.map((row) => [row.name, row])
            );
            dialog.fields_dict.job_cards_html.$wrapper.html(
                qcmc_logic.stock_entry.render_job_card_rows(rows)
            );
        },
    });
};

qcmc_logic.stock_entry.render_job_card_rows = function(rows) {
    if (!rows.length) {
        return `<div class="text-muted">${__("No selectable Job Cards found.")}</div>`;
    }

    const body = rows.map((row) => {
        const disabled = row.has_pending_material ? "" : "disabled";
        const muted = row.has_pending_material ? "" : "text-muted";

        return `
            <tr class="${muted}">
                <td><input type="radio" name="qcmc_job_card" value="${frappe.utils.escape_html(row.name)}" ${disabled}></td>
                <td>${frappe.utils.escape_html(row.name || "")}</td>
                <td>${frappe.utils.escape_html(row.work_order || "")}</td>
                <td>${frappe.utils.escape_html(row.production_item || "")}</td>
                <td class="text-right">${format_number(row.for_quantity || 0)}</td>
                <td class="text-right">${format_number(row.transferred_qty || 0)}</td>
                <td class="text-right">${format_number(row.consumed_qty || 0)}</td>
                <td class="text-right">${format_number(row.remaining_qty || 0)}</td>
                <td>${frappe.utils.escape_html(row.status || "")}</td>
            </tr>
        `;
    }).join("");

    return `
        <table class="table table-bordered table-sm">
            <thead>
                <tr>
                    <th style="width: 32px"></th>
                    <th>${__("Job Card")}</th>
                    <th>${__("Work Order")}</th>
                    <th>${__("Production Item")}</th>
                    <th class="text-right">${__("Qty")}</th>
                    <th class="text-right">${__("Transferred")}</th>
                    <th class="text-right">${__("Consumed")}</th>
                    <th class="text-right">${__("Remaining")}</th>
                    <th>${__("Status")}</th>
                </tr>
            </thead>
            <tbody>${body}</tbody>
        </table>
    `;
};

qcmc_logic.stock_entry.apply_job_card = function(frm, dialog, job_card) {
    if (frm.doc.purpose === "Manufacture") {
        const selected_row = dialog._qcmc_job_cards_by_name
            && dialog._qcmc_job_cards_by_name[job_card];
        qcmc_logic.stock_entry.prompt_manufacture_quantity(dialog, job_card, selected_row);
        return;
    }

    const replace = () => qcmc_logic.stock_entry.fetch_job_card_items(frm, dialog, job_card);
    const has_items = (frm.doc.items || []).some((row) => row.item_code || row.qty);
    const changing_job_card = frm.doc.job_card && frm.doc.job_card !== job_card;

    if (has_items || changing_job_card) {
        frappe.confirm(
            __("Existing item rows will be cleared before fetching this Job Card. Continue?"),
            replace
        );
        return;
    }

    replace();
};

qcmc_logic.stock_entry.prompt_manufacture_quantity = function(dialog, job_card, selected_row) {
    const available_qty = flt(selected_row && selected_row.remaining_qty);
    if (available_qty <= 0) {
        frappe.msgprint(__("This Job Card has no unposted completed output."));
        return;
    }

    frappe.prompt(
        {
            fieldtype: "Float",
            fieldname: "qty",
            label: __("Finished Goods Quantity"),
            default: available_qty,
            reqd: 1,
            description: __("Available completed output: {0}", [format_number(available_qty)]),
        },
        (values) => {
            const qty = flt(values.qty);
            if (qty <= 0 || qty > available_qty) {
                frappe.throw(
                    __("Finished Goods Quantity must be greater than zero and not exceed {0}.", [
                        format_number(available_qty),
                    ])
                );
            }

            qcmc_logic.stock_entry.create_manufacture_entry(dialog, job_card, qty);
        },
        __("Manufacture Output"),
        __("Create")
    );
};

qcmc_logic.stock_entry.create_manufacture_entry = function(dialog, job_card, qty) {
    frappe.call({
        method: "qcmc_logic.api.stock_entry.make_manufacture_stock_entry_from_job_card",
        args: { job_card, qty },
        freeze: true,
        freeze_message: __("Creating Manufacture Stock Entry..."),
        callback(r) {
            if (!r.message) return;

            dialog.hide();
            const documents = frappe.model.sync(r.message);
            const stock_entry = documents.find((doc) => doc.doctype === "Stock Entry");
            if (stock_entry) {
                frappe.set_route("Form", "Stock Entry", stock_entry.name);
            }
        },
    });
};

qcmc_logic.stock_entry.fetch_job_card_items = function(frm, dialog, job_card) {
    frappe.call({
        method: "qcmc_logic.api.stock_entry.get_job_card_details_for_stock_entry",
        args: {
            job_card,
            purpose: frm.doc.purpose,
            work_order: frm.doc.work_order,
        },
        freeze: true,
        callback(r) {
            const details = r.message;
            if (!details) return;

            qcmc_logic.stock_entry.set_job_card_header(frm, details).then(() => {
                qcmc_logic.stock_entry.apply_job_card_field_rules(frm);
                return qcmc_logic.stock_entry.get_items(frm);
            }).then(() => {
                dialog.hide();

                if (!(frm.doc.items || []).length) {
                    frappe.msgprint(__("No pending material was returned for the selected Job Card."));
                    return;
                }

                frm.refresh();
            });
        },
    });
};

qcmc_logic.stock_entry.set_job_card_header = function(frm, details) {
    const fields = [
        "job_card",
        "work_order",
        "bom_no",
        "from_bom",
        "fg_completed_qty",
        "from_warehouse",
        "to_warehouse",
    ];

    return fields.reduce((promise, fieldname) => {
        return promise.then(() => {
            const value = Object.prototype.hasOwnProperty.call(details, fieldname)
                ? details[fieldname]
                : null;
            return frm.set_value(fieldname, value);
        });
    }, Promise.resolve());
};

qcmc_logic.stock_entry.get_items = function(frm) {
    return frm.call({
        doc: frm.doc,
        freeze: true,
        method: "get_items",
        callback(r) {
            if (!r.exc) {
                frm.refresh_field("items");
            }
        },
    });
};

qcmc_logic.stock_entry.setup_manufacture_row_lock = function(frm) {
    $(frm.wrapper).off("grid-row-render.qcmc_manufacture");
    $(frm.wrapper).on("grid-row-render.qcmc_manufacture", (event, grid_row) => {
        if (grid_row.grid.df.fieldname !== "items") return;
        qcmc_logic.stock_entry.apply_manufacture_row_lock(frm, grid_row);
    });
};

qcmc_logic.stock_entry.refresh_manufacture_row_locks = function(frm) {
    const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
    if (!grid) return;

    const lock_structure = frm.doc.purpose === "Manufacture" && frm.doc.work_order;
    grid.cannot_add_rows = Boolean(lock_structure);
    grid.wrapper
        .find(".grid-add-row, .grid-add-multiple-rows, .grid-remove-rows")
        .toggle(!lock_structure);

    grid.grid_rows.forEach((grid_row) => {
        qcmc_logic.stock_entry.apply_manufacture_row_lock(frm, grid_row);
    });
};

qcmc_logic.stock_entry.apply_manufacture_row_lock = function(frm, grid_row) {
    const should_lock = (
        frm.doc.purpose === "Manufacture"
        && frm.doc.work_order
        && !grid_row.doc.is_finished_item
    );

    if (!should_lock) return;

    grid_row.docfields.forEach((df) => {
        if (df.fieldname && !["idx"].includes(df.fieldname)) {
            grid_row.toggle_editable(df.fieldname, false);
        }
    });

    grid_row.wrapper
        .find(".grid-delete-row, .grid-move-row, .grid-duplicate-row")
        .hide();
};
