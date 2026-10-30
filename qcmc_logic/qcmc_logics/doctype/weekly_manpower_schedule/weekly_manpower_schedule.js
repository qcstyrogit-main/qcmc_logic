frappe.ui.form.on("Weekly Manpower Schedule", {
	onload(frm) {
		const default_company = frappe.defaults.get_user_default("Company");
		if (frm.is_new() && default_company && !frm.doc.company) {
			frm.set_value("company", default_company);
		}
	},

	setup(frm) {
		frm.set_query("section", () => ({
			query: "qcmc_logic.qcmc_logics.doctype.weekly_manpower_schedule.weekly_manpower_schedule.get_cost_centers",
			filters: { company: frm.doc.company },
		}));
	},

	refresh(frm) {
		frm.remove_custom_button(__("Open Schedule Workbench"));
		frm.add_custom_button(__("Open Schedule Workbench"), () => open_schedule_workbench(frm));
	},

	week_start(frm) {
		if (frm.doc.week_start) {
			frm.set_value("week_end", frappe.datetime.add_days(frm.doc.week_start, 6));
		}
	},
});

async function open_schedule_workbench(frm) {
	if (!frm.doc.company || !frm.doc.section || !frm.doc.week_start) {
		frappe.msgprint(__("Select Company, Section, and Week Start before opening the Schedule Workbench."));
		return;
	}
	if (frm.is_new() || frm.is_dirty()) {
		if (frm.doc.docstatus !== 0 || frm.doc.workflow_state !== "Draft") {
			frappe.msgprint(__("Only a Draft schedule can be saved before opening the Schedule Workbench."));
			return;
		}
		await frm.save();
		if (frm.is_new() || frm.is_dirty()) return;
	}
	frappe.set_route("weekly-manpower-schedule-workbench", frm.doc.name);
}