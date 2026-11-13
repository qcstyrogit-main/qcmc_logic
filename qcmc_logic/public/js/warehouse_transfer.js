frappe.provide("qcmc_logic.warehouse_transfer");

frappe.ui.form.on("Warehouse Transfer", {
    setup(frm) {
        qcmc_logic.warehouse_transfer.set_queries(frm);
        qcmc_logic.warehouse_transfer.watch_pick_list_action(frm);
        qcmc_logic.warehouse_transfer.watch_pick_list_render(frm);
    },

    onload_post_render(frm) {
        // Standard form toolbar actions may be rebuilt after refresh handlers.
        qcmc_logic.warehouse_transfer.add_pick_list_action(frm);
    },

    refresh(frm) {
        qcmc_logic.warehouse_transfer.configure_allocation(frm);
        qcmc_logic.warehouse_transfer.set_queries(frm);
        qcmc_logic.warehouse_transfer.apply_default_source_warehouse(frm);
        qcmc_logic.warehouse_transfer.configure_receiving_state(frm);
        qcmc_logic.warehouse_transfer.toggle_shipping_details(frm);
        qcmc_logic.warehouse_transfer.add_get_items_buttons(frm);
        qcmc_logic.warehouse_transfer.add_pick_list_action(frm);
        // Existing Pick Lists are now shown in the native Connections tab.
        frm.dashboard.parent.find(".qcmc-linked-pick-lists").remove();
        qcmc_logic.warehouse_transfer.render_pick_list_connections(frm);
    },

    custom_apply_putaway_rule(frm) {
        qcmc_logic.warehouse_transfer.configure_allocation(frm);
    },

    after_save(frm) {
        frm.refresh_field("custom_storage_allocation");
    },

    source_warehouse(frm) {
        qcmc_logic.warehouse_transfer.set_queries(frm);
    },

    transfer_type(frm) {
        qcmc_logic.warehouse_transfer.set_queries(frm);
        qcmc_logic.warehouse_transfer.toggle_shipping_details(frm);
    },

    custom_with_shipping_details(frm) {
        qcmc_logic.warehouse_transfer.toggle_shipping_details(frm);
    },

    target_warehouse(frm) {
        qcmc_logic.warehouse_transfer.set_queries(frm);
        qcmc_logic.warehouse_transfer.configure_receiving_state(frm);
    },
});

qcmc_logic.warehouse_transfer.render_pick_list_connections = async function(frm) {
    const tab = (frm.layout?.tabs || []).find(t => t.df?.fieldname === "connections_tab");
    if (!tab?.wrapper) return;
    // Frappe hides an empty custom tab during form refresh.
    // Keep this relationship tab visible even without ordinary data fields.
    tab.toggle(true);
    frm.layout.tab_link_container?.show();
    // Warehouse Transfer uses a custom DocType whose existing allocation
    // sections were appended after the newly added Tab Break. Keep all
    // existing fields in Details and reserve Connections for relationships.
    const details = (frm.layout?.tabs || []).find(t =>
        t.df?.fieldname === "__details" || t.df?.label === "Details"
    );
    if (details?.wrapper) {
        tab.wrapper.children(".form-section").appendTo(details.wrapper);
    }
    const target = tab.wrapper;
    target.find(".qcmc-pick-connection-card").remove();
    if (frm.is_new()) return;
    const name = frm.doc.name;
    try {
        const links = await frappe.xcall(
            "qcmc_logic.overrides.pick_list.get_linked_pick_lists",
            {warehouse_transfer: name}
        );
        if (frm.doc.name !== name) return;
        // Render Frappe's own form_links template, CSS classes and count badge.
        // No hand-built card styling and no duplicate document link below it.
        // Frappe's form_links styles are scoped under .form-links, and its
        // dashboard sections wrap the transactions in .section-body.
        const container = $('<div class="qcmc-pick-connection-card form-dashboard-section form-links visible-section"></div>');
        const section_body = $('<div class="section-body"></div>').appendTo(container);
        const content = $('<div class="transactions"></div>').appendTo(section_body);
        const dashboard_data = {
            transactions: [{label: __("Inventory"), items: ["Pick List"]}],
            internal_links: {"Pick List": ["custom_warehouse_transfer"]},
            frm: frm,
        };
        $(frappe.render_template("form_links", dashboard_data)).appendTo(content);
        const doc_link = content.find('.document-link[data-doctype="Pick List"]');
        doc_link.find(".count").removeClass("hidden")
            .text(links.length).attr("title", __("Count of linked documents"));
        // Native Frappe connection navigation opens the linked document list,
        // filtered to this Warehouse Transfer, rather than an unrelated record.
        doc_link.find(".badge-link").on("click", event => {
            event.preventDefault();
            frappe.route_options = {custom_warehouse_transfer: name};
            frappe.set_route("List", "Pick List", "List");
        });
        target.prepend(container);
        tab.toggle(true);
        if (details) details.toggle(true);
        frm.layout.tab_link_container?.show();
    } catch (error) {
        console.warn("Warehouse Transfer connections lookup failed", error);
    }
};

qcmc_logic.warehouse_transfer.watch_pick_list_render = function(frm) {
    if (frm.__qcmc_pick_render_watched) return;
    frm.__qcmc_pick_render_watched = true;
    // Record navigation uses an asynchronous form render; toolbar and doc
    // children can settle after the first refresh handler has run.
    $(frm.wrapper).on("render_complete.qcmc_pick_menu", () => {
        frappe.after_ajax(() => {
            if (frm.doctype === "Warehouse Transfer") {
                qcmc_logic.warehouse_transfer.add_pick_list_action(frm);
            }
        });
    });
};

qcmc_logic.warehouse_transfer.watch_pick_list_action = function(frm) {
    if (frm.__qcmc_pick_menu_watched) return;
    frm.__qcmc_pick_menu_watched = true;
    $(frm.wrapper).on("dirty.qcmc_pick_menu", () => {
        // Toolbar clears the menu on dirty; restore only our native action.
        setTimeout(() => qcmc_logic.warehouse_transfer.add_pick_list_action(frm), 0);
    });
};

qcmc_logic.warehouse_transfer.add_pick_list_action = function(frm) {
    if (frm.is_new() || frm.doc.docstatus !== 0 || frm.doc.transfer_status !== "Draft") return;
    if (!["Warehouse Transfer"].includes(frm.doc.transfer_type)) return;
    if (!(frm.doc.transfer_items || []).some(row => flt(row.issued_qty) > 0)) return;
    // Add to the built-in black Actions menu, not a new custom button group.
    // This avoids a second grey "Actions" dropdown.
    frm.remove_custom_button(__("Create Pick List"), __("Actions"));
    frm.remove_custom_button(__("Create Pick List"));
    frm.page.add_action_item(__("Create Pick List"), async () => {
        if (frm.is_dirty()) {
            frappe.msgprint(__("Save the Warehouse Transfer before creating its Pick List."));
            return;
        }
        const result = await frappe.xcall("qcmc_logic.overrides.pick_list.create_pick_list_from_warehouse_transfer", {
            warehouse_transfer: frm.doc.name,
        });
        if (result && result.name) {
            frappe.set_route("Form", "Pick List", result.name);
        }
    });
};

qcmc_logic.warehouse_transfer.shipping_detail_fields = [
    "custom_etd",
    "custom_eta",
    "custom_shipping_details_column_break",
    "custom_seal_no",
    "custom_van_no",
    "custom_shipping_line",
    "custom_shipping_remarks",
];

qcmc_logic.warehouse_transfer.toggle_shipping_details = function(frm) {
    const is_pwt = frm.doc.transfer_type === "Provincial Warehouse Transfer";
    const show_details = is_pwt && cint(frm.doc.custom_with_shipping_details);

    if (frm.fields_dict.custom_shipping_details_section) {
        frm.toggle_display("custom_shipping_details_section", show_details);
    }
    if (frm.fields_dict.custom_with_shipping_details) {
        frm.toggle_display("custom_with_shipping_details", is_pwt);
    }

    qcmc_logic.warehouse_transfer.shipping_detail_fields.forEach(fieldname => {
        if (frm.fields_dict[fieldname]) {
            frm.toggle_display(fieldname, show_details);
        }
    });
};

qcmc_logic.warehouse_transfer.add_get_items_buttons = function(frm) {
    if (!qcmc_logic.warehouse_transfer.can_get_items_from_material_request(frm)) return;

    frm.add_custom_button(__("Get Items From Material Request"), () => {
        qcmc_logic.warehouse_transfer.open_material_request_picker(frm);
    });
};

qcmc_logic.warehouse_transfer.can_get_items_from_material_request = function(frm) {
    if (frm.doc.docstatus !== 0) return false;

    const transfer_status = frm.doc.transfer_status || "Draft";
    return transfer_status === "Draft";
};

qcmc_logic.warehouse_transfer.set_queries = function(frm) {
    frm.set_query("source_warehouse", () => ({
        query: "qcmc_logic.utils.get_source_warehouse_query",
        filters: {
            user: frappe.session.user,
            target_warehouse: frm.doc.target_warehouse,
            transfer_type: frm.doc.transfer_type,
        },
    }));

    frm.set_query("target_warehouse", () => ({
        query: "qcmc_logic.utils.get_target_warehouse_query",
        filters: {
            user: frappe.session.user,
            source_warehouse: frm.doc.source_warehouse,
            transfer_type: frm.doc.transfer_type,
        },
    }));

};

qcmc_logic.warehouse_transfer.apply_default_source_warehouse = function(frm) {
    if (!frm.is_new() || frm.doc.docstatus !== 0 || frm.doc.source_warehouse) {
        return;
    }

    frappe.call({
        method: "qcmc_logic.utils.get_default_warehouse_for_user",
        args: {
            user: frappe.session.user,
            require_transact: 1,
        },
        callback(r) {
            if (r.message && !frm.doc.source_warehouse) {
                frm.set_value("source_warehouse", r.message);
            }
        },
    });
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
                child.reference_doc = item.reference_doc || "";
                child.material_request = item.material_request;
                child.material_request_item = item.material_request_item;
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
        grid.update_docfield_property("received_qty", "read_only", 1);
        grid.update_docfield_property("item_code", "read_only", 0);
        grid.update_docfield_property("uom", "read_only", 0);
        grid.update_docfield_property("reference_doc", "label", __("Remarks"));
        return;
    }

    grid.update_docfield_property("issued_qty", "read_only", 1);
    grid.update_docfield_property("received_qty", "read_only", 1);
    grid.update_docfield_property("item_code", "read_only", 1);
    grid.update_docfield_property("uom", "read_only", 1);
    grid.update_docfield_property("reference_doc", "label", __("Remarks"));

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
            qcmc_logic.warehouse_transfer.apply_receiving_rows(frm, dialog).then(() => {
                dialog.hide();
            });
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
    let has_changes = false;

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
            child.material_request = "";
            child.material_request_item = "";
            has_changes = true;
        } else {
            const row_name = $row.attr("data-name");
            const child = (frm.doc.transfer_items || []).find(item => item.name === row_name);
            if (child) {
                child.received_qty = received_qty;
                has_changes = true;
            }
        }
    });

    if (has_changes) {
        frm.dirty();
    }

    frm.refresh_field("transfer_items");
    return frm.save("Update");
};

qcmc_logic.warehouse_transfer.configure_allocation = function(frm) {
    const closed = frm.doc.docstatus === 2 || frm.doc.transfer_status === "Received"
        || (frm.doc.docstatus === 1 && !frm.doc.custom_storage_allocation_enabled);
    frm.set_df_property("custom_apply_putaway_rule", "read_only", closed ? 1 : 0);
    frm.set_df_property("custom_storage_allocation_section", "hidden",
        frm.is_new() || !frm.doc.custom_storage_allocation_enabled || !frm.doc.custom_apply_putaway_rule ? 1 : 0);
    frm.refresh_field("custom_storage_allocation");
};
