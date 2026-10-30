frappe.listview_settings["Weekly Manpower Schedule"] = {
	onload(listview) {
		const default_company = frappe.defaults.get_user_default("Company");
		if (!default_company || !listview.filter_area) return;

		const company_filter_exists = listview.filter_area
			.get()
			.some((filter) => filter[0] === "Weekly Manpower Schedule" && filter[1] === "company");
		if (!company_filter_exists) {
			listview.filter_area.add("Weekly Manpower Schedule", "company", "=", default_company);
		}
	},
};
