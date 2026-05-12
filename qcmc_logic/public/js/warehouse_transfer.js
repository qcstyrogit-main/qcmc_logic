frappe.provide("qcmc_logic.warehouse_transfer");

frappe.ui.form.on("Warehouse Transfer", {
    setup(frm) {
        qcmc_logic.warehouse_transfer.set_queries(frm);
    },

    refresh(frm) {
        qcmc_logic.warehouse_transfer.set_queries(frm);
        qcmc_logic.warehouse_transfer.configure_receiving_state(frm);
        qcmc_logic.warehouse_transfer.add_get_items_buttons(frm);
    },

    source_warehouse(frm) {
        frm.set_value("target_warehouse", "");
        qcmc_logic.warehouse_transfer.set_queries(frm);
    },

    transfer_type(frm) {
        frm.set_value("target_warehouse", "");
        qcmc_logic.warehouse_transfer.set_queries(frm);
    },

    target_warehouse(frm) {
        qcmc_logic.warehouse_transfer.configure_receiving_state(frm);
    },
});

qcmc_logic.warehouse_transfer.add_get_items_buttons = function(frm) {
    if (frm.doc.docstatus !== 0 || frm.doc.transfer_status === "Transferred") return;

    frm.add_custom_button(__("Get Items From Material Request"), () => {
        qcmc_logic.warehouse_transfer.open_material_request_picker(frm);
    });
};

qcmc_logic.warehouse_transfer.set_queries = function(frm) {
    frm.set_query("target_warehouse", () => ({
        query: "qcmc_logic.utils.get_target_warehouse_query",
        filters: {
            user: frappe.session.user,
            source_warehouse: frm.doc.source_warehouse,
            transfer_type: frm.doc.transfer_type,
        },
    }));

};

qcmc_logic.warehouse_transfer.open_material_request_picker = function(frm) {
    if (!frm.doc.transfer_type || !frm.doc.source_warehouse || !frm.doc.target_warehouse) {
        frappe.msgprint(__("Please select Transfer Type, Source Warehouse, and Target Warehouse first."));
        return;
    }

    frappe.call({
        method: "qcmc_logic.utils.get_possible_material_transfer_requests",
        args: {
            transfer_type: frm.doc.transfer_type,
            source_warehouse: frm.doc.source_warehouse,
            target_warehouse: frm.doc.target_warehouse,
        },
        freeze: true,
        callback(r) {
            const requests = r.message || [];
            if (!requests.length) {
                frappe.msgprint(__("No submitted Material Transfer requests are possible for this transfer."));
                return;
            }

            qcmc_logic.warehouse_transfer.show_material_request_dialog(frm, requests);
        },
    });
};

qcmc_logic.warehouse_transfer.show_material_request_dialog = function(frm, requests) {
    const rows = requests.map(request => {
        return `
            <tr>
                <td><input type="checkbox" class="mr-check" data-name="${frappe.utils.escape_html(request.name)}"></td>
                <td>${frappe.utils.escape_html(request.name)}</td>
                <td>${frappe.utils.escape_html(request.transaction_date || "")}</td>
                <td>${frappe.utils.escape_html(request.company || "")}</td>
                <td>${frappe.utils.escape_html(request.source_warehouse || "")}</td>
                <td>${frappe.utils.escape_html(request.target_warehouse || "")}</td>
            </tr>
        `;
    }).join("");

    const dialog = new frappe.ui.Dialog({
        title: __("Get Items From Material Request"),
        size: "extra-large",
        fields: [
            {
                fieldtype: "HTML",
                fieldname: "requests_html",
                options: `
                    <table class="table table-bordered table-sm">
                        <thead>
                            <tr>
                                <th style="width: 32px"><input type="checkbox" class="select-all-mr"></th>
                                <th>${__("Material Request")}</th>
                                <th>${__("Date")}</th>
                                <th>${__("Company")}</th>
                                <th>${__("Source Warehouse")}</th>
                                <th>${__("Target Warehouse")}</th>
                            </tr>
                        </thead>
                        <tbody>${rows}</tbody>
                    </table>
                `,
            },
        ],
        primary_action_label: __("Get Items"),
        primary_action() {
            const selected = [];
            dialog.$wrapper.find(".mr-check:checked").each(function() {
                selected.push($(this).data("name"));
            });

            if (!selected.length) {
                frappe.msgprint(__("Select at least one Material Request."));
                return;
            }

            qcmc_logic.warehouse_transfer.get_items_from_material_requests(frm, selected, dialog);
        },
    });

    dialog.$wrapper.on("change", ".select-all-mr", function() {
        dialog.$wrapper.find(".mr-check").prop("checked", $(this).is(":checked"));
    });

    dialog.show();
};

qcmc_logic.warehouse_transfer.get_items_from_material_requests = function(frm, material_requests, dialog) {
    frappe.call({
        method: "qcmc_logic.utils.get_material_transfer_requests_for_warehouse_transfer",
        args: {
            material_requests,
            transfer_type: frm.doc.transfer_type,
            source_warehouse: frm.doc.source_warehouse,
            target_warehouse: frm.doc.target_warehouse,
        },
        freeze: true,
        callback(r) {
            const data = r.message || {};
            const items = data.items || [];

            if (data.source_warehouse && !frm.doc.source_warehouse) {
                frm.set_value("source_warehouse", data.source_warehouse);
            }
            if (data.target_warehouse && !frm.doc.target_warehouse) {
                frm.set_value("target_warehouse", data.target_warehouse);
            }

            items.forEach(item => {
                const child = frm.add_child("transfer_items");
                child.item_code = item.item_code;
                child.item_name = item.item_name;
                child.uom = item.uom;
                child.issued_qty = flt(item.issued_qty || 0);
                child.received_qty = 0;
                child.reference_doc = item.reference_doc;
            });

            frm.refresh_field("transfer_items");
            dialog.hide();
        },
    });
};

qcmc_logic.warehouse_transfer.configure_receiving_state = function(frm) {
    if (frm.doc.transfer_status === "Received") {
        frm.set_read_only();
        return;
    }

    const grid = frm.fields_dict.transfer_items && frm.fields_dict.transfer_items.grid;
    if (!grid) return;

    if (frm.doc.transfer_status !== "Transferred") {
        grid.update_docfield_property("issued_qty", "read_only", 0);
        grid.update_docfield_property("received_qty", "read_only", 0);
        grid.update_docfield_property("item_code", "read_only", 0);
        grid.update_docfield_property("uom", "read_only", 0);
        return;
    }

    grid.update_docfield_property("issued_qty", "read_only", 1);
    grid.update_docfield_property("received_qty", "read_only", 1);
    grid.update_docfield_property("item_code", "read_only", 1);
    grid.update_docfield_property("uom", "read_only", 1);

    frappe.call({
        method: "qcmc_logic.utils.check_warehouse_access",
        args: {
            user: frappe.session.user,
            warehouse: frm.doc.target_warehouse,
            require_transact: 1,
        },
        callback(r) {
            if (!r.message) return;

            frm.add_custom_button(__("Receive Items"), () => {
                qcmc_logic.warehouse_transfer.open_receiving_dialog(frm);
            });
        },
    });
};

qcmc_logic.warehouse_transfer.open_receiving_dialog = function(frm) {
    const existing_items = frm.doc.transfer_items || [];
    const dialog = new frappe.ui.Dialog({
        title: __("Receive Items"),
        size: "extra-large",
        fields: [
            {
                fieldtype: "HTML",
                fieldname: "items_html",
            },
            {
                fieldtype: "Button",
                fieldname: "add_row",
                label: __("Add Item"),
                click() {
                    const idx = dialog.$wrapper.find(".wt-receive-row").length;
                    dialog.$wrapper.find("tbody").append(
                        qcmc_logic.warehouse_transfer.render_receive_row({}, idx, true)
                    );
                    qcmc_logic.warehouse_transfer.make_item_control(dialog, idx);
                },
            },
        ],
        primary_action_label: __("Save"),
        primary_action() {
            qcmc_logic.warehouse_transfer.apply_receiving_rows(frm, dialog);
            dialog.hide();
        },
    });

    const rows = existing_items.map((row, idx) => {
        return qcmc_logic.warehouse_transfer.render_receive_row(row, idx, false);
    }).join("");

    dialog.fields_dict.items_html.$wrapper.html(`
        <table class="table table-bordered">
            <thead>
                <tr>
                    <th>${__("Item")}</th>
                    <th>${__("Item Name")}</th>
                    <th>${__("UOM")}</th>
                    <th class="text-right">${__("Issued Qty")}</th>
                    <th class="text-right">${__("Received Qty")}</th>
                    <th class="text-right">${__("Variance")}</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `);

    dialog.$wrapper.on("input", ".received-qty", function() {
        const $row = $(this).closest("tr");
        const issued = flt($row.attr("data-issued"));
        const received = flt($(this).val());
        $row.find(".variance").text(format_number(issued - received, null, 2));
    });

    dialog.show();
};

qcmc_logic.warehouse_transfer.render_receive_row = function(row, idx, is_new) {
    const issued = flt(row.issued_qty || 0);
    const received = flt(row.received_qty || 0);
    const item_code = frappe.utils.escape_html(row.item_code || "");
    const item_name = frappe.utils.escape_html(row.item_name || "");
    const uom = frappe.utils.escape_html(row.uom || "");

    return `
        <tr class="wt-receive-row" data-idx="${idx}" data-name="${row.name || ""}" data-new="${is_new ? 1 : 0}" data-issued="${issued}">
            <td>${is_new ? `<div class="item-control" data-idx="${idx}"></div>` : item_code}</td>
            <td class="item-name">${item_name}</td>
            <td class="uom">${uom}</td>
            <td class="text-right issued-qty">${format_number(issued, null, 2)}</td>
            <td><input type="number" class="form-control text-right received-qty" value="${received}" min="0"></td>
            <td class="text-right variance">${format_number(issued - received, null, 2)}</td>
        </tr>
    `;
};

qcmc_logic.warehouse_transfer.make_item_control = function(dialog, idx) {
    const $parent = dialog.$wrapper.find(`.item-control[data-idx="${idx}"]`);
    const control = frappe.ui.form.make_control({
        parent: $parent,
        render_input: true,
        df: {
            fieldtype: "Link",
            options: "Item",
            fieldname: `received_item_${idx}`,
            change() {
                const item_code = control.get_value();
                if (!item_code) return;

                frappe.db.get_value("Item", item_code, ["item_name", "stock_uom"]).then(r => {
                    const values = r.message || {};
                    const $row = $parent.closest("tr");
                    $row.attr("data-item-code", item_code);
                    $row.find(".item-name").text(values.item_name || "");
                    $row.find(".uom").text(values.stock_uom || "");
                });
            },
        },
    });
};

qcmc_logic.warehouse_transfer.apply_receiving_rows = function(frm, dialog) {
    dialog.$wrapper.find(".wt-receive-row").each(function() {
        const $row = $(this);
        const is_new = cint($row.attr("data-new"));
        const received_qty = flt($row.find(".received-qty").val());

        if (is_new) {
            const item_code = $row.attr("data-item-code");
            if (!item_code && received_qty) {
                frappe.throw(__("Item is required for receiver-added rows."));
            }
            if (!item_code) return;

            const child = frm.add_child("transfer_items");
            child.item_code = item_code;
            child.item_name = $row.find(".item-name").text();
            child.uom = $row.find(".uom").text();
            child.issued_qty = 0;
            child.received_qty = received_qty;
            child.reference_doc = "";
        } else {
            const row_name = $row.attr("data-name");
            const child = (frm.doc.transfer_items || []).find(item => item.name === row_name);
            if (child) {
                child.received_qty = received_qty;
            }
        }
    });

    frm.refresh_field("transfer_items");
    frm.save();
};
