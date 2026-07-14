frappe.ui.form.on("HMO Rate Plan", {
	refresh(frm) {
		recalculate_all_hmo_rate_rows(frm);
		if (!frm.is_new()) {
			frm.add_custom_button(__("Create Employee Enrollments"), () => {
				frappe.new_doc("Bulk HMO Enrollment Creation", {
					hmo_rate_plan: frm.doc.name,
					company: frm.doc.company,
					effective_from: frm.doc.effective_from,
					effective_to: frm.doc.effective_to,
				});
			});
		}
	},
});

frappe.ui.form.on("HMO Employee Rate Detail", {
	total_fee(frm, cdt, cdn) {
		recalculate_hmo_employee_rate_row(cdt, cdn);
	},
	er_share(frm, cdt, cdn) {
		recalculate_hmo_employee_rate_row(cdt, cdn);
	},
	er_share_weekly_cutoff(frm, cdt, cdn) {
		recalculate_hmo_employee_rate_row(cdt, cdn, true);
	},
	ee_share_weekly_cutoff(frm, cdt, cdn) {
		recalculate_hmo_employee_rate_row(cdt, cdn, true);
	},
});

frappe.ui.form.on("HMO Dependent Rate Detail", {
	ee_share(frm, cdt, cdn) {
		recalculate_hmo_dependent_rate_row(cdt, cdn);
	},
	ee_share_weekly(frm, cdt, cdn) {
		recalculate_hmo_dependent_rate_row(cdt, cdn, true);
	},
});

function recalculate_all_hmo_rate_rows(frm) {
	(frm.doc.employee_rates || []).forEach((row) => {
		recalculate_hmo_employee_rate_row(row.doctype, row.name);
	});
	(frm.doc.dependent_rates || []).forEach((row) => {
		recalculate_hmo_dependent_rate_row(row.doctype, row.name);
	});
}

function recalculate_hmo_employee_rate_row(cdt, cdn, keep_weekly) {
	const row = locals[cdt][cdn];
	const total_fee = flt(row.total_fee);
	const er_share = flt(row.er_share);
	const ee_share = total_fee - er_share;
	const er_share_month = er_share / 3;
	const ee_share_month = ee_share / 3;
	const has_weekly_cutoff = keep_weekly || flt(row.er_share_weekly_cutoff) || flt(row.ee_share_weekly_cutoff);

	frappe.model.set_value(cdt, cdn, {
		ee_share,
		er_share_month,
		ee_share_month,
		premium: er_share_month + ee_share_month,
		er_share_monthly_cutoff: er_share_month / 2,
		ee_share_monthly_cutoff: ee_share_month / 2,
		er_share_weekly_cutoff: has_weekly_cutoff ? er_share_month / 4 : 0,
		ee_share_weekly_cutoff: has_weekly_cutoff ? ee_share_month / 4 : 0,
	});
}

function recalculate_hmo_dependent_rate_row(cdt, cdn, keep_weekly) {
	const row = locals[cdt][cdn];
	const ee_share_monthly = flt(row.ee_share) / 3;
	const has_weekly_cutoff = keep_weekly || flt(row.ee_share_weekly);

	frappe.model.set_value(cdt, cdn, {
		ee_share_monthly,
		ee_share_cutoff: ee_share_monthly / 2,
		ee_share_weekly: has_weekly_cutoff ? ee_share_monthly / 4 : 0,
	});
}
