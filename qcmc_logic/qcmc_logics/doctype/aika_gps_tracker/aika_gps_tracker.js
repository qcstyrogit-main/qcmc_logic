frappe.ui.form.on("AIKA GPS Tracker", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Link AIKA Vehicles"), () => {
				frappe.call({
					method: "qcmc_logic.integrations.aika_gps.link_account_vehicles",
					args: { tracker: frm.doc.name },
					freeze: true,
					freeze_message: __("Matching AIKA devices to ERPNext Vehicles..."),
					callback: (r) => frappe.msgprint(__("Linked {0} Vehicle(s): {1}", [r.message.count, (r.message.linked || []).join(", ") || __("none")]))
				});
			});
			frm.add_custom_button(__("Fetch Position Now"), () => {
				frappe.call({
					method: "qcmc_logic.integrations.aika_gps.enqueue_fetch",
					args: { tracker: frm.doc.name },
					freeze: true,
					freeze_message: __("Queueing GPS synchronization..."),
					callback: () => {
						frappe.show_alert({ message: __("GPS synchronization queued."), indicator: "blue" });
						setTimeout(() => frm.reload_doc(), 3000);
					}
				});
			}).addClass("btn-primary");
		}
	}
});
