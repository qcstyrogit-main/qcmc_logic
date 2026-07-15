frappe.ui.form.on("Bulk HMO Enrollment Renewal", {
	setup(frm) {
		frm.set_query("old_hmo_rate_plan", () => ({
			filters: { is_active: 1 },
		}));
		frm.set_query("new_hmo_rate_plan", () => ({
			filters: { is_active: 1 },
		}));
	},

	refresh(frm) {
		frm.add_custom_button(__("Fetch Enrollments"), () => fetch_hmo_enrollments(frm));
		frm.add_custom_button(__("Create Renewals"), () => create_hmo_renewals(frm));
	},

	new_hmo_rate_plan(frm) {
		if (!frm.doc.new_hmo_rate_plan) return;
		frappe.db.get_doc("HMO Rate Plan", frm.doc.new_hmo_rate_plan).then((plan) => {
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
		});
	},
});

function fetch_hmo_enrollments(frm) {
	const run_fetch = () => {
		frappe.call({
			method: "qcmc_logic.api.hmo_renewal.fetch_enrollments",
			args: { renewal_name: frm.doc.name },
			freeze: true,
			freeze_message: __("Fetching HMO enrollments..."),
			callback(r) {
				show_hmo_renewal_summary(r.message, __("Enrollments Fetched"));
				frm.reload_doc();
			},
		});
	};

	if (frm.is_dirty() || frm.is_new()) {
		frm.save().then(run_fetch);
		return;
	}

	run_fetch();
}

function create_hmo_renewals(frm) {
	const run_create = () => {
		frappe.confirm(
			__("Create new Employee HMO Enrollment records for all Ready rows?"),
			() => {
				frappe.call({
					method: "qcmc_logic.api.hmo_renewal.create_renewals",
					args: { renewal_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Creating HMO renewals..."),
					callback(r) {
						show_hmo_renewal_summary(r.message, __("Renewals Created"));
						frm.reload_doc();
					},
				});
			}
		);
	};

	if (frm.is_dirty() || frm.is_new()) {
		frm.save().then(run_create);
		return;
	}

	run_create();
}

function show_hmo_renewal_summary(summary, title) {
	if (!summary) return;
	frappe.msgprint({
		title,
		indicator: summary.error_rows ? "orange" : "green",
		message: __(
			"Total: {0}<br>Created: {1}<br>Skipped: {2}<br>Errors: {3}",
			[
				summary.total_enrollments || 0,
				summary.created_enrollments || 0,
				summary.skipped_rows || 0,
				summary.error_rows || 0,
			]
		),
	});
}
