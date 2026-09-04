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

function qcmc_configure_physical_count_grid(frm, for_recon, show_calculation_fields) {
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
	grid.set_column_disp("variance", show_calculation_fields);
	grid.update_docfield_property("variance", "hidden", !show_calculation_fields);
	grid.cannot_add_rows = true;
	grid.cannot_delete_rows = true;
	grid.grid_pagination.page_index = 1;
	grid.refresh();
}

async function qcmc_load_reconciliation_review(frm) {
	if (frm.__qcmc_review_loading) return;
	frm.__qcmc_review_loading = true;
	try {
		const response = await frappe.call({
			method: "qcmc_logic.api.stock_reconciliation.get_pcount_reconciliation_review",
			args: { reconciliation_id: frm.doc.name },
		});
		frm.__qcmc_reconciliation_review = response.message || {};
	} finally {
		frm.__qcmc_review_loading = false;
	}
}

function qcmc_show_reconciliation_review(frm) {
	const review = frm.__qcmc_reconciliation_review || {};
	const rows = Array.from(new Map(
		(review.unscanned_balances || []).map((row) => [row.storage_location, row])
	).values());
	const body = rows.length
		? rows.reduce((markup, row, index) => {
			if (index % 2 === 0) markup += "<tr>";
			markup += `<td>${frappe.utils.escape_html(row.location_name || row.storage_location || "")}</td>`;
			if (index % 2 === 1 || index === rows.length - 1) {
				if (index === rows.length - 1 && rows.length % 2 === 1) markup += "<td></td>";
				markup += "</tr>";
			}
			return markup;
		}, "")
		: `<tr><td colspan="2" class="text-muted text-center">${__("No uncounted Storage Locations found.")}</td></tr>`;
	const report_html = `
		<div class="qcmc-unscanned-stock-report">
			<h3 class="visible-print">${__("Warehouse Stock With No Counts")}</h3>
			<div style="margin-bottom:12px">
				<b>${__("Stock Reconciliation")}:</b> ${frappe.utils.escape_html(frm.doc.name || "")}<br>
				<b>${__("Warehouse")}:</b> ${frappe.utils.escape_html(review.warehouse || "")}<br>
				<b>${__("Locations with no count")}:</b> ${review.location_without_count_count || 0}
			</div>
			<div class="table-responsive"><table class="table table-bordered">
				<thead><tr><th>${__("Storage Location")}</th><th>${__("Storage Location")}</th></tr></thead>
				<tbody>${body}</tbody>
			</table></div>
		</div>`;
	const dialog = new frappe.ui.Dialog({
		title: __("Existing Stock Not Counted"),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "report", options: report_html }],
		primary_action_label: __("Print"),
		primary_action() {
			const print_window = window.open("", "_blank", "width=1100,height=800");
			if (!print_window) {
				frappe.msgprint(__("Please allow pop-ups to print this report."));
				return;
			}
			print_window.document.write(`<!doctype html><html><head><title>${frappe.utils.escape_html(frm.doc.name || "Physical Count Review")}</title>
				<style>body{font-family:Arial,sans-serif;font-size:11px;margin:24px}h3{margin:0 0 12px}table{width:100%;border-collapse:collapse}th,td{border:1px solid #999;padding:6px;text-align:left;width:50%}th{background:#eee}.text-right{text-align:right}@page{size:portrait;margin:12mm}</style>
				</head><body>${report_html}<div style="margin-top:18px">${__("Printed")}: ${frappe.datetime.str_to_user(frappe.datetime.now_datetime())}</div><script>window.onload=function(){window.print();}<\/script></body></html>`);
			print_window.document.close();
		},
	});
	dialog.show();
}

frappe.ui.form.on("Stock Reconciliation", {
	custom_physical_count(frm) {
		if (cint(frm.doc.custom_physical_count)) {
			frm.set_value("purpose", "Stock Reconciliation");
		}
	},

	async refresh(frm) {
		const physical_count = cint(frm.doc.custom_physical_count);
		const show_calculation_fields = ["For Recon", "Close Inventory"].includes(frm.doc.workflow_state);
		const draft_physical_count = physical_count && frm.doc.docstatus === 0;
		const for_recon = draft_physical_count && frm.doc.workflow_state === "For Recon";
		frm.set_df_property("items", "read_only", physical_count);
		frm.set_df_property("custom_physical_count_results", "read_only", !for_recon);
		if (frm.fields_dict.items && frm.fields_dict.items.grid) {
			frm.fields_dict.items.grid.update_docfield_property("location", "hidden", physical_count);
			frm.fields_dict.items.grid.set_column_disp("quantity_difference", show_calculation_fields);
			frm.fields_dict.items.grid.update_docfield_property("quantity_difference", "hidden", !show_calculation_fields);
		}
		qcmc_configure_physical_count_grid(frm, for_recon, show_calculation_fields);
		frm.refresh_field("items");
		frm.toggle_display("custom_physical_count_results_section", physical_count);
		frm.toggle_display("custom_physical_count_results_summary", false);
		if (!physical_count) return;
		if (draft_physical_count) {
			await qcmc_load_reconciliation_review(frm);
			frm.add_custom_button(__("Show Warehouse Stock With No Counts"), () => {
				qcmc_show_reconciliation_review(frm);
			}, __("Physical Count"));
		}
		frm.add_custom_button(__("Refresh Physical Count Details"), async () => {
			await frappe.call({
				method: "qcmc_logic.api.stock_reconciliation.refresh_pcount_summary",
				args: { reconciliation_id: frm.doc.name },
				freeze: true,
				freeze_message: __("Refreshing Physical Count Details..."),
			});
			await frm.reload_doc();
		}, __("Physical Count"));
		frm.add_custom_button(
			frm.__qcmc_show_audit_history ? __("Show Effective Counts") : __("View Audit History"),
			() => {
				frm.__qcmc_show_audit_history = !frm.__qcmc_show_audit_history;
				qcmc_configure_physical_count_grid(frm, for_recon, show_calculation_fields);
				frm.refresh();
			},
			__("Physical Count"),
		);
	},
});
