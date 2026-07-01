frappe.ui.form.on("Payroll Entry", {
	refresh(frm) {
		add_batch_overtime_entry_button(frm);
		add_batch_other_adjustment_entry_button(frm);
		add_employer_contribution_journal_entry_button(frm);
		move_salary_slips_action_to_create_menu(frm);
	}
});

function move_salary_slips_action_to_create_menu(frm) {
	if (!frm.doc.name || frm.is_new()) return;

	setTimeout(function() {
		const label = __("Create Salary Slips");
		const can_create_salary_slips =
			(frm.doc.employees || []).length &&
			!frappe.model.has_workflow(frm.doctype) &&
			!cint(frm.doc.salary_slips_created) &&
			frm.doc.docstatus === 0 &&
			!["Create", "Submit"].includes(frm.doc.overtime_step);

		const can_retry_salary_slips =
			frm.doc.docstatus === 1 &&
			!cint(frm.doc.salary_slips_created) &&
			frm.doc.status === "Failed";

		if (!can_create_salary_slips && !can_retry_salary_slips) return;

		frm.page.clear_primary_action();
		frm.remove_custom_button(label);
		frm.remove_custom_button(label, __("Create"));
		hide_page_button(frm, label);

		frm.add_custom_button(label, function() {
			if (can_create_salary_slips) {
				frm.save("Submit").then(function() {
					frm.page.clear_primary_action();
					frm.refresh();
				});
				return;
			}

			frm.trigger("create_salary_slip");
		}, __("Create"));
	}, 200);
}

function hide_page_button(frm, label) {
	const normalized_label = strip_button_text(label);
	$(frm.page.wrapper).find("button").each(function() {
		const $button = $(this);
		if ($button.closest(".dropdown-menu").length) return;
		if (strip_button_text($button.text()) === normalized_label) {
			$button.addClass("hidden").hide();
		}
	});
}

function strip_button_text(value) {
	return String(value || "").replace(/\s+/g, " ").trim();
}

function add_batch_overtime_entry_button(frm) {
	if (!frm.doc.name || frm.is_new()) return;

	frm.add_custom_button(__("Batch Overtime Entry"), function() {
		open_batch_overtime_entry(frm);
	}, __("Create"));
}

function open_batch_overtime_entry(frm) {
	frappe.db.get_list("Batch Overtime Entry", {
		filters: { payroll_entry: frm.doc.name, docstatus: ["!=", 2] },
		fields: ["name"],
		limit: 1
	}).then(function(rows) {
		if (rows && rows.length) {
			frappe.set_route("Form", "Batch Overtime Entry", rows[0].name);
			return;
		}

		frappe.model.with_doctype("Batch Overtime Entry", function() {
			const doc = frappe.model.get_new_doc("Batch Overtime Entry");
			doc.payroll_entry = frm.doc.name;
			doc.company = frm.doc.company;
			doc.from_date = frm.doc.start_date;
			doc.to_date = frm.doc.end_date;
			doc.department = frm.doc.department;
			doc.branch = frm.doc.branch;
			doc.custom_payroll_type = frm.doc.payroll_frequency;
			frappe.set_route("Form", "Batch Overtime Entry", doc.name);
		});
	});
}

function add_batch_other_adjustment_entry_button(frm) {
	if (!frm.doc.name || frm.is_new()) return;

	frm.add_custom_button(__("Batch Other Adjustment"), function() {
		open_batch_other_adjustment_entry(frm);
	}, __("Create"));
}

function open_batch_other_adjustment_entry(frm) {
	frappe.db.get_list("Batch Other Adjustment Entry", {
		filters: { payroll_entry: frm.doc.name, docstatus: ["!=", 2] },
		fields: ["name"],
		limit: 1
	}).then(function(rows) {
		if (rows && rows.length) {
			frappe.set_route("Form", "Batch Other Adjustment Entry", rows[0].name);
			return;
		}

		frappe.model.with_doctype("Batch Other Adjustment Entry", function() {
			const doc = frappe.model.get_new_doc("Batch Other Adjustment Entry");
			doc.payroll_entry = frm.doc.name;
			doc.company = frm.doc.company;
			doc.from_date = frm.doc.start_date;
			doc.to_date = frm.doc.end_date;
			doc.payroll_date = frm.doc.end_date || frm.doc.posting_date;
			doc.department = frm.doc.department;
			doc.branch = frm.doc.branch;
			doc.custom_payroll_type = frm.doc.payroll_frequency;
			frappe.set_route("Form", "Batch Other Adjustment Entry", doc.name);
		});
	});
}

function add_employer_contribution_journal_entry_button(frm) {
	if (!frm.doc.name || frm.is_new() || frm.doc.docstatus !== 1) return;

	frm.add_custom_button(__("Employer Contribution JE"), function() {
		create_employer_contribution_journal_entry(frm);
	}, __("Create"));
}

function create_employer_contribution_journal_entry(frm) {
	frappe.call({
		method: "xsi_payroll.xsi_payroll.services.employer_contribution.create_employer_contribution_journal_entry",
		args: {
			payroll_entry: frm.doc.name
		},
		freeze: true,
		freeze_message: __("Creating Employer Contribution JE..."),
		callback: function(r) {
			if (!r.message || !r.message.journal_entry) return;

			if (r.message.created) {
				frappe.show_alert({
					message: __("Employer Contribution JE created"),
					indicator: "green"
				});
			}

			frappe.set_route("Form", "Journal Entry", r.message.journal_entry);
		}
	});
}
