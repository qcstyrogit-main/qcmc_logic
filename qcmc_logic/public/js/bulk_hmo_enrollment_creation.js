frappe.ui.form.on("Bulk HMO Enrollment Creation", {
	setup(frm) {
		frm.set_query("hmo_rate_plan", () => ({
			filters: { is_active: 1 },
		}));
	},

	refresh(frm) {
		load_hmo_plan_rates(frm);
		setup_advanced_employee_filters(frm);
		lock_details_grid(frm);
		frm.add_custom_button(__("Fetch Employees"), () => fetch_hmo_employees(frm));
		frm.add_custom_button(__("Create Enrollments"), () => create_hmo_enrollments(frm));
		frm.add_custom_button(__("Assign Employee HMO Rate"), () => assign_employee_hmo_rate(frm), __("Update"));
	},

	before_save(frm) {
		sync_advanced_employee_filters(frm);
	},

	hmo_rate_plan(frm) {
		load_hmo_plan_rates(frm, true);
	},
});

frappe.ui.form.on("Bulk HMO Enrollment Creation Detail", {
	details_add(frm) {
		load_hmo_plan_rates(frm);
	},

	employee_hmo_rate(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.employee_hmo_rate && ["Needs Rate", "Error", ""].includes(row.status || "")) {
			frappe.model.set_value(cdt, cdn, "status", "Ready");
			frappe.model.set_value(cdt, cdn, "message", "");
		}
	},
});

function load_hmo_plan_rates(frm, clear_invalid = false) {
	if (!frm.doc.hmo_rate_plan) {
		set_employee_rate_options(frm, []);
		return;
	}

	frappe.db.get_doc("HMO Rate Plan", frm.doc.hmo_rate_plan).then((plan) => {
		const values = {};
		if (plan.company && !frm.doc.company) values.company = plan.company;
		if (plan.effective_from && !frm.doc.effective_from) values.effective_from = plan.effective_from;
		if (plan.effective_to && !frm.doc.effective_to) values.effective_to = plan.effective_to;
		if (Object.keys(values).length) frm.set_value(values);

		frm._hmo_employee_rates = (plan.employee_rates || [])
			.filter((row) => cint(row.is_active))
			.map((row) => `${row.level}-${flt(row.mbl)}`);

		set_employee_rate_options(frm, frm._hmo_employee_rates);
	});
}

function set_employee_rate_options(frm, rows) {
	const options = ["", ...rows].join("\n");
	const grid = frm.get_field("details") && frm.get_field("details").grid;
	if (!grid) return;
	const row_field = grid.get_field("employee_hmo_rate");
	if (!row_field) return;
	row_field.df.options = options;
	lock_details_grid(frm);
	grid.refresh();
}

function lock_details_grid(frm) {
	const grid = frm.get_field("details") && frm.get_field("details").grid;
	if (!grid) return;

	grid.cannot_add_rows = true;
	grid.df.cannot_add_rows = true;
	grid.df.cannot_delete_rows = true;

	const hide_row_controls = () => {
		grid.wrapper
			.find(
				".grid-add-row, .grid-add-multiple-rows, .grid-remove-rows, .grid-remove-all-rows, .grid-duplicate-rows, .grid-insert-row, .grid-insert-row-below, .grid-duplicate-row, .grid-append-row"
			)
			.addClass("hidden")
			.hide();
	};

	hide_row_controls();
	setTimeout(hide_row_controls, 100);
}

function fetch_hmo_employees(frm) {
	const run_fetch = () => {
		frappe.call({
			method: "qcmc_logic.api.hmo_creation.fetch_employees",
			args: { creation_name: frm.doc.name },
			freeze: true,
			freeze_message: __("Fetching employees..."),
			callback(r) {
				show_hmo_creation_summary(r.message, __("Employees Fetched"));
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

function create_hmo_enrollments(frm) {
	const run_create = () => {
		const grid = frm.get_field("details") && frm.get_field("details").grid;
		const selected_rows = grid ? grid.get_selected_children() : [];
		const selected_row_names = selected_rows.map((row) => row.name);
		const message = selected_row_names.length
			? __("Create Employee HMO Enrollment records for the {0} selected row(s)?", [selected_row_names.length])
			: __("No rows selected. Create Employee HMO Enrollment records for all Ready rows?");

		frappe.confirm(
			message,
			() => {
				frappe.call({
					method: "qcmc_logic.api.hmo_creation.create_enrollments",
					args: {
						creation_name: frm.doc.name,
						selected_rows: JSON.stringify(selected_row_names),
					},
					freeze: true,
					freeze_message: __("Creating HMO enrollments..."),
					callback(r) {
						show_hmo_creation_summary(r.message, __("Enrollments Created"));
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

function assign_employee_hmo_rate(frm) {
	const grid = frm.get_field("details") && frm.get_field("details").grid;
	if (!grid) return;

	const selected_rows = grid.get_selected_children();
	if (!selected_rows.length) {
		frappe.msgprint({
			title: __("No Rows Selected"),
			indicator: "orange",
			message: __("Please tick employee rows first, then assign the HMO rate."),
		});
		return;
	}

	const rates = frm._hmo_employee_rates || [];
	if (!rates.length) {
		frappe.msgprint({
			title: __("No Rates Found"),
			indicator: "orange",
			message: __("Please select an HMO Rate Plan first."),
		});
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Assign Employee HMO Rate"),
		fields: [
			{
				fieldname: "employee_hmo_rate",
				label: __("Employee HMO Rate"),
				fieldtype: "Select",
				options: rates.join("\n"),
				reqd: 1,
			},
		],
		primary_action_label: __("Update"),
		primary_action(values) {
			selected_rows.forEach((row) => {
				if (row.status === "Created") return;
				frappe.model.set_value(row.doctype, row.name, "employee_hmo_rate", values.employee_hmo_rate);
				frappe.model.set_value(row.doctype, row.name, "status", "Ready");
				frappe.model.set_value(row.doctype, row.name, "message", "");
			});
			dialog.hide();
			frm.refresh_field("details");
		},
	});
	dialog.show();
}

function setup_advanced_employee_filters(frm) {
	const field = frm.get_field("advanced_filters_html");
	if (!field || !field.$wrapper || frm._hmo_filter_group) return;

	field.$wrapper.empty();
	frappe.model.with_doctype("Employee", () => {
		frm._hmo_filter_group = new frappe.ui.FilterGroup({
			parent: field.$wrapper,
			doctype: "Employee",
			on_change: () => sync_advanced_employee_filters(frm),
		});

		const filters = parse_advanced_employee_filters(frm.doc.advanced_filters);
		if (filters.length) {
			frm._hmo_filter_group.add_filters_to_filter_group(filters);
		}
	});
}

function sync_advanced_employee_filters(frm) {
	if (!frm._hmo_filter_group) return;

	const filters = frm._hmo_filter_group.get_filters();
	const value = JSON.stringify(filters || []);
	if ((frm.doc.advanced_filters || "[]") !== value) {
		frm.set_value("advanced_filters", value);
	}
}

function parse_advanced_employee_filters(value) {
	if (!value) return [];
	try {
		return JSON.parse(value) || [];
	} catch (e) {
		return [];
	}
}

function show_hmo_creation_summary(summary, title) {
	if (!summary) return;
	frappe.msgprint({
		title,
		indicator: summary.error_rows ? "orange" : "green",
		message: __(
			"Total: {0}<br>Created: {1}<br>Skipped: {2}<br>Errors: {3}",
			[
				summary.total_employees || 0,
				summary.created_enrollments || 0,
				summary.skipped_rows || 0,
				summary.error_rows || 0,
			]
		),
	});
}
