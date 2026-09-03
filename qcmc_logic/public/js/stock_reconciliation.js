function qcmc_physical_count_key(row) {
	return [
		row.item_code || "", row.warehouse || "",
		row.location || row.inventory_location || row.inventory_location_id || "",
		row.batch_no || "", row.serial_no || "", row.uom || "",
	].join("\u001f");
}

function qcmc_latest_physical_count_rows(rows) {
	const latest = new Map();
	(rows || []).forEach((row, position) => {
		const key = qcmc_physical_count_key(row);
		const rank = `${row.submitted_at || row.counted_at || ""}|${String(row.idx || position).padStart(10, "0")}`;
		const current = latest.get(key);
		if (!current || rank >= current.rank) latest.set(key, { rank, row });
	});
	return Array.from(latest.values()).map((value) => value.row);
}

function qcmc_configure_physical_count_grid(frm, for_recon) {
	const grid = frm.fields_dict.custom_physical_count_results?.grid;
	if (!grid) return;

	if (!grid._qcmc_original_get_data) {
		grid._qcmc_original_get_data = grid.get_data.bind(grid);
		grid.get_data = function (filter_field) {
			const data = grid._qcmc_original_get_data(filter_field) || [];
			if (frm.__qcmc_show_audit_history) return data;
			const effective_names = new Set(
				qcmc_latest_physical_count_rows(frm.doc.custom_physical_count_results || [])
					.map((row) => row.name)
			);
			return data.filter((row) => effective_names.has(row.name));
		};
	}

	grid.update_docfield_property("physical_count", "read_only", !for_recon);
	grid.cannot_add_rows = true;
	grid.cannot_delete_rows = true;
	grid.grid_pagination.page_index = 1;
	grid.refresh();
}

frappe.ui.form.on("Stock Reconciliation", {
	custom_physical_count(frm) {
		if (cint(frm.doc.custom_physical_count)) {
			frm.set_value("purpose", "Stock Reconciliation");
		}
	},

	refresh(frm) {
		const physical_count = cint(frm.doc.custom_physical_count);
		const for_recon = physical_count && frm.doc.docstatus === 0 && frm.doc.workflow_state === "For Recon";
		frm.set_df_property("items", "read_only", physical_count);
		frm.set_df_property("custom_physical_count_results", "read_only", !for_recon);
		if (frm.fields_dict.items && frm.fields_dict.items.grid) {
			frm.fields_dict.items.grid.update_docfield_property("location", "hidden", physical_count);
		}
		qcmc_configure_physical_count_grid(frm, for_recon);
		frm.refresh_field("items");
		frm.toggle_display("custom_physical_count_results_section", physical_count);
		if (!physical_count || !frm.fields_dict.custom_physical_count_results_summary) return;

		const rows = frm.doc.custom_physical_count_results || [];
		const effective_rows = qcmc_latest_physical_count_rows(rows);
		const positive = effective_rows.reduce((total, row) => total + Math.max(flt(row.variance), 0), 0);
		const negative = effective_rows.reduce((total, row) => total + Math.min(flt(row.variance), 0), 0);
		const last = rows.reduce((value, row) => {
			return !value || (row.submitted_at || "") > value ? row.submitted_at : value;
		}, "");
		frm.fields_dict.custom_physical_count_results_summary.$wrapper.html(`
			<div class="alert alert-info" style="margin-bottom:12px">
				<b>${__("Counted rows")}:</b> ${effective_rows.length}
				&nbsp; | &nbsp;<b>${__("Positive variance")}:</b> ${format_number(positive)}
				&nbsp; | &nbsp;<b>${__("Negative variance")}:</b> ${format_number(negative)}
				&nbsp; | &nbsp;<b>${__("Last submission")}:</b> ${last ? frappe.datetime.str_to_user(last) : __("None")}
			</div>
		`);
		frm.add_custom_button(__("Refresh Physical Count Details"), async () => {
			await frappe.call({
				method: "qcmc_logic.api.stock_reconciliation.refresh_pcount_summary",
				args: { reconciliation_id: frm.doc.name },
				freeze: true,
				freeze_message: __("Refreshing Physical Count Details..."),
			});
			await frm.reload_doc();
		});
		frm.add_custom_button(
			frm.__qcmc_show_audit_history ? __("Show Effective Counts") : __("View Audit History"),
			() => {
				frm.__qcmc_show_audit_history = !frm.__qcmc_show_audit_history;
				qcmc_configure_physical_count_grid(frm, for_recon);
				frm.refresh();
			},
		);
	},
});
