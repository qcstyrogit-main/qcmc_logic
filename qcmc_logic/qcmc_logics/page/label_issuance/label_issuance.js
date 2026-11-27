frappe.pages["label-issuance"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({parent: wrapper, title: __("Label Issuance"), single_column: true});
	wrapper.label_issuance = new LabelIssuance(page);
};

const liEscape = value => frappe.utils.escape_html(String(value ?? ""));
const liNumber = value => format_number(value || 0, null, 2);

class LabelIssuance {
	constructor(page) {
		this.page = page;
		this.rows = [];
		this.root = $(page.body).empty();
		this.page.set_primary_action(__("Print All"), () => this.print_all(), "print");
		this.root.html(`<style>
			.label-issuance-filters{display:flex;align-items:flex-end;gap:12px;flex-wrap:wrap;padding:12px;margin-bottom:12px;border:1px solid var(--border-color);border-radius:8px;background:var(--fg-color)}
			.label-issuance-filter{min-width:210px;flex:0 1 240px}.label-issuance-actions{display:flex;gap:8px;padding-bottom:5px}
		</style><div class="label-issuance-filters">
			<div class="label-issuance-filter" data-filter="company"></div>
			<div class="label-issuance-filter" data-filter="plant_floor"></div>
			<div class="label-issuance-filter" data-filter="shift_type"></div>
			<div class="label-issuance-filter" data-filter="shift_date"></div>
			<div class="label-issuance-actions"><button class="btn btn-default" data-action="refresh"><i class="fa fa-refresh"></i> ${__("Refresh")}</button><button class="btn btn-primary" data-action="print-all"><i class="fa fa-print"></i> ${__("Print All")}</button></div>
		</div><div class="label-issuance-state text-muted">${__("Select a Plant Floor to load labels.")}</div><div class="label-issuance-grid"></div>`);
		this.build_filters();
		this.root.on("click", "[data-action='print']", event => this.print_row(event.currentTarget.dataset.job));
		this.root.on("click", "[data-action='refresh']", () => this.refresh());
		this.root.on("click", "[data-action='print-all']", () => this.print_all());
		this.root.on("input change", "[data-row-field]", event => this.update_row(event.currentTarget));
	}

	build_filters() {
		const make = (fieldname, label, fieldtype, options, required, default_value) => frappe.ui.form.make_control({
			parent: this.root.find(`[data-filter="${fieldname}"]`),
			df: {fieldname, label: __(label), fieldtype, options, reqd: required ? 1 : 0, default: default_value, change: () => this.refresh()},
			render_input: true,
		});
		this.company = make("company", "Company", "Link", "Company", true, frappe.defaults.get_user_default("Company"));
		this.company.df.change = () => {
			this.plant_floor.set_value("");
			this.rows = [];
			this.render();
			this.root.find(".label-issuance-state").text(__("Select a Plant Floor to load labels."));
		};
		this.company.refresh();
		this.plant_floor = make("plant_floor", "Section", "Link", "Plant Floor", true);
		this.plant_floor.df.get_query = () => ({filters: {company: this.company.get_value() || ""}});
		this.shift_type = make("shift_type", "Shift", "Link", "Shift Type", false);
		this.shift_date = make("shift_date", "Date", "Date", null, true, frappe.datetime.get_today());
	}

	async refresh() {
		if (!this.company.get_value() || !this.plant_floor.get_value() || !this.shift_date.get_value()) return;
		this.root.find(".label-issuance-state").text(__("Loading label issuance rows…"));
		try {
			const response = await frappe.call({method: "qcmc_logic.api.label_issuance.get_rows", type: "GET", args: {
				company: this.company.get_value(), plant_floor: this.plant_floor.get_value(), shift_date: this.shift_date.get_value(), shift_type: this.shift_type.get_value() || null,
			}});
			this.rows = (response.message || []).map(row => ({...row, standard_to_print: 0, big_to_print: 0}));
			this.render();
		} catch (error) {
			this.rows = [];
			this.root.find(".label-issuance-state").text(__("Could not load label issuance rows."));
			this.root.find(".label-issuance-grid").empty();
		}
	}

	render() {
		this.root.find(".label-issuance-state").text(this.rows.length ? __("{0} Job Card(s)", [this.rows.length]) : __("No Process Card jobs match these filters."));
		const headers = [__("Machine"), __("PC No"), __("JO No"), __("JO Qty"), __("Product Code"), __("Product Description"), __("Material Lot No."), __("Roll Lot No."), __("VAC Lot No."), __("Sorted By"), __("Customer Name"), __("UOM"), __("Std Pack Qty"), __("Big Pack Qty"), __("Max Std Labels"), __("Max Big Labels"), __("Std Pack to Print"), __("Big Pack to Print"), __("SOPH"), __("Completed Qty"), __("Action")];
		const body = this.rows.map((row, index) => `<tr>
			<td>${liEscape(row.machine)}</td>
			<td><a href="/app/process-card/${encodeURIComponent(row.process_card)}">${liEscape(row.process_card)}</a></td>
			<td><a href="/app/job-card/${encodeURIComponent(row.job_card)}">${liEscape(row.job_card)}</a></td>
			<td class="text-right">${liNumber(row.job_qty)}</td><td>${liEscape(row.product_code)}</td><td>${liEscape(row.product_description)}</td>
			<td><input class="form-control input-sm li-lot" data-row-field="material_lot_no" data-row="${index}" value="${liEscape(row.material_lot_no)}"></td>
			<td><input class="form-control input-sm li-lot" data-row-field="roll_lot_no" data-row="${index}" value="${liEscape(row.roll_lot_no)}"></td>
			<td><input class="form-control input-sm li-lot" data-row-field="vac_lot_no" data-row="${index}" value="${liEscape(row.vac_lot_no)}"></td>
			<td><input class="form-control input-sm li-lot" data-row-field="sorted_by" data-row="${index}" value="${liEscape(row.sorted_by)}"></td>
			<td>${liEscape(row.customer_name)}</td><td>${liEscape(row.uom)}</td>
			<td class="text-right">${liNumber(row.standard_pack_qty)}</td><td class="text-right">${liNumber(row.big_pack_qty)}</td>
			<td class="text-right li-count">${liEscape(row.standard_labels)}</td><td class="text-right li-count">${liEscape(row.big_labels)}</td>
			<td><input class="form-control input-sm li-qty" type="number" min="0" max="${liEscape(row.standard_labels)}" step="1" data-row-field="standard_to_print" data-row="${index}" value="${liEscape(row.standard_to_print)}"></td>
			<td><input class="form-control input-sm li-qty" type="number" min="0" max="${liEscape(row.big_labels)}" step="1" data-row-field="big_to_print" data-row="${index}" value="${liEscape(row.big_to_print)}"></td>
			<td class="text-right">${liNumber(row.soph)}</td><td class="text-right">${liNumber(row.completed_qty)}</td>
			<td><button class="btn btn-xs btn-primary" data-action="print" data-job="${liEscape(row.job_card)}"><i class="fa fa-print"></i> ${__("Print")}</button></td>
		</tr>`).join("");
		this.root.find(".label-issuance-grid").html(`<style>
			.label-issuance-grid{margin-top:12px;overflow:auto;max-height:calc(100vh - 250px);border:1px solid var(--border-color);border-radius:8px}
			.label-issuance-grid table{margin:0;min-width:1450px}.label-issuance-grid thead th{position:sticky;top:0;z-index:2;background:var(--subtle-fg);white-space:nowrap}
			.label-issuance-grid td{vertical-align:middle;white-space:nowrap}.label-issuance-grid .li-count{background:#dff3fb;font-weight:600}.label-issuance-grid .li-lot{min-width:130px}.label-issuance-grid .li-qty{width:90px;background:#dff3fb}
		</style><table class="table table-bordered table-hover"><thead><tr>${headers.map(label => `<th>${liEscape(label)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`);
	}

	update_row(input) {
		const row = this.rows[Number(input.dataset.row)];
		if (!row) return;
		const field = input.dataset.rowField;
		if (["material_lot_no", "roll_lot_no", "vac_lot_no", "sorted_by"].includes(field)) {
			row[field] = input.value;
			return;
		}
		const maximum = field === "standard_to_print" ? row.standard_labels : row.big_labels;
		const value = Math.max(0, Math.min(maximum, Math.floor(Number(input.value) || 0)));
		row[field] = value;
		input.value = value;
	}

	async ensure_print_module() {
		if (window.qcmc_logic?.job_card?.open_qr_dialog) return;
		await new Promise((resolve, reject) => frappe.require("/assets/qcmc_logic/js/job_card.js", resolve, reject));
	}

	async print_job(job_card) {
		await this.ensure_print_module();
		await frappe.model.with_doc("Job Card", job_card);
		return qcmc_logic.job_card.open_qr_dialog({doc: frappe.get_doc("Job Card", job_card)});
	}

	print_row(job_card) {
		const row = this.rows.find(item => item.job_card === job_card);
		if (!row || (!row.standard_to_print && !row.big_to_print)) {
			return frappe.msgprint(__("Enter a Standard Pack or Big Pack quantity to print first."));
		}
		this.open_bulk_dialog([row], __("Print Packing Labels — {0}", [job_card]));
	}

	print_all() {
		const selected = this.rows.filter(row => row.standard_to_print || row.big_to_print);
		if (!selected.length) return frappe.msgprint(__("Enter quantities in Standard Pack to Print or Big Pack to Print first."));
		this.open_bulk_dialog(selected, __("Print All Packing Labels"));
	}

	open_bulk_dialog(rows, title) {
		const dialog = new frappe.ui.Dialog({
			title,
			fields: [
				{fieldname: "orientation", fieldtype: "Select", label: __("Orientation"), options: "Portrait\nLandscape", default: "Portrait", reqd: 1},
				{fieldname: "master_sheet", fieldtype: "Check", label: __("Master Sheet"), default: 1},
			],
			primary_action_label: __("Generate All"),
			primary_action: async values => {
				dialog.disable_primary_action();
				try {
					for (let index = 0; index < rows.length; index++) {
						dialog.set_title(__("Generating {0} of {1}", [index + 1, rows.length]));
						await this.generate_row_labels(rows[index], values);
					}
					dialog.hide();
					frappe.show_alert({message: __("All label PDFs were generated."), indicator: "green"});
				} finally {
					dialog.enable_primary_action();
					dialog.set_title(title);
				}
			},
		});
		dialog.show();
	}

	async generate_row_labels(row, values) {
		if (row.standard_to_print) await this.generate_label(row, {...values, pack_type: "Standard Pack", label_count: row.standard_to_print});
		if (row.big_to_print) await this.generate_label(row, {...values, pack_type: "Big Pack", label_count: row.big_to_print});
	}

	async generate_label(row, values) {
		const defaults = (await frappe.call({
			method: "qcmc_logic.api.job_card_packing_label.get_packing_label_defaults",
			args: {job_card: row.job_card},
		})).message || {};
		const response = (await frappe.call({
			method: "qcmc_logic.api.job_card_packing_label.generate_packing_label_pdf",
			args: {
				job_card: row.job_card,
				pack_type: values.pack_type,
				orientation: values.orientation,
				master_sheet: values.master_sheet ? 1 : 0,
				label_count: values.label_count,
				label_data: {
					customer: defaults.customer,
					label_customer: defaults.customer_name,
					part_name: `${row.product_code || ""} ${row.product_description || ""}`.trim(),
					lot_no: row.vac_lot_no || row.roll_lot_no || row.material_lot_no,
					po_client: defaults.po_client,
					delivery_date: defaults.delivery_date,
					packed_date: frappe.datetime.get_today(),
					packed_by: frappe.session.user_fullname,
				},
			},
		})).message;
		this.download_pdf(response.pdf_base64, response.filename);
		if (response.remaining_pdf_base64) this.download_pdf(response.remaining_pdf_base64, response.remainder_filename);
	}

	download_pdf(encoded, filename) {
		const bytes = Uint8Array.from(atob(encoded), character => character.charCodeAt(0));
		const url = URL.createObjectURL(new Blob([bytes], {type: "application/pdf"}));
		const anchor = Object.assign(document.createElement("a"), {href: url, download: filename});
		document.body.appendChild(anchor); anchor.click(); anchor.remove();
		setTimeout(() => URL.revokeObjectURL(url), 1000);
	}
}
