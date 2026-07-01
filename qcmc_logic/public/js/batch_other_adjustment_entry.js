frappe.ui.form.on("Batch Other Adjustment Entry", {
	refresh(frm) {
		setup_batch_other_adjustment_form(frm);
		add_batch_other_adjustment_buttons(frm);
		apply_batch_other_adjustment_grid_style(frm);
	},

	payroll_entry(frm) {
		apply_payroll_entry_details(frm);
	},

	salary_component(frm) {
		refresh_batch_other_adjustment_filters(frm);
	},

	amount(frm) {
		refresh_batch_other_adjustment_filters(frm);
	},

	department(frm) {
		refresh_batch_other_adjustment_filters(frm);
	},

	branch(frm) {
		refresh_batch_other_adjustment_filters(frm);
	},

	employment_type(frm) {
		refresh_batch_other_adjustment_filters(frm);
	},

	custom_payroll_type(frm) {
		refresh_batch_other_adjustment_filters(frm);
	}
});

function setup_batch_other_adjustment_form(frm) {
	frm.set_query("payroll_entry", function() {
		return { filters: frm.doc.company ? { company: frm.doc.company } : {} };
	});
	frm.set_query("department", function() {
		return { filters: frm.doc.company ? { company: frm.doc.company } : {} };
	});
	frm.set_query("salary_component", function() {
		return {
			filters: {
				disabled: 0,
				type: ["in", ["Earning", "Deduction"]]
			}
		};
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
		["company", "start_date", "end_date", "department", "branch", "payroll_frequency", "posting_date"],
		function(values) {
			if (!values) return;

			const updates = {
				company: values.company,
				from_date: values.start_date,
				to_date: values.end_date,
				payroll_date: values.end_date || values.posting_date,
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

function refresh_batch_other_adjustment_filters(frm) {
	if ((frm.doc.details || []).length) {
		frappe.show_alert({
			message: __("Filters changed. Click Fetch Employees again to refresh the rows."),
			indicator: "orange"
		});
	}
}

function add_batch_other_adjustment_buttons(frm) {
	frm.remove_custom_button(__("Fetch Employees"));
	frm.remove_custom_button(__("Create Additional Salary"));

	if (frm.doc.docstatus !== 0 || frm.doc.status === "Created") return;

	frm.add_custom_button(__("Fetch Employees"), function() {
		fetch_batch_other_adjustment_employees(frm);
	}).addClass("btn-primary");

	if ((frm.doc.details || []).length) {
		frm.add_custom_button(__("Create Additional Salary"), function() {
			create_batch_other_adjustment_records(frm);
		});
	}
}

function fetch_batch_other_adjustment_employees(frm) {
	if (!frm.doc.company || !frm.doc.from_date || !frm.doc.to_date || !frm.doc.payroll_date) {
		frappe.msgprint({
			message: __("Please select Company, From Date, To Date, and Payroll Date."),
			indicator: "orange"
		});
		return;
	}
	if (!frm.doc.salary_component || !frm.doc.amount) {
		frappe.msgprint({
			message: __("Please select Salary Component and Default Amount."),
			indicator: "orange"
		});
		return;
	}

	frappe.call({
		method: "qcmc_logic.api.batch_other_adjustment.fetch_employees",
		freeze: true,
		freeze_message: __("Fetching employees..."),
		args: {
			company: frm.doc.company,
			from_date: frm.doc.from_date,
			to_date: frm.doc.to_date,
			payroll_date: frm.doc.payroll_date,
			salary_component: frm.doc.salary_component,
			amount: frm.doc.amount,
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
			frm.set_value("total_amount", result.total_amount || 0);
			frm.set_value("created_records", 0);
			frm.set_value("skipped_rows", 0);
			frm.set_value("status", (result.rows || []).length ? "Fetched" : "Draft");
			frm.refresh_field("details");

			frappe.show_alert({
				message: __("{0} employee(s) fetched.", [result.total_employees || 0]),
				indicator: result.total_employees ? "green" : "orange"
			});
		}
	});
}

function create_batch_other_adjustment_records(frm) {
	const rows = (frm.doc.details || []).filter(row => row.selected && !row.additional_salary);
	if (!rows.length) {
		frappe.msgprint({
			message: __("No selected employee rows are ready to create."),
			indicator: "orange"
		});
		return;
	}

	frappe.confirm(
		__("Create submitted Additional Salary records for {0} selected employee(s)?", [rows.length]),
		function() {
			if (frm.is_dirty()) {
				frm.save().then(() => call_create_batch_other_adjustment_records(frm));
			} else {
				call_create_batch_other_adjustment_records(frm);
			}
		}
	);
}

function call_create_batch_other_adjustment_records(frm) {
	frappe.call({
		method: "qcmc_logic.api.batch_other_adjustment.create_additional_salaries",
		freeze: true,
		freeze_message: __("Creating Additional Salary records..."),
		args: { batch_name: frm.doc.name },
		callback(r) {
			const result = r.message || {};
			frappe.msgprint({
				title: __("Done"),
				message: __("{0} Additional Salary record(s) created. {1} row(s) skipped or failed.", [
					result.created_records || 0,
					result.skipped_rows || 0
				]),
				indicator: result.created_records ? "green" : "orange"
			});
			frm.reload_doc();
		}
	});
}

function apply_batch_other_adjustment_grid_style(frm) {
	if (!frm.fields_dict.details || !frm.fields_dict.details.grid) return;

	if (!document.getElementById("batch-other-adjustment-entry-style")) {
		$("<style id='batch-other-adjustment-entry-style'>" +
			".frappe-control[data-fieldname='details'] .grid-body{max-height:520px;overflow:auto;}" +
			".frappe-control[data-fieldname='details'] .grid-heading-row{position:sticky;top:0;z-index:2;background:#f8fafc;}" +
			".frappe-control[data-fieldname='details'] .grid-row > .row .col{white-space:nowrap;overflow:visible;text-overflow:clip;}" +
			".frappe-control[data-fieldname='details'] .grid-static-col{min-height:34px;}" +
		"</style>").appendTo("head");
	}
}
