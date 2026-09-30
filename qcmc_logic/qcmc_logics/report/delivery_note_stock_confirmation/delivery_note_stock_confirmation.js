frappe.query_reports["Delivery Note Stock Confirmation"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company")},
		{fieldname: "delivery_date", label: __("Delivery Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today()},
		{fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse", get_query: () => ({filters: {company: frappe.query_report.get_filter_value("company"), is_group: 0, custom_is_province: 0}})}
	],
	onload(report) {
		if (can_logistics_review()) {
			report.page.add_inner_button(__("Logistics Remarks"), () => logistics_remarks(report));
		}
		if (can_sales_approve()) {
			report.page.add_inner_button(__("Proceed to DR"), () => proceed_to_dr(report));
		}
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "item_code" && data) {
			const color = flt(data.actual_qty) >= flt(data.qty) ? "green" : "red";
			return `<span class="indicator ${color}">${value}</span>`;
		}
		return value;
	},
	get_datatable_options(options) { options.checkboxColumn = true; return options; }
};

function logistics_selected_rows(report) {
	return (report.datatable?.rowmanager?.getCheckedRows() || []).map(index => report.data[index]).filter(Boolean);
}

function can_logistics_review() {
	return frappe.session.user === "Administrator" || frappe.user.has_role("Stock Confirm User");
}

function can_sales_approve() {
	return frappe.session.user === "Administrator" || frappe.user.has_role("Sales Coordinator");
}

function logistics_remarks(report) {
	const delivery_notes = [...new Set(logistics_selected_rows(report).map(row => row.delivery_note))];
	if (delivery_notes.length !== 1) return frappe.msgprint(__("Select rows from exactly one Delivery Note."));
	frappe.call({
		method: "qcmc_logic.qcmc_logics.report.delivery_note_stock_confirmation.delivery_note_stock_confirmation.get_delivery_note_items",
		args: {delivery_note: delivery_notes[0]},
		callback: response => {
			if (response.exc) return;
			with_logistics_reason_options(reason_options => {
				const dialog = new frappe.ui.Dialog({
					title: __("Logistics Remarks"),
					size: "extra-large",
					fields: [
						{fieldname: "reason_help", fieldtype: "HTML", options: reason_options.help_html},
						{
							fieldname: "items",
							label: __("Items"),
							fieldtype: "Table",
							cannot_add_rows: true,
							cannot_delete_rows: true,
							in_place_edit: true,
							data: (response.message || []).map(row => ({
								dn_detail: row.dn_detail,
								item_code: row.item_code,
								item_name: row.item_name,
								original_qty: row.original_qty,
								logistics_proposed_qty: row.logistics_proposed_qty,
								logistics_proposed_date: row.logistics_proposed_date,
								logistics_reason: row.logistics_reason || "",
								logistics_remarks: row.logistics_remarks || ""
							})),
							fields: [
								{fieldname: "dn_detail", fieldtype: "Data", hidden: 1},
								{fieldname: "item_code", label: __("Item"), fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 1},
								{fieldname: "item_name", label: __("Name"), fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 2},
								{fieldname: "original_qty", label: __("Orig Qty"), fieldtype: "Float", read_only: 1, in_list_view: 1, columns: 1},
								{fieldname: "logistics_proposed_qty", label: __("Prop Qty"), fieldtype: "Float", in_list_view: 1, columns: 1},
								{fieldname: "logistics_proposed_date", label: __("Prop Date"), fieldtype: "Date", in_list_view: 1, columns: 1},
								{fieldname: "logistics_reason", label: __("Reason"), fieldtype: "Select", options: reason_options.options, in_list_view: 1, columns: 1},
								{fieldname: "logistics_remarks", label: __("Remarks"), fieldtype: "Small Text", in_list_view: 1, columns: 3}
							]
						}
					],
					primary_action_label: __("Save Logistics Remarks"),
					primary_action(values) {
						frappe.call({
							method: "qcmc_logic.qcmc_logics.report.delivery_note_stock_confirmation.delivery_note_stock_confirmation.save_logistics_remarks",
							args: {delivery_note: delivery_notes[0], items: values.items || []},
							freeze: true,
							freeze_message: __("Saving logistics recommendations..."),
							callback: r => {
								if (r.exc) return;
								frappe.msgprint(r.message);
								dialog.hide();
								report.refresh();
							}
						});
					}
				});
				dialog.show();
			});
		}
	});
}

function proceed_to_dr(report) {
	const delivery_notes = [...new Set(logistics_selected_rows(report).map(row => row.delivery_note))];
	if (delivery_notes.length !== 1) return frappe.msgprint(__("Select rows from exactly one Delivery Note."));
	frappe.call({
		method: "qcmc_logic.qcmc_logics.report.delivery_note_stock_confirmation.delivery_note_stock_confirmation.get_dr_printing_review_items",
		args: {delivery_note: delivery_notes[0]},
		callback: response => {
			if (response.exc) return;
			const dialog = new frappe.ui.Dialog({
				title: __("Proceed to DR"),
				size: "extra-large",
				fields: [
					{
						fieldname: "instructions",
						fieldtype: "HTML",
						options: `<p class="text-muted">${__("Review Logistics recommendations. Sales-approved quantity/date below is what will be applied to the Delivery Note. Use Remove only when Sales explicitly approves removing the item from this DR.")}</p>`
					},
					{
						fieldname: "items",
						label: __("Items"),
						fieldtype: "Table",
						cannot_add_rows: true,
						cannot_delete_rows: true,
						in_place_edit: true,
						data: response.message || [],
						fields: [
							{fieldname: "dn_detail", fieldtype: "Data", hidden: 1},
							{fieldname: "item_code", label: __("Item"), fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 1},
							{fieldname: "item_name", label: __("Name"), fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 2},
							{fieldname: "original_qty", label: __("Orig Qty"), fieldtype: "Float", read_only: 1, in_list_view: 1, columns: 1},
							{fieldname: "logistics_proposed_qty", label: __("Prop Qty"), fieldtype: "Float", read_only: 1, in_list_view: 1, columns: 1},
							{fieldname: "logistics_proposed_date", label: __("Prop Date"), fieldtype: "Date", read_only: 1, in_list_view: 1, columns: 1},
							{fieldname: "logistics_reason", label: __("Reason"), fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 1},
							{fieldname: "logistics_remarks", label: __("Remarks"), fieldtype: "Small Text", read_only: 1, in_list_view: 1, columns: 2},
							{fieldname: "available_reschedule_dates", label: __("Existing Dates"), fieldtype: "Data", read_only: 1},
							{fieldname: "approved_qty", label: __("Appr Qty"), fieldtype: "Float", in_list_view: 1, columns: 1},
							{fieldname: "approved_date", label: __("Appr Date"), fieldtype: "Date", in_list_view: 1, columns: 1},
							{fieldname: "remove_item", label: __("Remove"), fieldtype: "Check", in_list_view: 1, columns: 1}
						]
					}
				],
				primary_action_label: __("Proceed to DR"),
				primary_action(values) {
					frappe.call({
						method: "qcmc_logic.qcmc_logics.report.delivery_note_stock_confirmation.delivery_note_stock_confirmation.proceed_to_dr_printing",
						args: {delivery_note: delivery_notes[0], items: values.items || []},
						freeze: true,
						freeze_message: __("Applying Sales-approved DR values..."),
						callback: r => {
							if (r.exc) return;
							frappe.msgprint(r.message);
							dialog.hide();
							report.refresh();
						}
					});
				}
			});
			dialog.show();
		}
	});
}

function with_logistics_reason_options(callback) {
	frappe.call({
		method: "qcmc_logic.qcmc_logics.report.delivery_note_stock_confirmation.delivery_note_stock_confirmation.get_logistics_reason_options",
		callback: r => callback(r.message || fallback_logistics_reason_options())
	});
}

function fallback_logistics_reason_options() {
	return {
		options: "\nOK\nTO\nCR\nSA\nOR\nND\nSE",
		default_remarks: __("OK - Good to go"),
		help_html: `<div class="text-muted small">
			<b>OK</b> - ${__("Good to go")}<br>
			<b>TO</b> - ${__("Truck Overload")}<br>
			<b>CR</b> - ${__("Customer Request")}<br>
			<b>SA</b> - ${__("Stock Availability")}<br>
			<b>OR</b> - ${__("Off Route")}<br>
			<b>ND</b> - ${__("Next Delivery Date")}<br>
			<b>SE</b> - ${__("Sales Error")}
		</div>`
	};
}
