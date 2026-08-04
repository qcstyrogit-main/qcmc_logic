frappe.ui.form.on("Payment Entry", {
	setup(frm) {
		set_underpayment_breakdown_queries(frm);
	},
	refresh(frm) {
		refresh_underpayment_breakdown_controls(frm);
		add_intercompany_collection_buttons(frm);
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
		render_affiliate_collection_deduction_button(frm);
	},
	company(frm) {
		render_affiliate_collection_deduction_button(frm);
	},
});

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
	},
});

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
