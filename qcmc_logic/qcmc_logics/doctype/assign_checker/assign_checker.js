frappe.ui.form.on("Assign Checker", {
	employee(frm) {
		if (!frm.doc.employee) return;
		frappe.db.get_value("Employee", frm.doc.employee, "employee_name").then((r) => {
			if (r.message && r.message.employee_name) {
				frm.set_value("checker_name", r.message.employee_name);
			}
		});
	},

	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Generate QR Code"), () => show_checker_qr(frm), __("Actions"));
	},
});

function show_checker_qr(frm) {
	frappe.call({
		method: "qcmc_logic.qcmc_logics.doctype.assign_checker.assign_checker.get_qr_payload",
		args: { name: frm.doc.name },
		callback(r) {
			if (!r.message) return;
			const qr = r.message;
			frappe.call({
				method: "qcmc_logic.api.generate_code.generate_qr",
				args: { item_code: qr.payload },
				callback(image_response) {
					if (!image_response.message) return;
					const dialog = new frappe.ui.Dialog({
						title: __("Checker QR — {0}", [qr.name]),
						fields: [{
							fieldname: "preview",
							fieldtype: "HTML",
							options: `<div class="checker-qr-label" style="text-align:center;padding:20px">
								<img src="${image_response.message}" alt="Checker QR" style="width:240px;height:240px">
								<h3 style="margin:12px 0 4px">${frappe.utils.escape_html(qr.name)}</h3>
								<div>${frappe.utils.escape_html(qr.assign_checker_id)}</div>
							</div>`,
						}],
						primary_action_label: __("Print"),
						primary_action() {
							const content = dialog.$wrapper.find(".checker-qr-label").html();
							const win = window.open("", "_blank");
							win.document.write(`<html><head><title>${frappe.utils.escape_html(qr.assign_checker_id)}</title></head><body style="font-family:Arial;text-align:center">${content}</body></html>`);
							win.document.close();
							win.focus();
							win.print();
						},
					});
					dialog.show();
				},
			});
		},
	});
}
