frappe.ui.form.on("Stock Reconciliation", {
	custom_physical_count(frm) {
		if (cint(frm.doc.custom_physical_count)) {
			frm.set_value("purpose", "Stock Reconciliation");
		}
	},

	refresh(frm) {
		const physical_count = cint(frm.doc.custom_physical_count);
		frm.set_df_property("items", "read_only", physical_count);
		if (frm.fields_dict.items && frm.fields_dict.items.grid) {
			frm.fields_dict.items.grid.update_docfield_property("location", "hidden", physical_count);
		}
		frm.refresh_field("items");
		frm.toggle_display("custom_physical_count_results_section", physical_count);
		if (!physical_count || !frm.fields_dict.custom_physical_count_results_summary) return;

		const rows = frm.doc.custom_physical_count_results || [];
		const latest_by_location = new Map();
		rows.forEach((row, position) => {
			const key = [
				row.item_code || "", row.warehouse || "",
				row.location || row.inventory_location || row.inventory_location_id || "",
				row.batch_no || "", row.serial_no || "", row.uom || "",
			].join("\u001f");
			const rank = `${row.submitted_at || row.counted_at || ""}|${String(row.idx || position).padStart(10, "0")}`;
			const current = latest_by_location.get(key);
			if (!current || rank >= current.rank) latest_by_location.set(key, { rank, row });
		});
		const effective_rows = Array.from(latest_by_location.values()).map((value) => value.row);
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
	},
});
