frappe.query_reports["Sales Order Delivery Scheduling"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company")},
		{fieldname: "delivery_date", label: __("Delivery Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today()},
		{
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			get_query: () => ({filters: {company: frappe.query_report.get_filter_value("company"), is_group: 0, custom_is_province: 0}})
		}
	],
	onload(report) {
		report.page.add_inner_button(__("Update Delivery Dates"), () => update_delivery_dates(report));
		report.page.add_inner_button(__("Adjust Quantity"), () => adjust_quantity(report));
		report.page.add_inner_button(__("Create DR for Confirmation"), () => create_delivery_notes(report));
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "item_code" && data) {
			const color = flt(data.actual_qty) >= flt(data.available_qty) ? "green" : "red";
			return `<span class="indicator ${color}">${value}</span>`;
		}
		return value;
	},
	get_datatable_options(options) { options.checkboxColumn = true; return options; }
};

function selected_rows(report) {
	return (report.datatable?.rowmanager?.getCheckedRows() || []).map(index => report.data[index]).filter(Boolean);
}

function update_delivery_dates(report) {
	const rows = selected_rows(report);
	if (!rows.length) return frappe.msgprint(__("Select at least one item row."));
	frappe.prompt({fieldname: "delivery_date", label: __("New Delivery Date"), fieldtype: "Date", reqd: 1}, values => {
		frappe.call({method: "qcmc_logic.qcmc_logics.report.sales_order_delivery_scheduling.sales_order_delivery_scheduling.update_delivery_dates", args: {so_details: rows.map(row => row.so_detail), delivery_date: values.delivery_date}, callback: r => { if (!r.exc) { frappe.msgprint(r.message); report.refresh(); } }});
	}, __("Update"), __("Apply"));
}

function adjust_quantity(report) {
	const rows = selected_rows(report);
	if (rows.length !== 1) return frappe.msgprint(__("Select exactly one schedule row."));
	const row = rows[0];
	frappe.call({
		method: "qcmc_logic.qcmc_logics.report.sales_order_delivery_scheduling.sales_order_delivery_scheduling.get_related_schedules",
		args: {source_so_detail: row.so_detail},
		callback: r => {
			const schedules = r.message || [];
			if (!schedules.length) return frappe.msgprint(__("No other delivery schedules were found for this item."));
			const schedule_options = schedules.map(schedule => `${schedule.delivery_date} - Qty ${format_number(schedule.qty)} / Available ${format_number(schedule.available_qty)}`);
			const schedules_by_label = {};
			schedules.forEach((schedule, index) => {
				schedules_by_label[schedule_options[index]] = schedule.name;
			});
			frappe.prompt([
				{
					fieldname: "instruction",
					fieldtype: "HTML",
					options: `<p class="text-muted">${__("This does not change delivery dates. It only moves quantity between existing schedules for the same item. Use Update Delivery Dates if you need to move the whole schedule row to another date.")}</p>`
				},
				{fieldname: "new_qty", label: __("New Quantity for {0}").replace("{0}", row.delivery_date), fieldtype: "Float", reqd: 1, default: row.qty},
				{fieldname: "target_schedule", label: __("Schedule to receive/supply the quantity difference"), fieldtype: "Select", options: schedule_options.join("\n"), reqd: 1},
				{fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text", reqd: 1}
			], values => {
				frappe.call({
					method: "qcmc_logic.qcmc_logics.report.sales_order_delivery_scheduling.sales_order_delivery_scheduling.adjust_scheduled_quantity",
					args: {
						source_so_detail: row.so_detail,
						target_so_detail: schedules_by_label[values.target_schedule],
						new_qty: values.new_qty,
						remarks: values.remarks
					},
					freeze: true,
					freeze_message: __("Rebalancing quantities between existing schedules..."),
					callback: r => { if (!r.exc) { frappe.msgprint(r.message); report.refresh(); } }
				});
			}, __("Rebalance Scheduled Quantity"), __("Apply"));
		}
	});
}

function create_delivery_notes(report) {
	const so_details = [...new Set(selected_rows(report).map(row => row.so_detail))];
	if (!so_details.length) return frappe.msgprint(__("Select at least one Sales Order item."));
	frappe.confirm(__("Create one Delivery Note per selected Sales Order and submit for Stock Confirmation?"), () => {
		frappe.call({method: "qcmc_logic.qcmc_logics.report.sales_order_delivery_scheduling.sales_order_delivery_scheduling.create_delivery_notes", args: {so_details}, freeze: true, freeze_message: __("Creating Delivery Notes..."), callback: r => { if (!r.exc) { frappe.msgprint(r.message); report.refresh(); } }});
	});
}
