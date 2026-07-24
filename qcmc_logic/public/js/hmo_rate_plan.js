frappe.ui.form.on("HMO Rate Plan", {
	refresh(frm) {
		recalculate_all_hmo_rate_rows(frm);
		configure_external_member_rates(frm);
		setTimeout(() => configure_external_member_rates(frm), 250);
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

frappe.ui.form.on("HMO External Member", {
	external_members_add(frm) {
		configure_external_member_rates(frm);
	},

	member_type(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.member_type === "Principal") {
			frappe.model.set_value(cdt, cdn, "principal_name", "");
			frappe.model.set_value(cdt, cdn, "relationship", "");
		} else {
			frappe.model.set_value(cdt, cdn, "level", "");
		}
	},

	rate_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.rate_code) return;
		const separator = row.rate_code.lastIndexOf("-");
		const rate_group = row.rate_code.slice(0, separator);
		const mbl = flt(row.rate_code.slice(separator + 1));
		frappe.model.set_value(cdt, cdn, "mbl", mbl);
		if (row.member_type === "Principal") {
			frappe.model.set_value(cdt, cdn, "level", rate_group);
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

function configure_external_member_rates(frm) {
	const grid = frm.get_field("external_members")?.grid;
	if (!grid) return;
	const principal_rates = (frm.doc.employee_rates || [])
		.map((row) => `${row.level}-${cint(row.mbl)}`);
	const dependent_rates = (frm.doc.dependent_rates || [])
		.map((row) => `Dependent-${cint(row.mbl)}`);
	const options = ["", ...new Set([...principal_rates, ...dependent_rates])].join("\n");
	grid.update_docfield_property("rate_code", "options", options);
	const rate_field = frappe.meta.get_docfield("HMO External Member", "rate_code", frm.doc.name);
	if (rate_field) rate_field.options = options;
	grid.refresh();
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
