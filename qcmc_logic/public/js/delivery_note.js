frappe.ui.form.on("Delivery Note", {
	before_save(frm) {
		check_delivery_note_warning(frm, "Save");
	},

	before_submit(frm) {
		check_delivery_note_warning(frm, "Submit");
	},
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
