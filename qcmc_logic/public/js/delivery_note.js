frappe.ui.form.on("Delivery Note", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || !(
			frappe.user.has_role("Credit and Collection User") ||
			frappe.user.has_role("Credit and Collection Section Head")
		)) return;

		const received = Boolean(frm.doc.custom_date_received);
		frm.add_custom_button(received ? __("Unreceive") : __("Tag as Received"), () => {
			frappe.call({
				method: "frappe.client.set_value",
				args: {
					doctype: "Delivery Note",
					name: frm.doc.name,
					fieldname: "custom_date_received",
					value: received ? null : frappe.datetime.now_datetime(),
				},
				freeze: true,
				callback(response) {
					if (response.exc) return;
					frm.reload_doc();
					frappe.msgprint(received
						? __("Delivery Note untagged as received.")
						: __("Delivery Note tagged as received."));
				},
			});
		}, __("Actions"));
	},

	validate(frm) {
		if (frm._qcmc_invoice_lookup_pending) {
			frappe.throw(__("Wait for the linked invoice check to finish, then save again."));
		}
	},
	after_save(frm) {
		if (!frm._qcmc_sync_draft_invoice_quantities) return;
		frm._qcmc_sync_draft_invoice_quantities = false;
		frappe.call({
			method: "qcmc_logic.api.delivery_note.sync_draft_invoice_quantities_from_delivery_note",
			args: {dn_name: frm.doc.name},
			freeze: true,
			callback(response) {
				if (response.exc) return;
				const names = response.message || [];
				frappe.show_alert({message: names.length ? __("Updated linked draft invoice quantities: {0}", [names.join(", ")]) : __("No linked draft invoice quantities needed updating."), indicator: "green"});
			}
		});
	},
	before_save(frm) {
		check_delivery_note_warning(frm, "Save");
	},

	before_submit(frm) {
		check_delivery_note_warning(frm, "Submit");
	},
});

frappe.ui.form.on("Delivery Note Item", {
	qty(frm, cdt, cdn) {
		if (frm.is_new() || frm.doc.workflow_state !== "To Deliver and Bill") return;
		const row = locals[cdt][cdn];
		if (row.__qcmc_invoice_prompted_qty === row.qty) return;
		row.__qcmc_invoice_prompted_qty = row.qty;
		frm._qcmc_invoice_lookup_pending = true;
		frappe.call({
			method: "qcmc_logic.api.delivery_note.get_delivery_note_draft_invoices",
			args: {dn_name: frm.doc.name},
			callback(response) {
				frm._qcmc_invoice_lookup_pending = false;
				if (response.exc) return;
				const invoices = response.message || [];
				if (!invoices.length) return;
				if (invoices.some(invoice => cint(invoice.docstatus) === 1)) {
					frappe.msgprint({title: __("Submitted invoice"), message: __("A linked invoice has already been submitted. The Delivery Note quantity was not saved. Correct the invoice and Delivery Note through the approved amendment process."), indicator: "red"});
					frm.reload_doc();
					return;
				}
				if (invoices.length > 1) {
					frappe.msgprint({title: __("Multiple linked invoices"), message: __("More than one draft invoice is linked to this Delivery Note. Resolve the invoice links before changing quantities so invoice quantities are not duplicated."), indicator: "orange"});
					frm.reload_doc();
					return;
				}
				const names = invoices.map(invoice => invoice.name).join(", ");
				if (!invoices[0].can_write) {
					frappe.confirm(
						__("A draft invoice is linked to this Delivery Note ({0}), but you do not have permission to update it. Continue with the Delivery Note quantity change without updating the invoice?", [names]),
						() => { frm._qcmc_sync_draft_invoice_quantities = false; },
						() => { frm.reload_doc(); }
					);
					return;
				}
				frappe.confirm(
					__("A draft invoice is linked to this Delivery Note ({0}). Update its item quantities when you save the Delivery Note?", [names]),
					() => { frm._qcmc_sync_draft_invoice_quantities = true; },
					() => { frm._qcmc_sync_draft_invoice_quantities = false; }
				);
			}
		});
	}
});

function check_delivery_note_warning(frm, action) {
	if (frm._qcmc_delivery_warning_confirmed_action === action) {
		frm._qcmc_delivery_warning_confirmed_action = null;
		return;
	}
	frappe.validated = false;
	frappe.call({
		method: "qcmc_logic.customs.delivery_note_warning.get_sales_order_delivery_warning",
		args: { delivery_note: frm.doc },
		freeze: true,
		freeze_message: __("Checking existing Delivery Notes..."),
		callback(response) {
			const result = response.message || {};
			if (!result.has_warning) {
				continue_delivery_note_action(frm, action);
				return;
			}

			frappe.warn(
				__("Possible Duplicate or Excess Delivery"),
				result.message,
				() => continue_delivery_note_action(frm, action),
				__("Continue"),
				true
			);
		},
		});
}

function continue_delivery_note_action(frm, action) {
	frm._qcmc_delivery_warning_confirmed_action = action;
	frm.save(action);
}


function qcmc_refresh_dn_invoice_action(frm) {
    const label = __("Create Sales Invoice");
    frm.remove_custom_button(label);
    const has_number = Boolean(String(frm.doc.custom_dr_number || "").trim());
    if (!has_number || frm.is_dirty()) {
        frm.remove_custom_button(__("Sales Invoice"), __("Create"));
        frm.remove_custom_button(__("Sales Invoice"));
        frm.remove_custom_button(label, __("Create"));
        return;
    }
    if (frm.is_new() || frm.doc.docstatus !== 0 || !frappe.model.can_create("Sales Invoice")) return;
    const roles = frappe.user_roles || [];
    const eligible = frm.doc.workflow_state === "To Deliver and Bill"
        || roles.includes("Provincial Stock User")
        || (roles.includes("Invoicing Clerk") && (
            frm.doc.workflow_state === "Draft" && (frm.doc.items || []).length
                && (frm.doc.is_return || frm.doc.items.every(item => item.custom_so_delivery_schedule)
                    || (!frm.doc.custom_sales_order && frm.doc.items.every(item => !item.against_sales_order && !item.so_detail)))));
    if (!eligible) return;
    frm.add_custom_button(label, () => {
        if (frm.is_dirty() || !String(frm.doc.custom_dr_number || "").trim()) {
            return frappe.msgprint(__("Save the Delivery Note with its DR Number before creating the invoice."));
        }
        frappe.call({
            method: "qcmc_logic.api.delivery_note.create_sales_invoice_from_draft_dn",
            args: {dn_name: frm.doc.name},
            freeze: true,
            callback(r) {
                if (r.exc || !r.message) return;
                const doc = frappe.model.sync(r.message)[0];
                frappe.set_route("Form", doc.doctype, doc.name);
            }
        });
    });
}

async function qcmc_check_dn_dr_number(frm) {
    const number = String(frm.doc.custom_dr_number || "").trim();
    const company = frm.doc.company;
    const sequence = (frm._qcmc_dr_check_sequence || 0) + 1;
    frm._qcmc_dr_check_sequence = sequence;
    const field = frm.get_field("custom_dr_number");
    if (!field) return;
    field.set_description("");
    if (!number || !company || frm.doc.docstatus === 2) return;
    try {
        const result = await frappe.xcall("qcmc_logic.customs.delivery_dr_number.check_dr_number", {
            company, dr_number: number, delivery_note: frm.is_new() ? null : frm.doc.name
        });
        if (sequence !== frm._qcmc_dr_check_sequence || company !== frm.doc.company
                || number !== String(frm.doc.custom_dr_number || "").trim()) return;
        const esc = frappe.utils.escape_html;
        if (result?.duplicate) {
            field.set_description('<span class="text-danger">' + esc(__("DR Number already used by another active Delivery Note in this company."))
                + (result.delivery_note ? ' <a href="/desk/delivery-note/' + encodeURIComponent(result.delivery_note) + '">' + esc(result.delivery_note) + '</a>' : '') + '</span>');
        } else {
            field.set_description('<span class="text-success">' + esc(__("DR Number available in this company. Final validation occurs on save.")) + '</span>');
        }
    } catch (error) {
        if (sequence === frm._qcmc_dr_check_sequence) field.set_description(__("DR Number will be validated on save."));
    }
}

function qcmc_configure_manual_schedule_links(frm) {
    const grid = frm.fields_dict.items?.grid;
    if (!grid) return;
    const editable = frm.doc.docstatus === 0 && frm.doc.workflow_state === "Draft"
        && !frm.doc.is_return && (frappe.user_roles || []).some(role => ["Head Office Sales User", "Sales Coordinator", "System Manager"].includes(role));
    grid.update_docfield_property("custom_so_delivery_schedule", "read_only", editable ? 0 : 1);
    frm.set_query("custom_so_delivery_schedule", "items", (doc, cdt, cdn) => {
        const item = locals[cdt][cdn];
        return {filters: {sales_order: item.against_sales_order || "__none__", sales_order_item: item.so_detail || "__none__",
            item_code: item.item_code, warehouse: item.warehouse, history_status: "Verified",
            endorsement_status: "Endorsed", confirmation_status: "Finalized"}};
    });
}

frappe.ui.form.on("Delivery Note", {
    refresh(frm) {
        qcmc_configure_manual_schedule_links(frm);
        qcmc_refresh_dn_invoice_action(frm);
        qcmc_check_dn_dr_number(frm);
    },
    custom_dr_number(frm) {
        qcmc_refresh_dn_invoice_action(frm);
        qcmc_check_dn_dr_number(frm);
    },
    company(frm) {
        qcmc_refresh_dn_invoice_action(frm);
        qcmc_check_dn_dr_number(frm);
    },
    after_save(frm) {
        qcmc_refresh_dn_invoice_action(frm);
    }
});

// Capture the actual stock posting timestamp at final workflow submission.
// The values are request-only; cancelling the dialog does not change the draft.
function qcmc_confirm_actual_posting(frm) {
    const now = frappe.datetime.now_datetime().split(' ');
    return new Promise((resolve, reject) => {
        let confirmed = false;
        const dialog = new frappe.ui.Dialog({
            title: __('Confirm Actual Delivery Posting'),
            fields: [
                {fieldtype: 'HTML', fieldname: 'instructions', options: '<p>' + __('Enter the actual delivery posting date and time. Confirming will submit the Delivery Note.') + '</p>'},
                {fieldtype: 'Date', fieldname: 'posting_date', label: __('Posting Date'), reqd: 1, default: now[0]},
                {fieldtype: 'Time', fieldname: 'posting_time', label: __('Posting Time'), reqd: 1, default: now[1]},
            ],
            primary_action_label: __('Confirm and Submit'),
            primary_action(values) {
                if (!values || !values.posting_date || !values.posting_time) return;
                let time = String(values.posting_time);
                if (time.length === 5) time += ':00';
                frm.doc._qcmc_actual_posting = {posting_date: values.posting_date, posting_time: time};
                confirmed = true;
                dialog.hide();
                frappe.dom.freeze();
                resolve();
            },
            onhide() {
                if (confirmed) return;
                delete frm.doc._qcmc_actual_posting;
                frm.selected_workflow_action = null;
                reject(new Error('Delivery posting cancelled'));
            },
        });
        // Native workflow freezes the screen before invoking this handler.
        frappe.dom.unfreeze();
        dialog.show();
    });
}

// Customer returns keep commercial quantities bulk; storage is a separate plan.
function configure_delivery_note_return_allocation(frm) {
    const is_return = !!frm.doc.is_return;
    frm.set_df_property('custom_apply_putaway_rule', 'hidden', is_return ? 0 : 1);
    frm.set_df_property('custom_apply_putaway_rule', 'read_only', frm.doc.docstatus === 0 ? 0 : 1);
    frm.set_df_property('custom_storage_allocation_section', 'hidden',
        frm.is_new() || !is_return || !frm.doc.custom_storage_allocation_enabled || !frm.doc.custom_apply_putaway_rule ? 1 : 0);
    for (const table of ['items', 'packed_items']) {
        const grid = frm.fields_dict[table]?.grid;
        if (!grid) continue;
        grid._qcmc_return_storage_hidden ||= {};
        for (const df of grid.docfields || []) {
            if (df.options !== 'Storage Location') continue;
            if (!(df.fieldname in grid._qcmc_return_storage_hidden)) {
                grid._qcmc_return_storage_hidden[df.fieldname] = df.hidden || 0;
            }
            grid.update_docfield_property(df.fieldname, 'hidden', is_return ? 1 : grid._qcmc_return_storage_hidden[df.fieldname]);
        }
    }
    frm.refresh_field('custom_storage_allocation');
}

frappe.ui.form.on('Delivery Note', {
    refresh(frm) {
        configure_delivery_note_return_allocation(frm);
        frappe.require("/assets/qcmc_logic/js/picking_status_form.js", () => {
            qcmc_logic.picking_status.refresh(frm);
        });
        qcmc_delivery_pick_list.add_action(frm);
        qcmc_delivery_pick_list.watch_action_menu(frm);
        qcmc_delivery_pick_list.refresh_stage(frm);
    },
    onload_post_render(frm) {
        qcmc_delivery_pick_list.add_action(frm);
        qcmc_delivery_pick_list.refresh_stage(frm);
    },
    async before_workflow_action(frm) {
        if (frm.selected_workflow_action === "Tag To Active") {
            delete frm.doc._qcmc_actual_posting;
            await qcmc_confirm_actual_posting(frm);
            return;
        }
        // Required picking is still enforced by the server before final submission.
    },
    is_return: configure_delivery_note_return_allocation,
    custom_apply_putaway_rule: configure_delivery_note_return_allocation,
    after_save: configure_delivery_note_return_allocation,
});

const qcmc_delivery_pick_list = {
    apply_stage(frm) {
        if (frm.doc.is_return || frm.doc.docstatus !== 0) return;
        const stage = frm.__qcmc_delivery_pick_stage || "loading";
        const $actions = frm.page?.actions;
        if (!$actions?.length) return;
        const shown = {
            "Create Pick List": stage === "pick",
            // Activation is the final workflow step, never an initial draft action.
            "Tag To Active": (frm.doc.workflow_state === "To Deliver and Bill" || (frm.doc.workflow_state === "Draft" && (frappe.user_roles || []).includes("Provincial Stock User"))) && !frm.is_dirty(),
        };
        $actions.find("li > a.dropdown-item").each(function() {
            const $link = $(this);
            const label = $link.find(".menu-item-label").first().text().trim();
            if (Object.prototype.hasOwnProperty.call(shown, label)) {
                $link.closest("li").toggle(shown[label]);
            }
        });
    },
    async refresh_stage(frm) {
        if (frm.doc.is_return || frm.doc.docstatus !== 0) return;
        const token = (frm.__qcmc_delivery_stage_token || 0) + 1;
        frm.__qcmc_delivery_stage_token = token;
        frm.__qcmc_delivery_pick_stage = "loading";
        this.apply_stage(frm);
        if (frm.is_new() || frm.is_dirty()) return;
        const name = frm.doc.name;
        try {
            const result = await frappe.xcall(
                "qcmc_logic.delivery_note_pick_list.get_delivery_note_action_state",
                {delivery_note: name});
            if (frm.doc.name !== name || token !== frm.__qcmc_delivery_stage_token) return;
            frm.__qcmc_delivery_pick_stage = result?.managed ? result.stage : "unmanaged";
        } catch (error) {
            console.warn("Delivery Note picking state lookup failed", error);
            frm.__qcmc_delivery_pick_stage = "loading";
        }
        this.apply_stage(frm);
    },
    watch_action_menu(frm) {
        // Frappe Toolbar.clear_actions_menu() runs when a document becomes dirty.
        // Re-register after that event so the action stays available (the click
        // handler still requires saving the document before creating a Pick List).
        if (frm.__qcmc_pick_menu_watched) return;
        frm.__qcmc_pick_menu_watched = true;
        const actionsNode = frm.page?.actions?.[0];
        if (actionsNode && !frm.__qcmc_delivery_stage_observer) {
            const observer = new MutationObserver(() => qcmc_delivery_pick_list.apply_stage(frm));
            observer.observe(actionsNode, {childList: true, subtree: true});
            frm.__qcmc_delivery_stage_observer = observer;
        }
        $(frm.wrapper).on("dirty.qcmc_pick_menu", () => {
            setTimeout(() => {
                qcmc_delivery_pick_list.add_action(frm);
                qcmc_delivery_pick_list.apply_stage(frm);
            }, 0);
        });
        // When entering a Delivery Note from List View, the form's toolbar
        // finishes rendering asynchronously. Register again after rendering
        // and outstanding loads, not only during the first form refresh.
        $(frm.wrapper).on("render_complete.qcmc_pick_menu", () => {
            frappe.after_ajax(() => {
                if (frm.doctype === "Delivery Note") {
                    qcmc_delivery_pick_list.add_action(frm);
                    qcmc_delivery_pick_list.refresh_stage(frm);
                }
            });
        });
    },
    add_action(frm) {
        if (frm.is_new() || frm.doc.docstatus !== 0 || frm.doc.is_return) return;
        if (!(frm.doc.items || []).some(row => flt(row.qty) > 0)) return;
        // Only the built-in black Actions menu: never add a second Actions group.
        frm.page.add_action_item(__("Create Pick List"), async () => {
            if (frm.is_dirty()) {
                frappe.msgprint(__("Save the Delivery Note before creating its Pick List."));
                return;
            }
            const result = await frappe.xcall(
                "qcmc_logic.delivery_note_pick_list.create_pick_list_from_delivery_note",
                {delivery_note: frm.doc.name}
            );
            if (result?.name) frappe.set_route("Form", "Pick List", result.name);
        });
    },
};

