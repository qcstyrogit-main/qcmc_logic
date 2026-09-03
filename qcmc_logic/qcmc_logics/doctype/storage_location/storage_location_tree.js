frappe.treeview_settings["Storage Location"] = {
	get_tree_nodes:
		"qcmc_logic.qcmc_logics.doctype.storage_location.storage_location.get_storage_location_tree_nodes",
	add_tree_node: "frappe.desk.treeview.add_node",
	root_label: __("Storage Locations"),
	get_tree_root: true,
	toolbar: [
		{
			label: __("View Item Balances"),
			condition(node) {
				return Boolean(
					!node.is_root &&
						node.data &&
						node.data.value &&
						!Number(node.data.expandable)
				);
			},
			click(node) {
				show_storage_location_item_balances(node.data.value);
			},
		},
		{
			label: __("Rename"),
			condition(node) {
				return !node.is_root && frappe.model.can_write("Storage Location");
			},
			click(node) {
				show_storage_location_rename_dialog(node);
			},
			btnClass: "hidden-xs",
		},
		{
			label: __("Print Child QR Labels"),
			condition(node) {
				return !node.is_root && node.data && node.data.value;
			},
			click(node) {
				const location = encodeURIComponent(node.data.value);
				window.open(
					`/storage_location_qr?parent_location=${location}`,
					"_blank",
					"noopener"
				);
			},
		},
	],
	extend_toolbar: true,
	fields: [
		{
			fieldtype: "Check",
			fieldname: "is_group",
			label: __("Is Group"),
			description: __("Groups can contain child storage locations."),
		},
		{
			fieldtype: "Data",
			fieldname: "location_code",
			label: __("Location Code"),
			reqd: 1,
		},
		{
			fieldtype: "Data",
			fieldname: "location_name",
			label: __("Location Name"),
			reqd: 1,
		},
		{
			fieldtype: "Select",
			fieldname: "location_type",
			label: __("Location Type"),
			options: "Building\nFloor\nMezza\nBlock\nLot\nRoom\nAisle\nRack\nRow\nLayer\nColumn\nBin\nOpen Area\nOther",
			reqd: 1,
		},
	],
	ignore_fields: ["parent_storage_location"],
};

function show_storage_location_item_balances(storage_location) {
	frappe.call({
		method:
			"qcmc_logic.qcmc_logics.doctype.storage_location.storage_location.get_storage_location_item_balances",
		args: { storage_location },
		freeze: true,
		freeze_message: __("Loading item balances..."),
	}).then((response) => {
		const data = response.message || {};
		const balances = data.balances || [];
		const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
		const quantity = (value) => format_number(value, null, 3);
		const rows = balances.length
			? balances
					.map(
						(row) => `<tr>
							<td><strong>${escape(row.item_code)}</strong><br><small>${escape(row.item_name)}</small></td>
							<td>${escape(row.batch_no || "—")}</td>
							<td class="text-right"><strong>${escape(quantity(row.actual_qty))}</strong> ${escape(row.uom)}</td>
							<td>${escape(row.last_movement || "—")}</td>
						</tr>`
					)
					.join("")
			: `<tr><td colspan="4" class="text-muted text-center">${__("No positive item balances in this location.")}</td></tr>`;
		const dialog = new frappe.ui.Dialog({
			title: __("Item Balances — {0}", [data.location_code || storage_location]),
			size: "extra-large",
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "balances",
					options: `<div class="mb-3">
						<strong>${escape(data.location_name || data.location_code)}</strong><br>
						<span class="text-muted">${escape(data.warehouse)} · ${escape(data.item_count || 0)} ${__("item(s)")}</span>
					</div>
					<div class="table-responsive"><table class="table table-bordered table-hover">
						<thead><tr><th>${__("Item")}</th><th>${__("Batch")}</th><th class="text-right">${__("Available Quantity")}</th><th>${__("Last Movement")}</th></tr></thead>
						<tbody>${rows}</tbody>
					</table></div>`,
				},
			],
		});
		dialog.show();
	});
}

function show_storage_location_rename_dialog(node) {
	frappe.db
		.get_value("Storage Location", node.label, ["location_code", "location_name"])
		.then((response) => {
			const location = response.message || {};
			const dialog = new frappe.ui.Dialog({
				title: __("Rename {0}", [node.label]),
				fields: [
					{
						fieldname: "location_code",
						fieldtype: "Data",
						label: __("New Location Code"),
						reqd: 1,
						default: location.location_code || node.label,
					},
					{
						fieldname: "location_name",
						fieldtype: "Data",
						label: __("New Location Name"),
						reqd: 1,
						default: location.location_name,
					},
				],
				primary_action_label: __("Rename"),
				primary_action(values) {
					dialog.disable_primary_action();
					frappe.call({
						method: "qcmc_logic.qcmc_logics.doctype.storage_location.storage_location.rename_storage_location",
						args: {
							storage_location: node.label,
							location_code: values.location_code,
							location_name: values.location_name,
						},
						freeze: true,
						freeze_message: __("Renaming Storage Location..."),
					}).then(() => {
						dialog.hide();
						frappe.show_alert({ message: __("Storage Location renamed"), indicator: "green" });
						frappe.views.trees["Storage Location"].make_tree();
					}).catch(() => dialog.enable_primary_action());
				},
			});
			dialog.show();
		});
}
