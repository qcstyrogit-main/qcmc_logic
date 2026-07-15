frappe.ui.form.on("Employee HMO Enrollment", {
	setup(frm) {
		frm.set_query("hmo_rate_plan", () => ({
			filters: { is_active: 1 },
		}));
	},

	refresh(frm) {
		load_hmo_plan_rates(frm);
		if (frm.is_new() && !frm.doc.employee) {
			frm.set_value({
				employee_name: "",
				company: "",
				department: "",
				payroll_type: "",
			});
		}
	},

	employee(frm) {
		if (!frm.doc.employee) {
			frm.set_value({
				employee_name: "",
				company: "",
				department: "",
				payroll_type: "",
			});
			return;
		}

		frappe.db
			.get_value("Employee", frm.doc.employee, [
				"employee_name",
				"company",
				"department",
				"custom_payroll_type",
				"payroll_type",
			])
			.then((r) => {
				const employee = r.message || {};
				frm.set_value({
					employee_name: employee.employee_name || "",
					company: employee.company || "",
					department: employee.department || "",
					payroll_type: employee.custom_payroll_type || employee.payroll_type || "",
				});
			});
	},

	hmo_rate_plan(frm) {
		load_hmo_plan_rates(frm, true);
	},

	employee_hmo_rate(frm) {
		apply_employee_rate(frm);
	},
});

function load_hmo_plan_rates(frm, clear_invalid = false) {
	if (!frm.doc.hmo_rate_plan) {
		set_employee_rate_options(frm, []);
		set_dependent_rate_options(frm, []);
		return;
	}

	frappe.db.get_doc("HMO Rate Plan", frm.doc.hmo_rate_plan).then((plan) => {
		set_plan_dates(frm, plan);

		frm._hmo_employee_rates = (plan.employee_rates || [])
			.filter((row) => cint(row.is_active))
			.map((row) => ({
				key: employee_rate_key(row),
				level: row.level,
				mbl: flt(row.mbl),
				employee_ee_monthly_cutoff: flt(row.ee_share_monthly_cutoff),
				employee_er_monthly_cutoff: flt(row.er_share_monthly_cutoff),
				employee_ee_weekly_cutoff: flt(row.ee_share_weekly_cutoff),
				employee_er_weekly_cutoff: flt(row.er_share_weekly_cutoff),
			}));

		frm._hmo_dependent_rates = (plan.dependent_rates || [])
			.filter((row) => cint(row.is_active))
			.map((row) => ({
				key: dependent_rate_key(row),
				mbl: flt(row.mbl),
				dependent_ee_cutoff: flt(row.ee_share_cutoff),
				dependent_ee_weekly: flt(row.ee_share_weekly),
			}));

		set_employee_rate_options(frm, frm._hmo_employee_rates);
		set_dependent_rate_options(frm, frm._hmo_dependent_rates);

		if (clear_invalid && !find_employee_rate(frm, frm.doc.employee_hmo_rate)) {
			frm.set_value({
				employee_hmo_rate: "",
				level: "",
				mbl: 0,
				employee_ee_monthly_cutoff: 0,
				employee_er_monthly_cutoff: 0,
				employee_ee_weekly_cutoff: 0,
				employee_er_weekly_cutoff: 0,
			});
		} else {
			apply_employee_rate(frm);
		}

		(frm.doc.dependents || []).forEach((row) => {
			if (clear_invalid && !find_dependent_rate(frm, row.dependent_hmo_rate)) {
				frappe.model.set_value(row.doctype, row.name, "dependent_hmo_rate", "");
				frappe.model.set_value(row.doctype, row.name, "mbl", 0);
				frappe.model.set_value(row.doctype, row.name, "dependent_ee_cutoff", 0);
				frappe.model.set_value(row.doctype, row.name, "dependent_ee_weekly", 0);
			} else {
				apply_dependent_rate(frm, row.doctype, row.name);
			}
		});
	});
}

function set_plan_dates(frm, plan) {
	const values = {};
	if (plan.effective_from && !frm.doc.effective_from) {
		values.effective_from = plan.effective_from;
	}
	if (plan.effective_to && !frm.doc.effective_to) {
		values.effective_to = plan.effective_to;
	}
	if (Object.keys(values).length) {
		frm.set_value(values);
	}
}

function set_employee_rate_options(frm, rows) {
	const field = frm.get_field("employee_hmo_rate");
	if (!field) return;
	field.df.options = ["", ...rows.map((row) => row.key)].join("\n");
	frm.refresh_field("employee_hmo_rate");
}

function set_dependent_rate_options(frm, rows) {
	const grid = frm.get_field("dependents") && frm.get_field("dependents").grid;
	if (!grid) return;
	const field = grid.get_field("dependent_hmo_rate");
	if (!field) return;
	field.df.options = ["", ...rows.map((row) => row.key)].join("\n");
	grid.refresh();
}

function apply_employee_rate(frm) {
	const rate = find_employee_rate(frm, frm.doc.employee_hmo_rate);
	if (!rate) {
		frm.set_value({
			level: "",
			mbl: 0,
			employee_ee_monthly_cutoff: 0,
			employee_er_monthly_cutoff: 0,
			employee_ee_weekly_cutoff: 0,
			employee_er_weekly_cutoff: 0,
		});
		return;
	}

	frm.set_value({
		level: rate.level,
		mbl: rate.mbl,
		employee_ee_monthly_cutoff: rate.employee_ee_monthly_cutoff,
		employee_er_monthly_cutoff: rate.employee_er_monthly_cutoff,
		employee_ee_weekly_cutoff: rate.employee_ee_weekly_cutoff,
		employee_er_weekly_cutoff: rate.employee_er_weekly_cutoff,
	});
}

function apply_dependent_rate(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	const rate = find_dependent_rate(frm, row.dependent_hmo_rate);
	frappe.model.set_value(cdt, cdn, "mbl", rate ? rate.mbl : 0);
	frappe.model.set_value(cdt, cdn, "dependent_ee_cutoff", rate ? rate.dependent_ee_cutoff : 0);
	frappe.model.set_value(cdt, cdn, "dependent_ee_weekly", rate ? rate.dependent_ee_weekly : 0);
}

function find_employee_rate(frm, key) {
	return (frm._hmo_employee_rates || []).find((row) => row.key === key);
}

function find_dependent_rate(frm, key) {
	return (frm._hmo_dependent_rates || []).find((row) => row.key === key);
}

function employee_rate_key(row) {
	return `${row.level}-${flt(row.mbl)}`;
}

function dependent_rate_key(row) {
	return `Dependent-${flt(row.mbl)}`;
}

frappe.ui.form.on("Employee HMO Dependent", {
	dependents_add(frm, cdt, cdn) {
		load_hmo_plan_rates(frm);
		frappe.model.set_value(cdt, cdn, "is_active", 1);
	},

	form_render(frm) {
		load_hmo_plan_rates(frm);
	},

	dependent_hmo_rate(frm, cdt, cdn) {
		apply_dependent_rate(frm, cdt, cdn);
	},
});
