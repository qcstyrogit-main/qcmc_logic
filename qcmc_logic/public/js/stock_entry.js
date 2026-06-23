frappe.provide("qcmc_logic.stock_entry");

qcmc_logic.stock_entry.supported_purposes = new Set([
    "Material Transfer for Manufacture",
    "Material Consumption for Manufacture",
]);

frappe.ui.form.on("Stock Entry", {
    refresh(frm) {
        qcmc_logic.stock_entry.add_job_card_button(frm);
    },

    purpose(frm) {
        qcmc_logic.stock_entry.add_job_card_button(frm);
    },
});

qcmc_logic.stock_entry.add_job_card_button = function(frm) {
    if (!qcmc_logic.stock_entry.can_fetch_from_job_card(frm)) return;

    frm.add_custom_button(__("Get Items from Job Card"), () => {
        qcmc_logic.stock_entry.open_job_card_dialog(frm);
    }, __("Get Items From"));
};

qcmc_logic.stock_entry.can_fetch_from_job_card = function(frm) {
    return frm.doc.docstatus === 0 && qcmc_logic.stock_entry.supported_purposes.has(frm.doc.purpose);
};

qcmc_logic.stock_entry.open_job_card_dialog = function(frm) {
    const dialog = new frappe.ui.Dialog({
        title: __("Get Items from Job Card"),
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
