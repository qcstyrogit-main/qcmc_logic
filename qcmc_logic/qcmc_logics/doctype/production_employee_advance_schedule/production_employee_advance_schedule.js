const APPROVED_PRODUCTION_WAREHOUSES = [
	"RMFS - Guyong",
	"Recycling - Guyong",
	"RMFS - Sta Clara",
	"Recycling - Sta Clara",
	"Recycling - MC1",
	"Recycling - MC2",
	"RMFS - MC1",
	"RMFS - MC2",
];

frappe.ui.form.on("Production Employee Advance Schedule", {
	setup(frm) {
		frm.set_query("company", () => ({
			filters: {
				name: ["in", ["Multiplast Corporation", "QC Styropackaging Corporation"]],
			},
		}));
		frm.set_query("warehouse", () => ({
			filters: {
				company: frm.doc.company,
				warehouse_name: ["in", APPROVED_PRODUCTION_WAREHOUSES],
				disabled: 0,
			},
		}));
		set_detail_queries(frm);
	},
	refresh(frm) {
		render_weekly_preview(frm);
		if (frm.doc.docstatus === 0 && ["Draft", "Returned for Revision", undefined, null, ""].includes(frm.doc.workflow_state)) {
			frm.add_custom_button(__("Load / Refresh Plantilla"), () => load_plantilla(frm));
		}
	},
	company(frm) {
		frm.set_value("warehouse", null);
		clear_schedule_details(frm);
		frm.set_value("plantilla_loaded_by", null);
		frm.set_value("plantilla_loaded_at", null);
	},
	async warehouse(frm) {
		clear_schedule_details(frm);
		if (!frm.doc.warehouse) {
			await frm.set_value("plantilla_loaded_by", null);
			await frm.set_value("plantilla_loaded_at", null);
			await render_weekly_preview(frm);
			return;
		}
		if (!frm.doc.company) {
			frappe.msgprint(__("Select Company before Warehouse."));
			return;
		}
		await populate_plantilla(frm, {
			confirmReplacement: false,
			showFreeze: false,
		});
	},
	date_start(frm) {
		if (!frm.doc.date_start) return;
		frm.set_value("date_end", frappe.datetime.add_days(frm.doc.date_start, 6));
		render_weekly_preview(frm);
	},
	date_end(frm) {
		render_weekly_preview(frm);
	},
});

frappe.ui.form.on("Production Employee Schedule Detail", {
	schedule_details_add(frm) {
		render_weekly_preview(frm);
	},
	schedule_details_remove(frm) {
		render_weekly_preview(frm);
	},
	row_source(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.row_source === "Manual") {
			frappe.model.set_value(cdt, cdn, "production_plantilla", null);
		}
	},
	ds_assignment_status(frm, cdt, cdn) {
		clear_employee_for_non_assigned(cdt, cdn, "ds_assignment_status", "day_shift_employee");
	},
	ns_assignment_status(frm, cdt, cdn) {
		clear_employee_for_non_assigned(cdt, cdn, "ns_assignment_status", "night_shift_employee");
	},
	section(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.row_source === "Manual") {
			frappe.model.set_value(cdt, cdn, "machine", null);
		}
	},
});

const PREVIEW_DETAIL_FIELDS = [
	"production_position",
	"plantilla_id",
	"ds_assignment_status",
	"day_shift_employee",
	"day_shift_mon",
	"day_shift_tue",
	"day_shift_wed",
	"day_shift_thu",
	"day_shift_fri",
	"day_shift_sat",
	"day_shift_sun",
	"day_shift_restday",
	"ns_assignment_status",
	"night_shift_employee",
	"night_shift_mon",
	"night_shift_tue",
	"night_shift_wed",
	"night_shift_thu",
	"night_shift_fri",
	"night_shift_sat",
	"night_shift_sun",
	"night_shift_restday",
];

frappe.ui.form.on(
	"Production Employee Schedule Detail",
	Object.fromEntries(PREVIEW_DETAIL_FIELDS.map((fieldname) => [
		fieldname,
		(frm) => render_weekly_preview(frm),
	])),
);

function set_detail_queries(frm) {
	frm.set_query("section", "schedule_details", () => ({
		filters: {
			company: frm.doc.company,
			warehouse: frm.doc.warehouse,
		},
	}));
	frm.set_query("machine", "schedule_details", (doc, cdt, cdn) => {
		const row = locals[cdt][cdn];
		return {
			filters: {
				plant_floor: row.section,
				disabled: 0,
			},
		};
	});
	frm.set_query("production_plantilla", "schedule_details", () => ({
		filters: {
			company: frm.doc.company,
			warehouse: frm.doc.warehouse,
			is_active: 1,
		},
	}));
}

function clear_employee_for_non_assigned(cdt, cdn, statusField, employeeField) {
	const row = locals[cdt][cdn];
	if (row[statusField] && row[statusField] !== "Assigned") {
		frappe.model.set_value(cdt, cdn, employeeField, null);
	}
}

async function load_plantilla(frm) {
	if (!frm.doc.company || !frm.doc.warehouse) {
		frappe.msgprint(__("Select Company and Warehouse first."));
		return;
	}
	await populate_plantilla(frm, {
		confirmReplacement: true,
		showFreeze: true,
	});
}

async function populate_plantilla(frm, { confirmReplacement, showFreeze }) {
	if (confirmReplacement && frm.doc.schedule_details && frm.doc.schedule_details.length) {
		const confirmed = await new Promise((resolve) => {
			frappe.confirm(
				__("This will replace the current rows. Existing employee assignments will be removed. Continue?"),
				() => resolve(true),
				() => resolve(false),
			);
		});
		if (!confirmed) return;
	}

	const requestedWarehouse = frm.doc.warehouse;
	let response;
	try {
		response = await frappe.call({
			method: "qcmc_logic.qcmc_logics.doctype.production_employee_advance_schedule.production_employee_advance_schedule.get_plantilla_rows",
			args: {
				company: frm.doc.company,
				warehouse: requestedWarehouse,
				date_start: frm.doc.date_start || frappe.datetime.get_today(),
			},
			freeze: showFreeze,
			freeze_message: __("Loading Production Plantilla..."),
		});
	} catch (error) {
		clear_schedule_details(frm);
		throw error;
	}

	// Ignore an older response if the user changed Warehouse while it was loading.
	if (frm.doc.warehouse !== requestedWarehouse) return;

	clear_schedule_details(frm);
	const seenPlantilla = new Set();
	for (const plantilla of response.message || []) {
		const uniqueKey = plantilla.name || `${plantilla.plantilla_id}:${plantilla.plantilla_slot}`;
		if (seenPlantilla.has(uniqueKey)) continue;
		seenPlantilla.add(uniqueKey);
		frm.add_child("schedule_details", {
			section: plantilla.section,
			machine: plantilla.machine,
			production_position: plantilla.production_position,
			plantilla_id: plantilla.plantilla_id,
			plantilla_slot: plantilla.plantilla_slot,
			row_source: "Plantilla",
			production_plantilla: plantilla.name,
		});
	}
	await frm.set_value("plantilla_loaded_by", frappe.session.user);
	await frm.set_value("plantilla_loaded_at", frappe.datetime.now_datetime());
	frm.refresh_field("schedule_details");
	await render_weekly_preview(frm);
	frappe.show_alert({
		message: __("Loaded {0} active Plantilla rows.", [seenPlantilla.size]),
		indicator: "green",
	});
}

function clear_schedule_details(frm) {
	frm.clear_table("schedule_details");
	frm.refresh_field("schedule_details");
}

async function render_weekly_preview(frm) {
	const wrapper = frm.fields_dict.weekly_schedule_preview?.$wrapper;
	if (!wrapper) return;
	const rows = frm.doc.schedule_details || [];
	if (!rows.length) {
		wrapper.html(`<div class="text-muted">${__("Load Plantilla rows to display the weekly schedule.")}</div>`);
		return;
	}

	const shiftNames = [...new Set(rows.flatMap((row) =>
		["day_shift", "night_shift"].flatMap((prefix) =>
			["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
				.map((day) => row[`${prefix}_${day}`])
				.filter(Boolean),
		),
	))];
	const shiftTimes = {};
	if (shiftNames.length) {
		const shifts = await frappe.db.get_list("Shift Type", {
			filters: { name: ["in", shiftNames] },
			fields: ["name", "start_time", "end_time"],
			limit: shiftNames.length,
		});
		for (const shift of shifts) {
			shiftTimes[shift.name] = `${format_time(shift.start_time)} - ${format_time(shift.end_time)}`;
		}
	}

	const dayNames = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
	const headers = [
		"Position", "Plantilla Record", "ID", "DS Employee",
		...dayNames.map((day) => `DS ${day.toUpperCase()}`),
		"DS Restday", "NS Employee",
		...dayNames.map((day) => `NS ${day.toUpperCase()}`),
		"NS Restday",
	];
	const body = rows.map((row) => {
		const cells = [
			row.production_position,
			row.production_plantilla
				? {
					html: `<a href="${frappe.utils.get_form_link("Production Plantilla", row.production_plantilla)}">${frappe.utils.escape_html(row.production_plantilla)}</a>`,
				}
				: "",
			row.plantilla_id,
			row.day_shift_employee || row.ds_assignment_status,
			...dayNames.map((day) => schedule_cell(frm, row, "day_shift", day, shiftTimes)),
			row.day_shift_restday,
			row.night_shift_employee || row.ns_assignment_status,
			...dayNames.map((day) => schedule_cell(frm, row, "night_shift", day, shiftTimes)),
			row.night_shift_restday,
		];
		return `<tr>${cells.map(render_preview_cell).join("")}</tr>`;
	}).join("");
	wrapper.html(`
		<div style="overflow-x:auto;max-width:100%">
			<table class="table table-bordered table-sm" style="white-space:nowrap;font-size:11px">
				<thead><tr>${headers.map((label) => `<th>${__(label)}</th>`).join("")}</tr></thead>
				<tbody>${body}</tbody>
			</table>
		</div>
	`);
}

function render_preview_cell(value) {
	if (value && typeof value === "object" && value.html) {
		return `<td>${value.html}</td>`;
	}
	return `<td>${frappe.utils.escape_html(String(value || ""))}</td>`;
}

function schedule_cell(frm, row, prefix, day, shiftTimes) {
	const dayIndex = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].indexOf(day);
	const cellDate = frm.doc.date_start ? frappe.datetime.add_days(frm.doc.date_start, dayIndex) : null;
	const restday = prefix === "day_shift" ? row.day_shift_restday : row.night_shift_restday;
	if (cellDate && restday === cellDate) return "RD";
	const shiftType = row[`${prefix}_${day}`];
	return shiftTimes[shiftType] || shiftType || "";
}

function format_time(value) {
	if (!value) return "";
	return moment(value, ["HH:mm:ss", "HH:mm"]).format("h:mm A");
}
