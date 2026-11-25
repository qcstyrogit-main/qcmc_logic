async function autofill_process_card_shift(frm) {
	const shiftType = frm.doc.shift_type;
	const shiftDate = frm.doc.shift_date;
	const sequence = (frm._shift_time_request || 0) + 1;
	frm._shift_time_request = sequence;
	if (!shiftType || !shiftDate) return;
	if (!["Draft", "In Progress"].includes(frm.doc.status || "Draft")) return;
	const response = await frappe.db.get_value("Shift Type", shiftType, ["start_time", "end_time"]);
	if (sequence !== frm._shift_time_request || frm.doc.shift_type !== shiftType || frm.doc.shift_date !== shiftDate) return;
	const times = response.message;
	if (!times?.start_time || !times?.end_time) {
		frappe.msgprint(__("Set Start Time and End Time on the selected Shift Type."));
		return;
	}
	// MariaDB Time values may be returned without a leading zero.
	const normalizeTime = value => value.split(":").map(part => part.padStart(2, "0")).join(":");
	const startTime = normalizeTime(times.start_time);
	const endTime = normalizeTime(times.end_time);
	const endDate = endTime <= startTime ? frappe.datetime.add_days(shiftDate, 1) : shiftDate;
	await frm.set_value({
		shift_start: frappe.datetime.convert_to_system_tz(shiftDate + " " + startTime),
		shift_end: frappe.datetime.convert_to_system_tz(endDate + " " + endTime),
	});
}

frappe.ui.form.on("Process Card", {
	setup(frm) {
		frm.set_query("job_card", "jobs", () => {
			if (!frm.doc.workstation || !frm.doc.company) {
				return {filters: {name: ["=", ""]}};
			}
			const selected = (frm.doc.jobs || []).map(row => row.job_card).filter(Boolean);
			const filters = {
				workstation: frm.doc.workstation,
				company: frm.doc.company,
				docstatus: ["<", 2],
				status: ["not in", ["Completed", "Cancelled"]],
			};
			if (selected.length) filters.name = ["not in", selected];
			return {filters};
		});
	},
	shift_type: autofill_process_card_shift,
	shift_date: autofill_process_card_shift,
	onload(frm) {
		if (frm.is_new() && (!frm.doc.shift_start || !frm.doc.shift_end)) {
			return autofill_process_card_shift(frm);
		}
	},
	refresh(frm) {
		if (frm.is_new()) return;
		const transition = (status, label) => {
			frm.add_custom_button(__(label), () => {
				frappe.call({
					method: "qcmc_logic.api.process_card_workbench.transition_status",
					args: { process_card: frm.doc.name, status },
					freeze: true,
					freeze_message: __("Updating Process Card status..."),
				}).then(() => frm.reload_doc());
			}, __("Shift"));
		};

		if (frm.doc.status === "Draft") transition("In Progress", "Start Shift");
		if (frm.doc.status === "In Progress") transition("For Approval", "Send for Approval");
		if (frm.doc.status === "For Approval") {
			transition("In Progress", "Return to In Progress");
			if (frappe.user.has_role("Manufacturing Manager") || frappe.user.has_role("System Manager")) {
				transition("Approved", "Approve Process Card");
			}
		}
		if (["Draft", "In Progress", "For Approval"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Cancel Shift"), () => {
				frappe.confirm(__("Cancel this Process Card?"), () => {
					frappe.call({
						method: "qcmc_logic.api.process_card_workbench.transition_status",
						args: { process_card: frm.doc.name, status: "Cancelled" },
						freeze: true,
						freeze_message: __("Cancelling Process Card..."),
					}).then(() => frm.reload_doc());
				});
			}, __("Shift"));
		}

		frm.add_custom_button(__("Shift Summary"), () => {
			frappe.call({
				method: "qcmc_logic.api.process_card_services.get_process_card_shift_summary",
				args: { process_card: frm.doc.name },
				freeze: true,
				freeze_message: __("Loading shift summary..."),
			}).then(({message: summary}) => {
				const escape = value => frappe.utils.escape_html(String(value ?? ""));
				const metric = value => value == null ? __("Unavailable") : Number(value).toFixed(2);
				const table = (headers, rows) => `
					<table class="table table-bordered table-sm">
						<thead><tr>${headers.map(header => `<th>${escape(header)}</th>`).join("")}</tr></thead>
						<tbody>${rows || `<tr><td colspan="${headers.length}">${escape(__("No records"))}</td></tr>`}</tbody>
					</table>`;
				const outputRows = summary.production_output.per_job.map(row =>
					`<tr><td>${escape(row.job_card)}</td><td>${escape(row.production_item)}</td><td>${metric(row.good_qty)}</td><td>${metric(row.rejected_qty)}</td></tr>`
				).join("");
				const manpowerRows = summary.manpower_participation.map(row =>
					`<tr><td>${escape(row.employee_name || row.employee)}</td><td>${escape(row.job_card)}</td><td>${escape(row.from_time)}</td><td>${escape(row.to_time)}</td><td>${escape(row.pay_mode)}</td><td>${escape(row.mca_approval_reference)}</td></tr>`
				).join("");
				const qaRows = summary.qa_rejections.map(row =>
					`<tr><td>${escape(row.quality_inspection)}</td><td>${escape(row.specification)}</td><td>${escape(row.reject_reason)}</td><td>${metric(row.rejected_qty)}</td></tr>`
				).join("");
				const inspectionRows = summary.quality_inspections.map(row =>
					`<tr><td>${escape(row.name)}</td><td>${escape(row.job_card)}</td><td>${escape(row.status)}</td><td>${escape(row.inspected_by)}</td></tr>`
				).join("");
				const measurementRows = summary.measurements.map(row =>
					`<tr><td>${escape(row.quality_inspection)}</td><td>${escape(row.specification)}</td><td>${escape(row.reading_value || (row.readings || []).filter(Boolean).join(", "))}</td><td>${escape(row.uom)}</td><td>${escape(row.result)}</td></tr>`
				).join("");
				const downtimeRows = summary.downtime_entries.map(row =>
					`<tr><td>${escape(row.name)}</td><td>${escape(row.from_time)}</td><td>${escape(row.to_time)}</td><td>${escape(row.stop_reason)}</td></tr>`
				).join("");
				const breakdownRows = summary.breakdowns.map(row =>
					`<tr><td>${escape(row.name)}</td><td>${escape(row.asset)}</td><td>${escape(row.failure_date)}</td><td>${escape(row.repair_status)}</td><td>${escape(row.actions_taken)}</td></tr>`
				).join("");
				const metrics = summary.machine_metrics;
				if (summary.section_access && Object.values(summary.section_access).includes(false)) frappe.show_alert({message: __("Some shift summary sections are restricted by your permissions."), indicator: "orange"});
				const dialog = new frappe.ui.Dialog({
					title: __("Shift Summary"),
					fields: [{fieldtype: "HTML", fieldname: "summary"}],
					primary_action_label: __("Close"),
					primary_action: () => dialog.hide(),
				});
				dialog.fields_dict.summary.$wrapper.html(`
					<p><strong>${__("Availability")}</strong>: ${metric(metrics.availability_percent)}% (${metric(metrics.available_hours)} ${__("available hours")} / ${metric(metrics.shift_hours)} ${__("shift hours")})</p>
					<p><strong>${__("Downtime")}</strong>: ${metric(metrics.downtime_hours)} ${__("hours")} &nbsp; <strong>${__("Recorded Output Interval Hours")}</strong>: ${metric(metrics.recorded_output_interval_hours)} ${__("hours")}</p>
					<p class="text-muted">${escape(metrics.definitions.availability)} ${escape(metrics.definitions.actual_run_hours)}</p>
					<h5>${__("Production Output")}</h5>${table([__("Job Card"), __("Item"), __("Good Qty"), __("Rejected Qty")], outputRows)}
					<h5>${__("Manpower Participation")}</h5>${table([__("Employee"), __("Job Card"), __("Time In"), __("Time Out"), __("Pay Mode"), __("MCA Approval")], manpowerRows)}
					<h5>${__("Quality Inspections")}</h5>${table([__("Inspection"), __("Job Card"), __("Result"), __("Inspector")], inspectionRows)}
					<h5>${__("Product Weight / Measurements")}</h5>${table([__("Inspection"), __("Specification"), __("Reading"), __("UOM"), __("Result")], measurementRows)}
					<h5>${__("QA Rejections")}</h5>${table([__("Inspection"), __("Specification"), __("Reject Reason"), __("Rejected Qty")], qaRows)}
					<h5>${__("Downtime Entries")}</h5>${table([__("Entry"), __("From"), __("To"), __("Reason")], downtimeRows)}
					<h5>${__("Breakdowns")}</h5>${table([__("Asset Repair"), __("Asset"), __("Failure"), __("Status"), __("Actions")], breakdownRows)}
				`);
				dialog.show();
			});
		}, __("Shift"));

		frm.add_custom_button(__("Open Process Card Workbench"), () => {
			frappe.set_route("process-card-workbench", frm.doc.name);
		});
	},
});
