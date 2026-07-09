frappe.ui.form.on("Payroll Entry", {
	setup(frm) {
		apply_payroll_entry_role_scope(frm);
	},
	refresh(frm) {
		apply_payroll_entry_role_scope(frm);
		ensure_dirty_payroll_entry_save(frm);
		add_batch_other_adjustment_entry_button(frm);
		add_employer_contribution_journal_entry_button(frm);
	},
	company(frm) {
		apply_payroll_entry_role_scope(frm);
	},
	payroll_frequency(frm) {
		apply_payroll_entry_role_scope(frm);
	},
	overtime_step(frm) {
		ensure_dirty_payroll_entry_save(frm);
	}
});

function ensure_dirty_payroll_entry_save(frm) {
	if (frm.doc.docstatus !== 0 || frm.is_new()) return;

	[100, 350, 800].forEach(function(delay) {
		setTimeout(function() {
			show_dirty_payroll_entry_save(frm);
		}, delay);
	});
}

function show_dirty_payroll_entry_save(frm) {
		if (!frm.is_dirty()) return;

		frm.page.set_primary_action(__("Save"), function() {
			frm.save();
		});
}

function apply_payroll_entry_role_scope(frm) {
	const scope = get_payroll_entry_role_scope(frm);
	if (!scope) return;

	setup_payroll_entry_role_queries(frm, scope);
	apply_payroll_entry_defaults(frm, scope);
	apply_payroll_entry_locks(frm, scope);
}

function setup_payroll_entry_role_queries(frm, scope) {
	frm.set_query("company", () => ({
		filters: {
			name: ["in", scope.companies],
		},
	}));

	if (scope.branch_restricted) {
		frm.set_query("branch", () => ({
			filters: {
				name: ["in", scope.branches],
			},
		}));
	}

	frm.set_query("employee", "employees", () => {
		let error_fields = [];
		let mandatory_fields = ["company", "payroll_frequency", "start_date", "end_date"];
		let message = __("Mandatory fields required in {0}", [__(frm.doc.doctype)]);

		mandatory_fields.forEach((field) => {
			if (!frm.doc[field]) {
				error_fields.push(frappe.unscrub(field));
			}
		});

		if (error_fields && error_fields.length) {
			message = message + "<br><br><ul><li>" + error_fields.join("</li><li>") + "</ul>";
			frappe.throw({
				message: message,
				indicator: "red",
				title: __("Missing Fields"),
			});
		}

		return {
			query: "hrms.payroll.doctype.payroll_entry.payroll_entry.employee_query",
			filters: get_payroll_entry_employee_filters(frm, scope),
		};
	});
}

function get_payroll_entry_employee_filters(frm, scope) {
	const filters = frm.events.get_employee_filters(frm);
	if (scope.employment_types.length) {
		filters.employment_type = ["in", scope.employment_types];
	}
	if (scope.branch_restricted && scope.branches.length) {
		filters.branch = ["in", scope.branches];
	}
	return filters;
}

async function apply_payroll_entry_defaults(frm, scope) {
	if (scope.companies.length === 1 && frm.doc.company !== scope.companies[0]) {
		await frm.set_value("company", scope.companies[0]);
	}

	if (scope.payroll_frequencies.length === 1 && frm.doc.payroll_frequency !== scope.payroll_frequencies[0]) {
		await frm.set_value("payroll_frequency", scope.payroll_frequencies[0]);
	}

	if (scope.branch_restricted && scope.branches.length === 1 && frm.doc.branch !== scope.branches[0]) {
		await frm.set_value("branch", scope.branches[0]);
	}

	if (scope.branch_restricted && scope.branches.length > 1 && frm.doc.branch && !scope.branches.includes(frm.doc.branch)) {
		await frm.set_value("branch", "");
	}
}

function apply_payroll_entry_locks(frm, scope) {
	frm.set_df_property("company", "read_only", scope.companies.length === 1 ? 1 : 0);
	frm.set_df_property("payroll_frequency", "read_only", scope.payroll_frequencies.length === 1 ? 1 : 0);
	frm.set_df_property("branch", "read_only", scope.branch_restricted && scope.branches.length === 1 ? 1 : 0);
}

function get_payroll_entry_role_scope(frm) {
	if (frappe.session && frappe.session.user === "Administrator") return null;
	if (!frappe.user || !frappe.user.has_role) return null;

	const rules = get_payroll_entry_role_rules().filter((rule) => frappe.user.has_role(rule.role));
	if (!rules.length) return null;

	const current_payroll_type = get_payroll_entry_payroll_type(frm.doc.payroll_frequency);
	const matching_rules = current_payroll_type
		? rules.filter((rule) => rule.payroll_type === current_payroll_type)
		: rules;
	const effective_rules = matching_rules.length ? matching_rules : rules;
	const branch_restricted = effective_rules.every((rule) => (rule.branches || []).length);

	return {
		companies: unique_payroll_entry_values(effective_rules.map((rule) => rule.company)),
		payroll_frequencies: unique_payroll_entry_values(
			effective_rules.map((rule) => rule.payroll_type === "Weekly" ? "Weekly" : "Bimonthly")
		),
		branches: branch_restricted
			? unique_payroll_entry_values(effective_rules.flatMap((rule) => rule.branches || []))
			: [],
		branch_restricted,
		employment_types: unique_payroll_entry_values(effective_rules.flatMap((rule) => rule.employment_types || [])),
	};
}

function get_payroll_entry_payroll_type(payroll_frequency) {
	if (payroll_frequency === "Weekly") return "Weekly";
	if (["Bimonthly", "Monthly"].includes(payroll_frequency)) return "Monthly";
	return "";
}

function get_payroll_entry_role_rules() {
	const regular = ["Regular", "Probation", "Probationary"];
	const provincial = [
		"Bacolod", "Cebu", "Cagayan De Oro", "Iloilo", "Davao", "Zamboanga",
		"La Union", "Pampanga", "Laguna", "Quezon"
	];

	return [
		{ role: "Monthly QC", company: "QC Styropackaging Corporation", payroll_type: "Monthly", employment_types: regular },
		{ role: "Monthly MC", company: "Multiplast Corporation", payroll_type: "Monthly", employment_types: regular },
		{ role: "Monthly SMB", company: "QC Styropackaging Corporation", payroll_type: "Monthly", branches: ["Guyong", "Sta. Clara"], employment_types: regular },
		{ role: "Monthly VAL", company: "Multiplast Corporation", payroll_type: "Monthly", branches: ["Valenzuela"], employment_types: regular },
		{ role: "MC Prov Merch", company: "Multiplast Corporation", payroll_type: "Monthly", employment_types: ["Provincial Merchandise"] },
		{ role: "Weekly QC EDSA", company: "QC Styropackaging Corporation", payroll_type: "Weekly", branches: ["QC Edsa"], employment_types: regular },
		{ role: "Weekly MC EDSA", company: "Multiplast Corporation", payroll_type: "Weekly", branches: ["QC Edsa"], employment_types: regular },
		{ role: "Weekly QC Agency", company: "QC Styropackaging Corporation", payroll_type: "Weekly", branches: ["QC Edsa"], employment_types: ["Agency"] },
		{ role: "Weekly QC SMB", company: "QC Styropackaging Corporation", payroll_type: "Weekly", branches: ["Guyong", "Sta. Clara"], employment_types: regular },
		{ role: "Weekly MC VAL", company: "Multiplast Corporation", payroll_type: "Weekly", branches: ["Valenzuela"], employment_types: regular },
		{ role: "Weekly QC Prov", company: "QC Styropackaging Corporation", payroll_type: "Weekly", branches: provincial, employment_types: regular },
		{ role: "Weekly MC Prov", company: "Multiplast Corporation", payroll_type: "Weekly", branches: provincial, employment_types: regular },
		{ role: "Weekly MC Prov Agency", company: "Multiplast Corporation", payroll_type: "Weekly", branches: provincial, employment_types: ["Agency"] },
	];
}

function unique_payroll_entry_values(values) {
	return Array.from(new Set((values || []).filter(Boolean)));
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
