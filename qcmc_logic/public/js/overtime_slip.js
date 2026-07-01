frappe.ui.form.on("Overtime Slip", {
	refresh(frm) {
		setTimeout(function() {
			install_qcmc_overtime_fetch_button(frm);
		}, 0);
	}
});

function install_qcmc_overtime_fetch_button(frm) {
	frm.remove_custom_button("Fetch Overtime Details");
	frm.add_custom_button(__("Fetch Overtime Details"), function() {
		fetch_qcmc_overtime_details(frm);
	}).addClass("btn-primary");
}

function fetch_qcmc_overtime_details(frm) {
	frappe.call({
		method: "qcmc_logic.api.overtime_slip.fetch_overtime_details",
		args: {
			employee: frm.doc.employee,
			start_date: frm.doc.start_date,
			end_date: frm.doc.end_date,
			current_name: frm.doc.name
		},
		freeze: true,
		freeze_message: __("Fetching overtime details..."),
		callback(r) {
			const result = r.message || {};
			const rows = result.rows || [];
			if (!rows.length) {
				frappe.msgprint({
					title: __("No OT Records Found"),
					message: __(
						"Found {0} Attendance record(s), but no OT reached the 1 hour minimum after applying the 30-minute rule.",
						[result.records || 0]
					),
					indicator: "orange"
				});
				return;
			}

			frm.clear_table("overtime_details");
			rows.forEach(function(item) {
				const row = frm.add_child("overtime_details");
				row.reference_document = item.reference_document;
				row.date = item.date;
				row.overtime_type = item.overtime_type;
				row.overtime_duration = item.overtime_duration;
				row.standard_working_hours = item.standard_working_hours || 8;
			});

			frm.set_value("total_overtime_duration", result.total_overtime_duration || 0);
			frm.refresh_field("overtime_details");
			frm.refresh_field("total_overtime_duration");

			frappe.msgprint({
				title: __("Done"),
				message: __(
					"{0} OT record(s) fetched. Total: <b>{1} hrs</b>. {2} record(s) below 1 hour were skipped.",
					[rows.length, result.total_overtime_duration || 0, result.skipped_below_minimum || 0]
				),
				indicator: "green"
			});
		}
	});
}
