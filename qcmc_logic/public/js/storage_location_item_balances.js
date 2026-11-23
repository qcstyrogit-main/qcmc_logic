// Shared Storage Location Tree View item balance dialog.
// Both Tree View and the Storage Location form use this exact implementation.
frappe.provide("qcmc_logic.storage_location");

function physical_count_adjustment_display(value, uom) {
	const adjustment = Number(value) || 0;
	const escape = (text) => frappe.utils.escape_html(String(text ?? ""));
	if (adjustment === 0) {
		return `<small style="color: #2490ef;">${__("No adjustment")}</small>`;
	}

	const color_class = adjustment > 0 ? "text-success" : "text-danger";
	const sign = adjustment > 0 ? "+" : "";
	return `<small class="${color_class}">${__("Variance")}: ${sign}${escape(format_number(adjustment, null, 3))} ${escape(uom)}</small>`;
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

							const quantity_display = is_count
								? `<strong>${__("Confirmed {0}", [escape(quantity(row.counted_quantity))])}</strong> ${escape(row.uom)}<br>${physical_count_adjustment_display(row.quantity, row.uom)}`
								: `<strong class="${Number(row.quantity) < 0 ? "text-danger" : "text-success"}">${Number(row.quantity) > 0 ? "+" : ""}${escape(quantity(row.quantity))}</strong> ${escape(row.uom)}`;
							const source = row.source_location
								? escape(row.source_location)
								: row.source_warehouse
									? `${escape(row.source_warehouse)} <small class="text-muted">(${__("Source Warehouse")})</small>`
									: row.source_label
										? escape(row.source_label)
										: `<small class="text-muted">${__("Source not recorded")}</small>`;
							const destination = row.target_location
								? escape(row.target_location)
								: row.target_warehouse
									? `${escape(row.target_warehouse)} <small class="text-muted">(${__("Warehouse — destination bin not yet recorded")})</small>`
									: row.target_label
										? escape(row.target_label)
										: `<small class="text-muted">${__("Destination not recorded")}</small>`;
							const movement_route = `${source} → ${destination}`;
							return `<tr>
							<td><strong>${escape(row.item_code)}</strong><br><small>${escape(row.item_name)}</small></td>
							<td class="text-right">${quantity_display}</td>
							<td>${location_movement_reference_display(row)}</td>
							<td>${movement_route}</td>
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


function location_movement_reference_display(row) {
    const escape = value => frappe.utils.escape_html(String(value ?? ''));
    const link = (doctype, name) => doctype && name
        ? `<a href="${escape(frappe.utils.get_form_link(doctype, name))}" target="_blank" rel="noopener noreferrer"><strong>${escape(name)}</strong></a>`
        : escape(name || '—');
    if (row.movement_type === 'Storage Allocation' && row.source_doctype && row.source_document) {
        const label = {
            'Purchase Receipt': 'Warehouse Receiving Report',
            'Delivery Note': 'Delivery Note Return',
        }[row.source_doctype] || row.source_doctype;
        return `<strong>${escape(__(label))}</strong><br><small>${link(row.source_doctype, row.source_document)}</small>`
            + `<br><small>${escape(__('Storage Allocation'))}: ${link('Storage Allocation', row.reference_name)}</small>`;
    }
    const doctype = {
        'Storage Allocation': 'Storage Allocation',
        'Warehouse Receiving Report': 'Purchase Receipt',
        'Location Transfer': 'Location Transfer',
        'Physical Count': 'Stock Reconciliation',
        'Physical Count Scan': 'Stock Reconciliation',
        'Warehouse Transfer OUT': 'Warehouse Transfer',
        'Delivery Note OUT': 'Delivery Note',
    }[row.movement_type];
    return `<strong>${escape(__(row.movement_type))}</strong><br><small>${link(doctype, row.reference_name)}</small>`;
}

qcmc_logic.storage_location.show_item_balances = show_storage_location_item_balances;
