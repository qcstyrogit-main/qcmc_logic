frappe.ui.form.on("Delivery Note", {
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
