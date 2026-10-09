frappe.ui.form.on("Weekly Production Plan", {
	setup(frm) {
		frm.set_query("section", () => ({
			filters: { company: frm.doc.company || "" },
		}));
		for (const fieldname of ["second_item", "third_item"]) {
			frm.set_query(fieldname, "machine_schedule", (_doc, cdt, cdn) => ({
				query: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_machine_fg_items",
				filters: { machine: frappe.get_doc(cdt, cdn).machine },
			}));
		}
		for (const tableField of ["item_1_schedule", "item_2_schedule"]) {
			frm.set_query("product_code", tableField, (_doc, cdt, cdn) => ({
				query: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_machine_fg_items",
				filters: { machine: frappe.get_doc(cdt, cdn).machine },
			}));
		}
	},

	refresh(frm) {
		set_grid_read_only(frm);
	},

	async company(frm) {
		await frm.set_value("section", null);
		clear_generated_schedule(frm);
	},

	start_date(frm) {
		refresh_machine_schedule(frm);
	},

	section(frm) {
		refresh_machine_schedule(frm);
	},
});

frappe.ui.form.on("Weekly Production Plan Detail", {
	form_render(frm, cdt, cdn) {
		render_possible_sales_orders(frm, cdt, cdn);
	},
});

const productionItemHandlers = {
	product_code(frm, cdt, cdn) {
		populate_production_item(frm, cdt, cdn);
	},
	machine(frm, cdt, cdn) {
		populate_production_item(frm, cdt, cdn);
	},
	paid_hrs(frm, cdt, cdn) {
		calculate_plan_hours(frm, cdt, cdn);
	},
	vos(frm, cdt, cdn) {
		calculate_plan_hours(frm, cdt, cdn);
	},
	cm_co(frm, cdt, cdn) {
		calculate_plan_hours(frm, cdt, cdn);
	},
	stab(frm, cdt, cdn) {
		calculate_plan_hours(frm, cdt, cdn);
	},
	plan_hrs(frm, cdt, cdn) {
		calculate_daily_volume(frm, cdt, cdn);
	},
	soph(frm, cdt, cdn) {
		calculate_daily_volume(frm, cdt, cdn);
	},
	std_weight_gm(frm, cdt, cdn) {
		calculate_daily_volume(frm, cdt, cdn);
	},
};

frappe.ui.form.on("Weekly Production Plan Item", productionItemHandlers);
frappe.ui.form.on("Weekly Production Plan Secondary Item", productionItemHandlers);

async function render_possible_sales_orders(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const gridRow = frm.fields_dict.machine_schedule?.grid?.grid_rows_by_docname?.[cdn];
	const wrapper = gridRow?.grid_form?.fields_dict?.possible_sales_orders?.$wrapper;
	if (!wrapper) return;

	wrapper.html(`<div class="text-muted">${__("Loading current Sales Orders...")}</div>`);
	const response = await frappe.call({
		method: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_possible_sales_order_items",
		args: { machine: row.machine },
	});
	if (!gridRow.grid_form?.fields_dict?.possible_sales_orders?.$wrapper) return;

	const candidates = response.message || [];
	const escape = frappe.utils.escape_html;
	const body = candidates.map((candidate, index) => `
		<tr class="js-so-candidate" data-search="${escape(`${candidate.sales_order} ${candidate.item_code} ${candidate.description || ""}`.toLowerCase())}" data-status="${candidate.docstatus === 0 ? "draft" : "submitted"}">
			<td>${frappe.utils.get_form_link("Sales Order", candidate.sales_order, true)}</td>
			<td>${escape(frappe.datetime.str_to_user(candidate.sales_order_date))}</td>
			<td>${candidate.docstatus === 0 ? `<span class="indicator-pill orange">${__("Draft")}</span>` : `<span class="indicator-pill green">${__("Submitted")}</span>`}</td>
			<td>${frappe.utils.get_form_link("Item", candidate.item_code, true)}</td>
			<td class="text-right">${format_number(candidate.remaining_qty)}</td>
			<td class="text-right text-nowrap">
				<button class="btn btn-xs btn-default js-use-candidate" data-index="${index}" data-table="item_1_schedule">${__("Add to Item 1")}</button>
				<button class="btn btn-xs btn-default js-use-candidate" data-index="${index}" data-table="item_2_schedule">${__("Add to Item 2")}</button>
			</td>
		</tr>
	`).join("");

	const salesOrders = candidates.length ? `
		<div class="row" style="margin: 0 0 8px">
			<div class="col-sm-8" style="padding-left: 0"><input type="text" class="form-control input-sm js-so-filter" placeholder="${__("Filter by SO No., item, or description")}"></div>
			<div class="col-sm-4" style="padding-right: 0"><select class="form-control input-sm js-so-status-filter"><option value="">${__("All statuses")}</option><option value="draft">${__("Draft")}</option><option value="submitted">${__("Submitted")}</option></select></div>
		</div>
		<div class="text-muted small js-so-result-count" style="margin-bottom: 5px"></div>
		<div class="table-responsive" style="max-height: 245px; overflow-y: auto; border-bottom: 1px solid var(--border-color)">
			<table class="table table-bordered table-condensed">
				<thead style="position: sticky; top: 0; background: var(--card-bg); z-index: 1"><tr><th>${__("SO No.")}</th><th>${__("SO Date")}</th><th>${__("Status")}</th><th>${__("FG Item")}</th><th class="text-right">${__("Remaining Qty")}</th><th>${__("Action")}</th></tr></thead>
				<tbody>${body}</tbody>
			</table>
		</div>
	` : `<div class="text-muted">${__("No eligible Sales Order items for this machine.")}</div>`;
	wrapper.html(`${salesOrders}${scheduled_items_html(frm, row)}`);
	bind_scheduled_item_actions(wrapper, frm, row);
	bind_sales_order_filters(wrapper);
	wrapper.find(".js-use-candidate").on("click", async function() {
		const candidate = candidates[Number(this.dataset.index)];
		const tableField = this.dataset.table;
		open_scheduled_item_dialog(frm, row, tableField, null, candidate.item_code);
	});
}

function bind_sales_order_filters(wrapper) {
	const filterRows = () => {
		const textFilter = (wrapper.find(".js-so-filter").val() || "").trim().toLowerCase();
		const statusFilter = wrapper.find(".js-so-status-filter").val() || "";
		let visible = 0;
		wrapper.find(".js-so-candidate").each(function() {
			const matchesText = !textFilter || (this.dataset.search || "").includes(textFilter);
			const matchesStatus = !statusFilter || this.dataset.status === statusFilter;
			const show = matchesText && matchesStatus;
			$(this).toggle(show);
			if (show) visible += 1;
		});
		wrapper.find(".js-so-result-count").text(__("{0} matching Sales Order item(s)", [visible]));
	};
	wrapper.find(".js-so-filter").on("input", filterRows);
	wrapper.find(".js-so-status-filter").on("change", filterRows);
	filterRows();
}

function rows_for_schedule(frm, tableField, scheduleRow) {
	return (frm.doc[tableField] || []).filter(
		(row) => row.machine === scheduleRow.machine && row.plan_date === scheduleRow.plan_date,
	);
}

function scheduled_items_html(frm, scheduleRow) {
	const escape = frappe.utils.escape_html;
	const renderRows = (tableField, secondary = false) => {
		const rows = rows_for_schedule(frm, tableField, scheduleRow);
		if (!rows.length) return `<tr><td colspan="${secondary ? 10 : 18}" class="text-muted text-center">${__("No items added.")}</td></tr>`;
		return rows.map((row) => `
			<tr>
				<td>${escape(row.product_code || "")}</td><td>${escape(row.product_description || "")}</td>
				<td>${row.cavs || 0}</td>
				${secondary ? "" : `<td>${row.paid_hrs || 0}</td><td>${row.vos || 0}</td><td>${row.cm_co || 0}</td><td>${row.stab || 0}</td><td>${row.plan_hrs || 0}</td>`}
				<td>${row.soph || 0}</td><td>${row.std_weight_gm || 0}</td><td>${row.daily_volume_qty || 0}</td><td>${row.daily_volume_kgs || 0}</td>
				<td>${secondary ? (row.factor_rate || 0) : (row.f_rate || 0)}</td><td>${row.cycle_time || 0}</td>
				${secondary ? "" : `<td>${escape(row.remarks || "")}</td><td>${escape(row.mat_type || "")}</td><td>${row.steam_regmt || 0}</td>`}
				<td class="text-nowrap"><button class="btn btn-xs btn-default js-edit-scheduled-item" data-table="${tableField}" data-name="${row.name}">${__("Edit")}</button> <button class="btn btn-xs btn-default js-delete-scheduled-item" data-table="${tableField}" data-name="${row.name}">${__("Remove")}</button></td>
			</tr>`).join("");
	};
	const table = (title, tableField, secondary = false) => `
		<div style="margin-top: 15px"><div class="flex justify-between align-center"><strong>${__(title)}</strong><button class="btn btn-xs btn-primary js-add-scheduled-item" data-table="${tableField}">${__("Add Row")}</button></div>
		<div class="table-responsive"><table class="table table-bordered table-condensed" style="margin-top: 6px; white-space: nowrap"><thead><tr>
		<th>${__("Prodcode")}</th><th>${__("Proddesc")}</th><th>${__("Cavs")}</th>
		${secondary ? "" : `<th>${__("PaidHrs")}</th><th>${__("VOS")}</th><th>${__("CM/CO")}</th><th>${__("Stab")}</th><th>${__("PlanHrs")}</th>`}
		<th>${__("SOPH")}</th><th>${__("StdWt(gm)")}</th><th>${__("Daily Vol Qty")}</th><th>${__("DailyVolKgs")}</th><th>${__(secondary ? "FactorRate" : "F.Rate")}</th><th>${__(secondary ? "CycleTime" : "C.T.")}</th>
		${secondary ? "" : `<th>${__("Remarks")}</th><th>${__("MatType")}</th><th>${__("SteamRegmt")}</th>`}<th>${__("Action")}</th>
		</tr></thead><tbody>${renderRows(tableField, secondary)}</tbody></table></div></div>`;
	return `<div class="scheduled-items-editor"><h6 style="margin-top: 18px">${__("Scheduled FG Items for {0} on {1}", [scheduleRow.machine, frappe.datetime.str_to_user(scheduleRow.plan_date)])}</h6>${table("Item 1", "item_1_schedule")}${table("Item 2", "item_2_schedule", true)}</div>`;
}

function bind_scheduled_item_actions(wrapper, frm, scheduleRow) {
	wrapper.find(".js-add-scheduled-item").on("click", function() {
		open_scheduled_item_dialog(frm, scheduleRow, this.dataset.table);
	});
	wrapper.find(".js-edit-scheduled-item").on("click", function() {
		open_scheduled_item_dialog(frm, scheduleRow, this.dataset.table, this.dataset.name);
	});
	wrapper.find(".js-delete-scheduled-item").on("click", function() {
		frappe.model.clear_doc(frm.fields_dict[this.dataset.table].df.options, this.dataset.name);
		frm.refresh_field(this.dataset.table);
		frm.dirty();
		render_possible_sales_orders(frm, scheduleRow.doctype, scheduleRow.name);
	});
}

function open_scheduled_item_dialog(frm, scheduleRow, tableField, rowName = null, initialProduct = null) {
	const secondary = tableField === "item_2_schedule";
	const existing = rowName ? locals[frm.fields_dict[tableField].df.options]?.[rowName] : null;
	let dialog;
	const numeric = (fieldname, label, read_only = false, defaultValue = 0) => ({ fieldname, label, fieldtype: "Float", read_only, default: existing?.[fieldname] ?? defaultValue });
	const fields = [
		{ fieldname: "machine", label: __("Machine"), fieldtype: "Link", options: "Workstation", read_only: 1, default: scheduleRow.machine },
		{ fieldname: "plan_date", label: __("Plan Date"), fieldtype: "Date", read_only: 1, default: scheduleRow.plan_date },
		{ fieldname: "product_code", label: __("Prodcode"), fieldtype: "Link", options: "Item", reqd: 1, default: existing?.product_code || initialProduct, get_query: () => ({ query: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_machine_fg_items", filters: { machine: scheduleRow.machine } }), onchange: () => load_dialog_product_details(dialog, scheduleRow.machine, secondary) },
		{ fieldname: "product_description", label: __("Proddesc"), fieldtype: "Data", read_only: 1, default: existing?.product_description },
		{ fieldname: "cavs", label: __("Cavs"), fieldtype: "Int", read_only: 1, default: existing?.cavs },
	];
	if (!secondary) fields.push(numeric("paid_hrs", "PaidHrs", false, 24), numeric("vos", "VOS"), numeric("cm_co", "CM/CO"), numeric("stab", "Stab"), numeric("plan_hrs", "PlanHrs", true, 24));
	fields.push(numeric("soph", "SOPH", true), numeric("std_weight_gm", "StdWt(gm)", true), numeric("daily_volume_qty", "Daily Vol Qty", true), numeric("daily_volume_kgs", "DailyVolKgs", true), numeric(secondary ? "factor_rate" : "f_rate", secondary ? "FactorRate" : "F.Rate", false, 100), numeric("cycle_time", secondary ? "CycleTime" : "C.T.", true));
	if (!secondary) fields.push(
		{ fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text", default: existing?.remarks },
		{ fieldname: "mat_type", label: __("MatType"), fieldtype: "Data", default: existing?.mat_type },
		numeric("steam_regmt", "SteamRegmt"),
	);
	dialog = new frappe.ui.Dialog({ title: __(rowName ? "Edit {0}" : "Add {0}", [secondary ? "Item 2" : "Item 1"]), fields, primary_action_label: __("Save Row"), primary_action(values) {
		const target = existing || frm.add_child(tableField);
		Object.assign(target, values, { machine: scheduleRow.machine, plan_date: scheduleRow.plan_date });
		frm.refresh_field(tableField);
		frm.dirty();
		dialog.hide();
		keep_schedule_detail_open(frm, scheduleRow);
	} });
	for (const fieldname of ["paid_hrs", "vos", "cm_co", "stab"]) if (dialog.fields_dict[fieldname]) dialog.fields_dict[fieldname].df.onchange = () => calculate_dialog_plan_hours(dialog);
	dialog.show();
	if (!secondary) calculate_dialog_plan_hours(dialog);
	if (initialProduct) load_dialog_product_details(dialog, scheduleRow.machine, secondary);
}

function keep_schedule_detail_open(frm, scheduleRow) {
	setTimeout(() => {
		const gridRow = frm.fields_dict.machine_schedule?.grid?.grid_rows_by_docname?.[scheduleRow.name];
		if (!gridRow) return;
		gridRow.toggle_view(true, () => {
			render_possible_sales_orders(frm, scheduleRow.doctype, scheduleRow.name);
		});
	}, 100);
}

async function load_dialog_product_details(dialog, machine, secondary) {
	const productCode = dialog.get_value("product_code"); if (!productCode) return;
	const response = await frappe.call({ method: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_item_production_details", args: { item_code: productCode, machine } });
	const details = response.message || {};
	for (const fieldname of ["product_description", "cavs", "soph", "std_weight_gm", "cycle_time"]) dialog.set_value(fieldname, details[fieldname] || 0);
	calculate_dialog_volume(dialog, secondary);
}

function calculate_dialog_volume(dialog, secondary) {
	const hours = secondary ? 24 : calculate_net_paid_hours(
		dialog.get_value("paid_hrs"),
		dialog.get_value("vos"),
		dialog.get_value("cm_co"),
		dialog.get_value("stab"),
	);
	const quantity = hours * flt(dialog.get_value("soph"));
	dialog.set_value("daily_volume_qty", quantity);
	dialog.set_value("daily_volume_kgs", flt(dialog.get_value("std_weight_gm")) * quantity / 1000);
}

function calculate_dialog_plan_hours(dialog) {
	const planHours = calculate_net_paid_hours(
		dialog.get_value("paid_hrs"),
		dialog.get_value("vos"),
		dialog.get_value("cm_co"),
		dialog.get_value("stab"),
	);
	dialog.set_value("plan_hrs", planHours);
	calculate_dialog_volume(dialog, false);
}

async function add_scheduled_item(frm, tableField, scheduleRow, productCode) {
	const row = frm.add_child(tableField, {
		machine: scheduleRow.machine,
		plan_date: scheduleRow.plan_date,
		product_code: productCode,
		paid_hrs: 24,
		plan_hrs: 24,
		...(tableField === "item_1_schedule" ? { f_rate: 100 } : { factor_rate: 100 }),
	});
	await populate_production_item(frm, row.doctype, row.name);
	frm.refresh_field(tableField);
}

async function populate_production_item(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	if (!row.product_code || !row.machine) return;
	const response = await frappe.call({
		method: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_item_production_details",
		args: { item_code: row.product_code, machine: row.machine },
	});
	const details = response.message || {};
	for (const fieldname of ["product_description", "cavs", "soph", "std_weight_gm", "cycle_time"]) {
		await frappe.model.set_value(cdt, cdn, fieldname, details[fieldname] || 0);
	}
	calculate_daily_volume(frm, cdt, cdn);
}

function calculate_daily_volume(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const hours = row.doctype === "Weekly Production Plan Secondary Item"
		? 24
		: calculate_net_paid_hours(row.paid_hrs, row.vos, row.cm_co, row.stab);
	const quantity = hours * flt(row.soph);
	frappe.model.set_value(cdt, cdn, "daily_volume_qty", quantity);
	frappe.model.set_value(cdt, cdn, "daily_volume_kgs", flt(row.std_weight_gm) * quantity / 1000);
}

function calculate_plan_hours(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const planHours = calculate_net_paid_hours(row.paid_hrs, row.vos, row.cm_co, row.stab);
	frappe.model.set_value(cdt, cdn, "plan_hrs", planHours);
	calculate_daily_volume(frm, cdt, cdn);
}

function calculate_net_paid_hours(paidHours, vos, cmCo, stab) {
	return flt(paidHours) - flt(vos) - flt(cmCo) - flt(stab);
}

async function refresh_machine_schedule(frm) {
	if (!frm.doc.start_date) {
		await frm.set_value("end_date", null);
		await frm.set_value("record_no", null);
		clear_generated_schedule(frm);
		return;
	}

	await frm.set_value("end_date", frappe.datetime.add_days(frm.doc.start_date, 13));
	if (!frm.doc.company || !frm.doc.section) {
		await frm.set_value("record_no", null);
		clear_generated_schedule(frm);
		return;
	}

	const requestedCompany = frm.doc.company;
	const requestedSection = frm.doc.section;
	const requestedStartDate = frm.doc.start_date;
	const response = await frappe.call({
		method: "qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.get_machine_schedule",
		args: {
			company: requestedCompany,
			section: requestedSection,
			start_date: requestedStartDate,
		},
		freeze: true,
		freeze_message: __("Building 14-day machine schedule..."),
	});

	if (
		frm.doc.company !== requestedCompany
		|| frm.doc.section !== requestedSection
		|| frm.doc.start_date !== requestedStartDate
	) return;

	const schedule = response.message || {};
	await frm.set_value("end_date", schedule.end_date || null);
	await frm.set_value("record_no", schedule.record_no || null);
	frm.clear_table("machine_schedule");
	for (const row of schedule.rows || []) {
		frm.add_child("machine_schedule", row);
	}
	frm.refresh_field("machine_schedule");
	set_grid_read_only(frm);

	if (!(schedule.rows || []).length) {
		frappe.msgprint(__("No enabled Workstations are assigned to Plant Floor {0}.", [requestedSection]));
	}
}

function clear_generated_schedule(frm) {
	frm.clear_table("machine_schedule");
	frm.refresh_field("machine_schedule");
}

function set_grid_read_only(frm) {
	const grid = frm.fields_dict.machine_schedule?.grid;
	if (!grid) return;
	grid.cannot_add_rows = true;
	grid.cannot_delete_rows = true;
	grid.wrapper.find(".grid-add-row, .grid-remove-rows, .grid-delete-row").hide();
}
