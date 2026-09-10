frappe.ui.form.on("Payment Entry", {
	setup(frm) {
		set_underpayment_breakdown_queries(frm);
		apply_payment_type_role_access(frm);
	},
	refresh(frm) {
		apply_payment_type_role_access(frm);
		refresh_underpayment_breakdown_controls(frm);
		add_intercompany_collection_buttons(frm);
		render_cwt_button(frm);
		render_affiliate_collection_deduction_button(frm);
	},
	references_add(frm) {
		refresh_underpayment_breakdown_controls(frm);
	},
	references_remove(frm) {
		refresh_underpayment_breakdown_controls(frm);
	},
	custom_underpayment_breakdown_add(frm) {
		refresh_underpayment_breakdown_controls(frm);
	},
	custom_underpayment_breakdown_remove(frm) {
		refresh_underpayment_breakdown_controls(frm);
	},
	unallocated_amount(frm) {
		render_affiliate_collection_deduction_button(frm);
	},
	payment_type(frm) {
		enforce_payment_type_role_access(frm);
		render_cwt_button(frm);
		render_affiliate_collection_deduction_button(frm);
	},
	company(frm) {
		render_cwt_button(frm);
		render_affiliate_collection_deduction_button(frm);
	},
});

const PAYMENT_TYPE_OPTIONS = ["Receive", "Pay", "Internal Transfer"];

async function apply_payment_type_role_access(frm) {
	if (frm.qcmc_payment_type_access_loaded) {
		enforce_payment_type_role_access(frm);
		return;
	}

	frm.qcmc_payment_type_access_loaded = true;

	const { message } = await frappe.call({
		method: "qcmc_logic.overrides.payment_entry.get_payment_entry_type_role_access",
	});

	frm.qcmc_payment_type_access = message || {};
	enforce_payment_type_role_access(frm);
}

function enforce_payment_type_role_access(frm) {
	const access = frm.qcmc_payment_type_access || {};
	const allowed = access.enabled && access.allowed_payment_types && access.allowed_payment_types.length
		? access.allowed_payment_types
		: PAYMENT_TYPE_OPTIONS;
	const allowed_series = access.enabled && access.allowed_naming_series && access.allowed_naming_series.length
		? access.allowed_naming_series
		: null;

	frm.set_df_property("payment_type", "options", allowed.join("\n"));
	if (allowed_series) {
		frm.set_df_property("naming_series", "options", allowed_series.join("\n"));
	}

	if (
		frm.doc.docstatus === 0
		&& access.enabled
		&& access.default_payment_type
		&& frm.doc.payment_type !== access.default_payment_type
	) {
		frm.set_value("payment_type", access.default_payment_type);
	}

	if (
		frm.doc.docstatus === 0
		&& access.enabled
		&& access.default_naming_series
		&& frm.doc.naming_series !== access.default_naming_series
	) {
		frm.set_value("naming_series", access.default_naming_series);
	}
}

frappe.ui.form.on("Payment Entry Reference", {
	reference_doctype(frm) {
		refresh_underpayment_breakdown_controls(frm);
	},
	reference_name(frm) {
		refresh_underpayment_breakdown_controls(frm);
	},
	outstanding_amount(frm) {
		refresh_underpayment_breakdown_controls(frm);
	},
	allocated_amount(frm) {
		refresh_underpayment_breakdown_controls(frm);
		render_cwt_button(frm);
	},
});

const CWT_DEDUCTION_DESCRIPTION_PREFIX = "CWT - Sales Invoice: ";

function render_cwt_button(frm) {
	const grid = frm.fields_dict.references && frm.fields_dict.references.grid;
	if (!grid) return;

	const label = __("Add CWT");
	const existing_button = grid.custom_buttons && grid.custom_buttons[label];

	if (
		frm.doc.docstatus !== 0
		|| frm.doc.payment_type !== "Receive"
		|| !frm.doc.company
	) {
		if (existing_button) existing_button.addClass("hidden");
		return;
	}

	grid.add_custom_button(label, () => show_cwt_dialog(frm), "top");
}

function get_cwt_invoice_references(frm, calculation_defaults) {
	const by_invoice = {};

	(frm.doc.references || []).forEach((row) => {
		if (row.reference_doctype !== "Sales Invoice" || !row.reference_name) return;

		const outstanding_amount = flt(row.outstanding_amount, 2);
		const current_allocation = flt(row.allocated_amount, 2);
		if (outstanding_amount <= 0 && current_allocation <= 0) return;

		const allocated_amount = current_allocation > 0
			? current_allocation
			: outstanding_amount;

		by_invoice[row.reference_name] = {
			invoice: row.reference_name,
			reference_row_name: row.name,
			original_amount: flt(row.total_amount, 2),
			outstanding_amount,
			allocated_amount,
			calculated_cwt: calculate_cwt_amount(
				allocated_amount,
				calculation_defaults.cwt_rate,
				calculation_defaults.vat_rate
			),
		};
	});

	return Object.values(by_invoice);
}

function calculate_cwt_amount(allocated_amount, cwt_rate, vat_rate) {
	const vat_divisor = 1 + (flt(vat_rate) / 100);
	return flt((flt(allocated_amount) / vat_divisor) * (flt(cwt_rate) / 100), 2);
}

function get_existing_cwt_deduction_map(frm) {
	const existing = {};

	(frm.doc.deductions || []).forEach((row) => {
		const invoice = row.custom_cwt_sales_invoice || get_cwt_invoice_from_description(row);
		if (!invoice) return;

		existing[invoice] = {
			row,
			amount: flt(row.amount),
			allocated_amount: flt(row.custom_cwt_allocated_amount),
			cwt_rate: flt(row.custom_cwt_rate),
			vat_rate: flt(row.custom_cwt_vat_rate),
		};
	});

	return existing;
}

function get_cwt_invoice_from_description(row) {
	const description = row.description || "";
	if (!description.startsWith(CWT_DEDUCTION_DESCRIPTION_PREFIX)) return null;

	return description.slice(CWT_DEDUCTION_DESCRIPTION_PREFIX.length).trim() || null;
}

function build_cwt_dialog_rows(frm, calculation_defaults) {
	const references = get_cwt_invoice_references(frm, calculation_defaults);
	const existing = get_existing_cwt_deduction_map(frm);
	const preselect_single = references.length === 1;

	return references.map((reference) => {
		const existing_row = existing[reference.invoice];
		const calculation_unchanged = existing_row
			&& flt(existing_row.allocated_amount, 2) === flt(reference.allocated_amount, 2)
			&& flt(existing_row.cwt_rate, 6) === flt(calculation_defaults.cwt_rate, 6)
			&& flt(existing_row.vat_rate, 6) === flt(calculation_defaults.vat_rate, 6);

		return {
			select: preselect_single ? 1 : 0,
			invoice: reference.invoice,
			reference_row_name: reference.reference_row_name,
			original_amount: reference.original_amount,
			outstanding_amount: reference.outstanding_amount,
			allocated_amount: reference.allocated_amount,
			cwt_amount: calculation_unchanged ? existing_row.amount : reference.calculated_cwt,
		};
	});
}

async function show_cwt_dialog(frm) {
	const eligible_references = (frm.doc.references || []).filter((row) => (
		row.reference_doctype === "Sales Invoice"
		&& row.reference_name
		&& (flt(row.outstanding_amount) > 0 || flt(row.allocated_amount) > 0)
	));

	if (!eligible_references.length) {
		frappe.msgprint(__("No eligible Sales Invoice references with an outstanding balance were found."));
		return;
	}

	const calculation_defaults = await frappe.xcall(
		"qcmc_logic.overrides.payment_entry.get_cwt_calculation_defaults",
		{
			company: frm.doc.company,
			customer: frm.doc.party_type === "Customer" ? frm.doc.party : null,
		}
	);
	const rows = build_cwt_dialog_rows(frm, calculation_defaults);

	const dialog = new frappe.ui.Dialog({
		title: __("Add CWT"),
		size: "large",
		fields: [
			{
				fieldtype: "Percent",
				fieldname: "cwt_rate",
				label: __("Suggested CWT Rate"),
				default: calculation_defaults.cwt_rate,
				read_only: 1,
			},
			{
				fieldtype: "Percent",
				fieldname: "vat_rate",
				label: __("VAT Rate"),
				default: calculation_defaults.vat_rate,
				read_only: 1,
			},
			{
				fieldtype: "Data",
				fieldname: "rate_source",
				label: __("CWT Rate Source"),
				default: calculation_defaults.rate_source,
				read_only: 1,
			},
			{
				fieldtype: "Table",
				fieldname: "cwt_invoices",
				label: __("Sales Invoices"),
				cannot_add_rows: true,
				cannot_delete_rows: true,
				in_place_edit: true,
				data: rows,
				fields: [
					{
						fieldtype: "Data",
						fieldname: "reference_row_name",
						hidden: 1,
					},
					{
						fieldtype: "Check",
						fieldname: "select",
						label: __("Select"),
						in_list_view: 1,
						columns: 1,
					},
					{
						fieldtype: "Data",
						fieldname: "invoice",
						label: __("Invoice Number"),
						read_only: 1,
						in_list_view: 1,
						columns: 2,
					},
					{
						fieldtype: "Currency",
						fieldname: "original_amount",
						label: __("Original Invoice Amount"),
						read_only: 1,
						in_list_view: 1,
						columns: 2,
					},
					{
						fieldtype: "Currency",
						fieldname: "outstanding_amount",
						label: __("Balance"),
						read_only: 1,
						in_list_view: 1,
						columns: 2,
					},
					{
						fieldtype: "Currency",
						fieldname: "allocated_amount",
						label: __("Allocated Amount"),
						in_list_view: 1,
						columns: 2,
						onchange() {
							this.doc.cwt_amount = calculate_cwt_amount(
								this.value,
								calculation_defaults.cwt_rate,
								calculation_defaults.vat_rate
							);
							this.grid_row.refresh_field("cwt_amount");
						},
					},
					{
						fieldtype: "Currency",
						fieldname: "cwt_amount",
						label: __("CWT Amount"),
						in_list_view: 1,
						columns: 2,
					},
				],
			},
		],
		primary_action_label: __("Add Selected CWT"),
		primary_action(values) {
			const selected = ((values && values.cwt_invoices) || [])
				.filter((row) => flt(row.select));

			if (!selected.length) {
				frappe.msgprint(__("Select at least one Sales Invoice."));
				return;
			}

			const invalid_allocation = selected.find((row) => (
				flt(row.allocated_amount) <= 0
				|| flt(row.allocated_amount) > flt(row.outstanding_amount)
			));
			if (invalid_allocation) {
				frappe.msgprint(__("Allocated Amount must be positive and cannot exceed the invoice balance."));
				return;
			}

			const invalid = selected.find((row) => flt(row.cwt_amount) <= 0);
			if (invalid) {
				frappe.msgprint(__("CWT Amount must be positive for every selected Sales Invoice."));
				return;
			}

			frappe.call({
				method: "qcmc_logic.overrides.payment_entry.get_cwt_deduction_defaults",
				args: {
					company: frm.doc.company,
				},
				freeze: true,
				freeze_message: __("Finding CWT account and cost center..."),
				callback(r) {
					const defaults = r.message || {};
					apply_selected_cwt_deductions(
						frm,
						selected,
						{ ...defaults, ...calculation_defaults }
					);
					dialog.hide();
				},
			});
		},
	});

	dialog.show();
}

function apply_selected_cwt_deductions(frm, selected, defaults) {
	const existing = get_existing_cwt_deduction_map(frm);
	const references = Object.fromEntries(
		(frm.doc.references || []).map((row) => [row.name, row])
	);

	selected.forEach((selected_row) => {
		const invoice = selected_row.invoice;
		const description = `${CWT_DEDUCTION_DESCRIPTION_PREFIX}${invoice}`;
		const row = existing[invoice] ? existing[invoice].row : frm.add_child("deductions");

		row.account = defaults.account;
		row.cost_center = defaults.cost_center;
		row.amount = flt(selected_row.cwt_amount, 2);
		row.description = description;
		row.custom_cwt_sales_invoice = invoice;
		row.custom_cwt_allocated_amount = flt(selected_row.allocated_amount, 2);
		row.custom_cwt_rate = flt(defaults.cwt_rate);
		row.custom_cwt_vat_rate = flt(defaults.vat_rate);

		const reference = references[selected_row.reference_row_name];
		if (reference) {
			reference.allocated_amount = flt(selected_row.allocated_amount, 2);
		}
	});

	frm.refresh_field("references");
	frm.refresh_field("deductions");
	trigger_payment_entry_recalculation(frm);
}

function trigger_payment_entry_recalculation(frm) {
	frm.trigger("set_total_allocated_amount");
}

function set_underpayment_breakdown_queries(frm) {
	if (!frm.fields_dict.custom_underpayment_breakdown) return;

	frm.set_query("sales_invoice", "custom_underpayment_breakdown", () => {
		const invoices = get_underpaid_sales_invoice_references(frm).map(row => row.invoice);

		return invoices.length
			? { filters: { name: ["in", invoices] } }
			: { filters: { name: ["=", ""] } };
	});
}

function render_underpayment_breakdown_controls(frm) {
	const has_underpayments = get_underpaid_sales_invoice_references(frm).length > 0;

	frm.toggle_display("custom_underpayment_section", has_underpayments);
	frm.toggle_display("custom_underpayment_breakdown", has_underpayments);

	const button_id = "qcmc-add-underpayment-breakdown";
	$(`#${button_id}`).remove();

	if (!has_underpayments || frm.doc.docstatus !== 0 || !frm.fields_dict.custom_underpayment_breakdown) {
		return;
	}

	const $button = $(`
		<div id="${button_id}" class="text-right" style="margin: 8px 0 10px;">
			<button class="btn btn-xs btn-default">
				${__("Insert Underpayment Invoices")}
			</button>
		</div>
	`);

	$button.find("button").on("click", () => {
		insert_underpayment_breakdown_rows(frm);
	});

	frm.fields_dict.custom_underpayment_breakdown.$wrapper.before($button);
}

async function refresh_underpayment_breakdown_controls(frm) {
	const existing = await get_existing_underpayment_invoice_map(frm);
	frm.qcmc_existing_underpayment_invoices = existing;
	set_underpayment_breakdown_queries(frm);
	render_underpayment_breakdown_controls(frm);
}

function get_underpaid_sales_invoice_references(frm) {
	const by_invoice = {};
	const existing = frm.qcmc_existing_underpayment_invoices || {};

	(frm.doc.references || []).forEach(row => {
		if (row.reference_doctype !== "Sales Invoice" || !row.reference_name) return;
		if (existing[row.reference_name]) return;

		const outstanding = flt(row.outstanding_amount);
		const allocated = flt(row.allocated_amount);
		const underpayment = flt(outstanding - allocated);

		if (allocated <= 0 || underpayment <= 0) return;

		by_invoice[row.reference_name] = flt((by_invoice[row.reference_name] || 0) + underpayment);
	});

	return Object.keys(by_invoice).map(invoice => ({
		invoice,
		amount: by_invoice[invoice],
	}));
}

async function get_existing_underpayment_invoice_map(frm) {
	const invoices = (frm.doc.references || [])
		.filter(row => row.reference_doctype === "Sales Invoice" && row.reference_name)
		.map(row => row.reference_name);

	if (!invoices.length) return {};

	const { message } = await frappe.call({
		method: "qcmc_logic.overrides.payment_entry.get_existing_underpayment_invoices",
		args: {
			sales_invoices: invoices,
			payment_entry: frm.doc.name,
		},
	});

	return message || {};
}

async function insert_underpayment_breakdown_rows(frm) {
	frm.qcmc_existing_underpayment_invoices = await get_existing_underpayment_invoice_map(frm);
	const underpaid_invoices = get_underpaid_sales_invoice_references(frm);
	const existing = {};

	(frm.doc.custom_underpayment_breakdown || []).forEach(row => {
		if (!row.sales_invoice) return;
		existing[row.sales_invoice] = flt((existing[row.sales_invoice] || 0) + flt(row.amount));
	});

	let inserted = 0;
	underpaid_invoices.forEach(row => {
		const remaining = flt(row.amount - (existing[row.invoice] || 0));
		if (remaining <= 0) return;

		const child = frm.add_child("custom_underpayment_breakdown");
		child.sales_invoice = row.invoice;
		child.amount = remaining;
		inserted += 1;
	});

	frm.refresh_field("custom_underpayment_breakdown");
	render_underpayment_breakdown_controls(frm);

	if (!inserted) {
		frappe.msgprint(__("Underpayment Breakdown already matches the underpaid Sales Invoice references."));
	}
}

function render_affiliate_collection_deduction_button(frm) {
	const button_id = "qcmc-affiliate-collection-deduction";
	$(`#${button_id}`).remove();

	if (
		frm.doc.docstatus !== 0
		|| frm.doc.payment_type !== "Receive"
		|| !frm.doc.company
		|| flt(frm.doc.unallocated_amount) <= 0
	) {
		return;
	}

	const $target = frm.fields_dict.deductions
		? frm.fields_dict.deductions.$wrapper
		: frm.fields_dict.unallocated_amount.$wrapper;

	const $button = $(`
		<div id="${button_id}" class="text-right" style="margin: 8px 0 10px;">
			<button class="btn btn-xs btn-default">
				${__("Add Affiliate Collection Deduction")}
			</button>
		</div>
	`);

	$button.find("button").on("click", () => {
		show_affiliate_collection_deduction_dialog(frm);
	});

	$target.before($button);
}

function add_intercompany_collection_buttons(frm) {
	if (frm.doc.docstatus !== 1 || frm.doc.payment_type !== "Receive") {
		return;
	}

	if (
		has_affiliate_collection_deduction(frm)
		&& !frm.doc.custom_intercompany_target_payment_entry
	) {
		frm.add_custom_button(__("Create Intercompany Payment Entry"), () => {
			show_intercompany_payment_preview(frm);
		});
	}

	const is_intercompany_target = (frm.doc.mode_of_payment || "").toLowerCase().includes("collected by")
		&& frm.doc.custom_ref_doc;

	if (
		is_intercompany_target
		&& !frm.doc.custom_intercompany_source_journal_entry
	) {
		frm.add_custom_button(__("Create Settlement JVs"), () => {
			show_intercompany_journal_preview(frm);
		});
	}
}

function has_affiliate_collection_deduction(frm) {
	return (frm.doc.deductions || []).some((row) => {
		const account = (row.account || "").toLowerCase();
		return flt(row.amount) < 0 && account.includes("advances from affiliates");
	});
}

async function show_affiliate_collection_deduction_dialog(frm) {
	const default_amount = Math.max(flt(frm.doc.unallocated_amount), 0);

	const dialog = new frappe.ui.Dialog({
		title: __("Add Affiliate Collection Deduction"),
		fields: [
			{
				fieldtype: "Link",
				fieldname: "affiliate_company",
				label: __("Affiliate Company"),
				options: "Company",
				reqd: 1,
				get_query: () => ({
					filters: {
						name: ["!=", frm.doc.company],
						is_group: 0,
					},
				}),
			},
			{
				fieldtype: "Currency",
				fieldname: "amount",
				label: __("Amount"),
				default: default_amount,
				reqd: 1,
			},
		],
		primary_action_label: __("Apply"),
		primary_action(values) {
			if (!flt(values.amount)) {
				frappe.msgprint(__("Amount is required."));
				return;
			}

			frappe.call({
				method: "qcmc_logic.overrides.payment_entry.get_affiliate_collection_deduction_defaults",
				args: {
					company: frm.doc.company,
					affiliate_company: values.affiliate_company,
				},
				freeze: true,
				freeze_message: __("Finding affiliate advances account..."),
				callback(r) {
					const defaults = r.message || {};
					const row = frm.add_child("deductions");
					row.account = defaults.account;
					row.cost_center = defaults.cost_center;
					row.amount = -Math.abs(flt(values.amount));
					frm.refresh_field("deductions");
					frm.trigger("set_unallocated_amount");
					dialog.hide();
				},
			});
		},
	});

	dialog.show();
}

async function show_intercompany_payment_preview(frm) {
	const preview = await get_intercompany_payment_preview(frm.doc.name);

	const dialog = new frappe.ui.Dialog({
		title: __("Create Intercompany Payment Entry"),
		fields: [
			{ fieldtype: "HTML", fieldname: "preview_html", options: render_payment_preview(preview) },
			{
				fieldtype: "Select",
				fieldname: "target_company",
				label: __("Target Company"),
				options: (preview.target_options || []).map((option) => option.company),
				default: preview.target_company,
				reqd: 1,
				onchange: async () => {
					const target_company = dialog.get_value("target_company");
					const selected_preview = await get_intercompany_payment_preview(frm.doc.name, target_company);
					dialog.set_value("paid_to", selected_preview.paid_to);
					dialog.fields_dict.preview_html.$wrapper.html(render_payment_preview(selected_preview));
				},
			},
			{
				fieldtype: "Currency",
				fieldname: "amount",
				label: __("Amount"),
				default: preview.amount,
				reqd: 1,
			},
			{
				fieldtype: "Link",
				fieldname: "paid_to",
				label: __("Paid To"),
				options: "Account",
				default: preview.paid_to,
				reqd: 1,
				get_query: () => ({
					filters: {
						company: dialog.get_value("target_company") || preview.target_company,
						is_group: 0,
					},
				}),
			},
		],
		primary_action_label: __("Create Draft"),
		primary_action(values) {
			frappe.call({
				method: "qcmc_logic.overrides.payment_entry.create_intercompany_collection_payment",
				args: {
					source_payment_entry: frm.doc.name,
					target_company: values.target_company,
					paid_to: values.paid_to,
					amount: values.amount,
				},
				freeze: true,
				freeze_message: __("Creating draft Payment Entry..."),
				callback(r) {
					dialog.hide();
					frm.reload_doc();
					if (r.message && r.message.payment_entry) {
						frappe.set_route("Form", "Payment Entry", r.message.payment_entry);
					}
				},
			});
		},
	});

	dialog.show();
}

async function get_intercompany_payment_preview(source_payment_entry, target_company) {
	const { message } = await frappe.call({
		method: "qcmc_logic.overrides.payment_entry.get_intercompany_collection_payment_preview",
		args: {
			source_payment_entry,
			target_company,
		},
	});

	return message;
}

async function show_intercompany_journal_preview(frm) {
	const { message } = await frappe.call({
		method: "qcmc_logic.overrides.payment_entry.get_intercompany_collection_journal_preview",
		args: {
			target_payment_entry: frm.doc.name,
		},
	});

	const preview = message;
	const dialog = new frappe.ui.Dialog({
		title: __("Create Settlement JVs"),
		fields: [
			{ fieldtype: "HTML", fieldname: "preview_html", options: render_journal_preview(preview) },
		],
		primary_action_label: __("Create and Submit JVs"),
		primary_action() {
			frappe.call({
				method: "qcmc_logic.overrides.payment_entry.create_intercompany_collection_journals",
				args: {
					target_payment_entry: frm.doc.name,
				},
				freeze: true,
				freeze_message: __("Creating draft Journal Entries..."),
				callback(r) {
					dialog.hide();
					frm.reload_doc();
					if (r.message && r.message.source_journal_entry) {
						frappe.set_route("Form", "Journal Entry", r.message.source_journal_entry);
					}
				},
			});
		},
	});

	dialog.show();
}

function render_payment_preview(preview) {
	return `
		<div class="small text-muted">
			<div><b>${__("Source")}</b>: ${frappe.utils.escape_html(preview.source_payment_entry)}</div>
			<div><b>${__("Target Company")}</b>: ${frappe.utils.escape_html(preview.target_company)}</div>
			<div><b>${__("Customer")}</b>: ${frappe.utils.escape_html(preview.party)}</div>
			<div><b>${__("Mode of Payment")}</b>: ${frappe.utils.escape_html(preview.mode_of_payment)}</div>
			<div><b>${__("Paid From")}</b>: ${frappe.utils.escape_html(preview.paid_from)}</div>
		</div>
	`;
}

function render_journal_preview(preview) {
	return `
		<div class="small">
			${render_journal_section(__("QC Settlement JV"), preview.source_journal_entry)}
			${render_journal_section(__("MC Settlement JV"), preview.target_journal_entry)}
		</div>
	`;
}

function render_journal_section(label, journal) {
	const rows = (journal.accounts || []).map((row) => `
		<tr>
			<td>${frappe.utils.escape_html(row.account)}</td>
			<td class="text-right">${format_currency(row.debit || 0)}</td>
			<td class="text-right">${format_currency(row.credit || 0)}</td>
		</tr>
	`).join("");

	return `
		<div>
			<div><b>${label}</b>: ${frappe.utils.escape_html(journal.company)}</div>
			<table class="table table-bordered" style="margin-top: 8px;">
				<thead>
					<tr>
						<th>${__("Account")}</th>
						<th class="text-right">${__("Debit")}</th>
						<th class="text-right">${__("Credit")}</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
	`;
}
