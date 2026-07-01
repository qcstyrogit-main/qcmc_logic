frappe.ui.form.on("Batch Overtime Entry", {
	refresh(frm) {
		setup_batch_overtime_form(frm);
		add_batch_overtime_buttons(frm);
		apply_batch_overtime_grid_style(frm);
	},

	company(frm) {
		set_department_query(frm);
	},

	payroll_entry(frm) {
		apply_payroll_entry_details(frm);
	},

	department(frm) {
		refresh_batch_filters(frm);
	},

	branch(frm) {
		refresh_batch_filters(frm);
	},

	employment_type(frm) {
		refresh_batch_filters(frm);
	},

	custom_payroll_type(frm) {
		refresh_batch_filters(frm);
	}
});

function setup_batch_overtime_form(frm) {
	set_department_query(frm);
	frm.set_query("payroll_entry", function() {
		return {
			filters: frm.doc.company ? { company: frm.doc.company } : {}
		};
	});
	frm.set_query("branch", function() {
		return {};
	});

	if (!frm.doc.status) {
		frm.set_value("status", "Draft");
	}
}

function apply_payroll_entry_details(frm) {
	if (!frm.doc.payroll_entry) return;

	frappe.db.get_value(
		"Payroll Entry",
		frm.doc.payroll_entry,
		["company", "start_date", "end_date", "department", "branch", "payroll_frequency"],
		function(values) {
			if (!values) return;

			const updates = {
				company: values.company,
				from_date: values.start_date,
				to_date: values.end_date,
				department: values.department,
				branch: values.branch,
				custom_payroll_type: values.payroll_frequency
			};

			Object.keys(updates).forEach(function(fieldname) {
				if (updates[fieldname]) {
					frm.set_value(fieldname, updates[fieldname]);
				}
			});
		}
	);
}

function set_department_query(frm) {
	frm.set_query("department", function() {
		return { filters: frm.doc.company ? { company: frm.doc.company } : {} };
	});
}

function refresh_batch_filters(frm) {
	if ((frm.doc.details || []).length) {
		frappe.show_alert({
			message: __("Filters changed. Click Fetch OT Employees again to refresh the rows."),
			indicator: "orange"
		});
	}
}

function add_batch_overtime_buttons(frm) {
	frm.remove_custom_button(__("Fetch OT Employees"));
	frm.remove_custom_button(__("Create Overtime Slips"));
	frm.remove_custom_button(__("Sync Payroll Entry Link"));

	if (frm.doc.payroll_entry && (frm.doc.details || []).some(row => row.created_overtime_slip)) {
		frm.add_custom_button(__("Sync Payroll Entry Link"), function() {
			sync_batch_overtime_payroll_entry(frm);
		}, __("Actions"));
	}

	if (frm.doc.docstatus !== 0 || frm.doc.status === "Created") return;

	frm.add_custom_button(__("Fetch OT Employees"), function() {
		fetch_batch_overtime(frm);
	}).addClass("btn-primary");

	if ((frm.doc.details || []).length) {
		frm.add_custom_button(__("Create Overtime Slips"), function() {
			create_batch_overtime_slips(frm);
		});
	}
}

function sync_batch_overtime_payroll_entry(frm) {
	frappe.call({
		method: "qcmc_logic.api.batch_overtime.sync_overtime_slip_payroll_entry",
		args: { batch_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Linking Overtime Slips to Payroll Entry..."),
		callback(r) {
			const result = r.message || {};
			frappe.msgprint({
				title: __("Done"),
				message: __("{0} of {1} Overtime Slip(s) linked to Payroll Entry.", [
					result.updated || 0,
					result.total || 0
				]),
				indicator: "green"
			});
		}
	});
}

function fetch_batch_overtime(frm) {
	if (!frm.doc.company || !frm.doc.from_date || !frm.doc.to_date) {
		frappe.msgprint({
			message: __("Please select Company, From Date, and To Date."),
			indicator: "orange"
		});
		return;
	}

	frappe.call({
		method: "qcmc_logic.api.batch_overtime.fetch_overtime_entries",
		freeze: true,
		freeze_message: __("Fetching overtime attendance..."),
		args: {
			company: frm.doc.company,
			from_date: frm.doc.from_date,
			to_date: frm.doc.to_date,
			department: frm.doc.department,
			branch: frm.doc.branch,
			employment_type: frm.doc.employment_type,
			custom_payroll_type: frm.doc.custom_payroll_type
		},
		callback(r) {
			const result = r.message || {};
			frm.clear_table("details");
			(result.rows || []).forEach(function(item) {
				const row = frm.add_child("details");
				Object.keys(item).forEach(function(key) {
					row[key] = item[key];
				});
			});
			frm.set_value("total_employees", result.total_employees || 0);
			frm.set_value("total_rows", result.total_rows || 0);
			frm.set_value("total_overtime_duration", result.total_overtime_duration || 0);
			frm.set_value("created_slips", 0);
			frm.set_value("skipped_rows", 0);
			frm.set_value("status", (result.rows || []).length ? "Fetched" : "Draft");
			frm.refresh_field("details");

			if (result.total_rows) {
				frappe.show_alert({
					message: __("{0} OT row(s) fetched.", [result.total_rows || 0]),
					indicator: "green"
				});
			} else {
				let message = __(
					"Found {0} employee(s) and {1} submitted Attendance record(s), but no new OT rows are available.",
					[result.candidate_employees || 0, result.submitted_attendance || 0]
				);
				if (result.already_used_attendance) {
					message = __(
						"Found {0} OT Attendance record(s), but all {1} are already linked to active Overtime Slip records.",
						[result.ot_marked_attendance || 0, result.already_used_attendance || 0]
					);
				} else if (!result.ot_marked_attendance) {
					message = __(
						"Found {0} employee(s) and {1} submitted Attendance record(s), but 0 records have both Overtime Type and OT Duration. Please mark overtime on Attendance first.",
						[result.candidate_employees || 0, result.submitted_attendance || 0]
					);
				}
				frappe.msgprint({
					title: __("No OT Rows Found"),
					message: message,
					indicator: "orange"
				});
			}
		}
	});
}

function create_batch_overtime_slips(frm) {
	const rows = (frm.doc.details || []).filter(row => row.selected && !row.created_overtime_slip);
	if (!rows.length) {
		frappe.msgprint({
			message: __("No selected overtime rows are ready to create."),
			indicator: "orange"
		});
		return;
	}

	frappe.confirm(
		__("Create submitted Overtime Slip records for {0} selected row(s)?", [rows.length]),
		function() {
			if (frm.is_dirty()) {
				frm.save().then(() => call_create_slips(frm));
			} else {
				call_create_slips(frm);
			}
		}
	);
}

function call_create_slips(frm) {
	frappe.call({
		method: "qcmc_logic.api.batch_overtime.create_overtime_slips",
		freeze: true,
		freeze_message: __("Creating Overtime Slips..."),
		args: { batch_name: frm.doc.name },
		callback(r) {
			const result = r.message || {};
			frappe.msgprint({
				title: __("Done"),
				message: __("{0} submitted Overtime Slip(s) created. {1} row(s) skipped or failed.", [
					result.created_slips || 0,
					result.skipped_rows || 0
				]),
				indicator: result.created_slips ? "green" : "orange"
			});
			frm.reload_doc();
		}
	});
}

function apply_batch_overtime_grid_style(frm) {
	if (!frm.fields_dict.details || !frm.fields_dict.details.grid) return;

	if (!document.getElementById("batch-overtime-entry-style")) {
		$("<style id='batch-overtime-entry-style'>" +
			".frappe-control[data-fieldname='details'] .grid-body{max-height:520px;overflow:auto;}" +
			".frappe-control[data-fieldname='details'] .grid-heading-row{position:sticky;top:0;z-index:2;background:#f8fafc;}" +
			".frappe-control[data-fieldname='details'] .grid-row > .row .col{white-space:nowrap;overflow:visible;text-overflow:clip;}" +
			".frappe-control[data-fieldname='details'] .grid-static-col{min-height:34px;}" +
		"</style>").appendTo("head");
	}
}
