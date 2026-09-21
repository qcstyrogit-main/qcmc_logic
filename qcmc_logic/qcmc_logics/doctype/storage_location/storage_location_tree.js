frappe.treeview_settings["Storage Location"] = {
	get_tree_nodes:
		"qcmc_logic.qcmc_logics.doctype.storage_location.storage_location.get_storage_location_tree_nodes",
	add_tree_node: "frappe.desk.treeview.add_node",
	root_label: __("Storage Locations"),
	get_tree_root: true,
	post_render(treeview) {
		restore_storage_location_tree_state(treeview);
		treeview.tree.wrapper.on("click.qcmc-tree-state", ".tree-link", () => {
			setTimeout(() => save_storage_location_tree_state(treeview), 150);
		});
	},
	toolbar: [
		{
			label: __("Edit"),
			condition(node) {
				return !node.is_root && frappe.model.can_write("Storage Location");
			},
			click(node) {
				show_storage_location_edit_dialog(node);
			},
		},
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
			options: "Building\nFloor\nMezza\nBlock\nLot\nRoom\nAisle\nRack\nRow\nLayer\nCube\nPallet\nBin\nOpen Area\nOther",
			reqd: 1,
		},
	],
	ignore_fields: ["parent_storage_location"],
};

const STORAGE_LOCATION_TREE_STATE_KEY = "qcmc-storage-location-tree-state";

function get_storage_location_treeview() {
	return frappe.views.trees["Storage Location"];
}

function save_storage_location_tree_state(treeview, renamed = {}) {
	const tree = treeview && treeview.tree;
	if (!tree) return;

	const expanded = Object.values(tree.nodes)
		.filter((node) => !node.is_root && node.expanded)
		.map((node) => renamed[node.label] || node.label);
	const selected = tree.get_selected_node();
	const state = {
		expanded,
		selected: selected && !selected.is_root ? renamed[selected.label] || selected.label : null,
	};
	sessionStorage.setItem(STORAGE_LOCATION_TREE_STATE_KEY, JSON.stringify(state));
}

async function restore_storage_location_tree_state(treeview) {
	let state;
	try {
		state = JSON.parse(sessionStorage.getItem(STORAGE_LOCATION_TREE_STATE_KEY) || "null");
	} catch (error) {
		sessionStorage.removeItem(STORAGE_LOCATION_TREE_STATE_KEY);
		return;
	}
	if (!state || !treeview.tree) return;

	const tree = treeview.tree;
	const pending = new Set(state.expanded || []);
	for (let attempt = 0; attempt < 100 && pending.size; attempt += 1) {
		let progressed = false;
		for (const label of Array.from(pending)) {
			const node = tree.nodes[label];
			if (!node) continue;
			if (!node.loaded) await tree.load_children(node);
			else if (!node.expanded) tree.expand_node(node, false);
			pending.delete(label);
			progressed = true;
		}
		if (!progressed) await new Promise((resolve) => setTimeout(resolve, 50));
	}

	const selected = state.selected && tree.nodes[state.selected];
	if (selected) {
		tree.set_selected_node(selected);
		tree.select_link(selected);
		tree.show_toolbar(selected);
		selected.$tree_link[0]?.scrollIntoView({ block: "nearest" });
	}
}

function refresh_storage_location_tree(old_name, new_name) {
	const treeview = get_storage_location_treeview();
	if (!treeview) return;
	save_storage_location_tree_state(
		treeview,
		old_name && new_name && old_name !== new_name ? { [old_name]: new_name } : {}
	);
	treeview.make_tree();
}

function show_storage_location_edit_dialog(node) {
	frappe.db.get_doc("Storage Location", node.label).then((location) => {
		const dialog = new frappe.ui.Dialog({
			title: __("Edit Storage Location"),
			fields: [
				{
					fieldtype: "Check",
					fieldname: "is_group",
					label: __("Is Group"),
					description: __("Groups can contain child storage locations."),
					default: location.is_group,
				},
				{
					fieldtype: "Data",
					fieldname: "location_code",
					label: __("Location Code"),
					reqd: 1,
					default: location.location_code,
				},
				{
					fieldtype: "Data",
					fieldname: "location_name",
					label: __("Location Name"),
					reqd: 1,
					default: location.location_name,
				},
				{
					fieldtype: "Select",
					fieldname: "location_type",
					label: __("Location Type"),
					options: "Building\nFloor\nMezza\nBlock\nLot\nRoom\nAisle\nRack\nRow\nLayer\nCube\nPallet\nBin\nOpen Area\nOther",
					reqd: 1,
					default: location.location_type,
				},
				{
					fieldtype: "Link",
					fieldname: "custom_warehouse",
					label: __("Warehouse"),
					options: "Warehouse",
					reqd: 1,
					default: location.custom_warehouse,
				},
			],
			primary_action_label: __("Update"),
			primary_action(values) {
				dialog.disable_primary_action();
				frappe.call({
					method: "qcmc_logic.qcmc_logics.doctype.storage_location.storage_location.update_storage_location_from_tree",
					args: {
						storage_location: location.name,
						...values,
					},
					freeze: true,
					freeze_message: __("Updating Storage Location..."),
				}).then((response) => {
					const updated = response.message || {};
					dialog.hide();
					frappe.show_alert({ message: __("Storage Location updated"), indicator: "green" });
					refresh_storage_location_tree(location.name, updated.name);
				}).catch(() => dialog.enable_primary_action());
			},
		});
		dialog.show();
	});
}

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
		const movement_details = data.movement_details || [];
		const capacity = data.capacity_summary || {};
		const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
		const quantity = (value) => format_number(value, null, 3);
		const capacity_quantity = (value) => `${escape(quantity(value))}${capacity.uom ? ` ${escape(capacity.uom)}` : ""}`;
		const capacity_value = (value) => value === null || value === undefined
			? __("Not configured")
			: capacity_quantity(value);
		const available_capacity = capacity.no_capacity_restriction
			? __("Unlimited")
			: capacity_value(capacity.available_capacity);
		const capacity_source = capacity.source_name
			? `${capacity.source}: ${capacity.source_name}`
			: __("No capacity source configured");
		const datetime = (value) => value ? frappe.datetime.str_to_user(value) : "—";
		const rows = balances.length
			? balances
					.map(
						(row) => `<tr>
							<td><strong>${escape(row.item_code)}</strong><br><small>${escape(row.item_name)}</small></td>
							<td class="text-right"><strong>${escape(quantity(row.actual_qty))}</strong> ${escape(row.uom)}</td>
							<td>${escape(row.last_movement || "—")}</td>
						</tr>`
					)
					.join("")
			: `<tr><td colspan="3" class="text-muted text-center">${__("No current stock in this location.")}</td></tr>`;
		const detail_rows = movement_details.length
			? movement_details
					.map(
						(row) => {
							const is_count = row.movement_type === "Physical Count";
							const reference_doctype = {
								"Warehouse Allocation": "Warehouse Allocation",
								"Location Transfer": "Location Transfer",
								"Physical Count": "Stock Reconciliation",
							}[row.movement_type];
							const reference_url = reference_doctype && row.reference_name
								? frappe.utils.get_form_link(reference_doctype, row.reference_name)
								: "";
							const reference_display = reference_url
								? `<a href="${escape(reference_url)}" target="_blank" rel="noopener noreferrer"><strong>${escape(row.reference_name)}</strong></a>`
								: escape(row.reference_name || "—");
							const quantity_display = is_count
								? `<strong>${__("Confirmed {0}", [escape(quantity(row.counted_quantity))])}</strong> ${escape(row.uom)}<br><small class="text-muted">${Number(row.quantity) === 0 ? __("No adjustment") : `${__("Variance")}: ${Number(row.quantity) > 0 ? "+" : ""}${escape(quantity(row.quantity))} ${escape(row.uom)}`}</small>`
								: `<strong class="${Number(row.quantity) < 0 ? "text-danger" : "text-success"}">${Number(row.quantity) > 0 ? "+" : ""}${escape(quantity(row.quantity))}</strong> ${escape(row.uom)}`;
							return `<tr>
							<td><strong>${escape(row.item_code)}</strong><br><small>${escape(row.item_name)}</small></td>
							<td class="text-right">${quantity_display}</td>
							<td><strong>${escape(row.movement_type)}</strong><br><small>${reference_display}</small></td>
							<td>${escape(row.source_location || "—")} → ${escape(row.target_location || "—")}</td>
							<td>${escape(row.performed_by || "—")}<br><small>${escape(row.device_id || "")}</small></td>
							<td>${escape(datetime(row.movement_time))}</td>
						</tr>`;
						}
					)
					.join("")
			: `<tr><td colspan="6" class="text-muted text-center">${__("No location movement history found.")}</td></tr>`;
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
					<div class="storage-location-capacity-summary mb-3">
						<div class="storage-location-capacity-card">
							<div class="text-muted">${__("Capacity")}</div>
							<strong>${capacity.no_capacity_restriction ? __("Unlimited") : capacity_value(capacity.capacity)}</strong>
						</div>
						<div class="storage-location-capacity-card">
							<div class="text-muted">${__("Used Capacity")}</div>
							<strong>${capacity_quantity(capacity.used_capacity || 0)}</strong>
						</div>
						<div class="storage-location-capacity-card">
							<div class="text-muted">${__("Available Capacity")}</div>
							<strong>${available_capacity}</strong>
						</div>
						<div class="storage-location-capacity-card">
							<div class="text-muted">${__("Capacity Source")}</div>
							<strong>${escape(capacity_source)}</strong>
						</div>
					</div>
					<div class="table-responsive"><table class="table table-bordered table-hover">
						<thead><tr><th>${__("Item")}</th><th class="text-right">${__("Current Quantity")}</th><th>${__("Last Movement")}</th></tr></thead>
						<tbody>${rows}</tbody>
					</table></div>
					<h5 class="mt-4 mb-2">${__("Location Movement History")}</h5>
					<style>
						.storage-location-capacity-summary {
							display: grid;
							grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
							gap: 10px;
						}
						.storage-location-capacity-card {
							border: 1px solid var(--border-color, #d1d8dd);
							border-radius: 8px;
							padding: 10px 12px;
							background: var(--card-bg, #fff);
						}
						.storage-location-capacity-card strong {
							display: block;
							margin-top: 4px;
							font-size: 15px;
						}
						.storage-allocation-details-scroll {
							max-height: min(420px, 48vh);
							overflow: auto;
							border: 1px solid var(--border-color, #d1d8dd);
						}
						.storage-allocation-details-scroll table { margin-bottom: 0; }
						.storage-allocation-details-scroll thead th {
							position: sticky;
							top: 0;
							z-index: 1;
							background: var(--card-bg, #fff);
						}
					</style>
					<div class="table-responsive storage-allocation-details-scroll"><table class="table table-bordered table-hover table-sm">
						<thead><tr>
							<th>${__("Item")}</th>
							<th class="text-right">${__("Quantity")}</th>
							<th>${__("Movement / Reference")}</th>
							<th>${__("From → To")}</th>
							<th>${__("User / Scanner")}</th>
							<th>${__("Movement Time")}</th>
						</tr></thead>
						<tbody>${detail_rows}</tbody>
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
						refresh_storage_location_tree(node.label, values.location_code);
					}).catch(() => dialog.enable_primary_action());
				},
			});
			dialog.show();
		});
}
