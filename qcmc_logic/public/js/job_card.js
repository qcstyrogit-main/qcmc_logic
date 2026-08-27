frappe.provide("qcmc_logic.job_card");

frappe.ui.form.on("Job Card", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus === 2) return;
		setTimeout(() => qcmc_logic.job_card.fix_final_product_stock_entry_action(frm), 0);
		setTimeout(() => qcmc_logic.job_card.fix_final_product_stock_entry_action(frm), 350);

		if (frm.doc.work_order && !frm.doc.skip_material_transfer) {
			frm.add_custom_button(__("Pick List"), () => {
				qcmc_logic.job_card.make_pick_list(frm);
			}, __("Create"));
		}

		frm.add_custom_button(__("Generate QR Code"), () => {
			qcmc_logic.job_card.open_qr_dialog(frm);
		}, __("Create"));
	},
});

qcmc_logic.job_card.fix_final_product_stock_entry_action = function(frm) {
	if (
		frm.doc.docstatus !== 1 ||
		!frm.doc.track_semi_finished_goods ||
		frm.doc.finished_good
	) {
		return;
	}

	const label = __("Make Stock Entry");
	const buttons = frm.page.inner_toolbar.find("button").filter(function() {
		return $(this).text().trim() === label;
	});
	if (!buttons.length) return;

	buttons.off("click").on("click.qcmc_final_product_stock_entry", async () => {
		const pending_qty = Math.max(
			flt(frm.doc.total_completed_qty) - flt(frm.doc.manufactured_qty),
			0
		);
		if (!pending_qty) {
			frappe.msgprint(__("This Job Card has no completed quantity remaining to manufacture."));
			return;
		}

		const values = await new Promise((resolve) => {
			frappe.prompt(
				{
					fieldname: "quantity",
					fieldtype: "Float",
					label: __("Manufacture Quantity"),
					default: pending_qty,
					reqd: 1,
					description: __("Maximum completed quantity available: {0}", [pending_qty]),
				},
				(data) => resolve(data),
				__("Create Manufacture Stock Entry"),
				__("Create")
			);
		});
		if (!values) return;

		const response = await frappe.call({
			method: "qcmc_logic.api.stock_entry.make_manufacture_stock_entry_from_job_card",
			args: { job_card: frm.doc.name, qty: values.quantity },
			freeze: true,
			freeze_message: __("Creating Manufacture Stock Entry..."),
		});
		if (!response.message) return;

		const docs = frappe.model.sync(response.message);
		const stock_entry = docs?.[0] || response.message;
		frappe.set_route("Form", "Stock Entry", stock_entry.name);
	});
};

qcmc_logic.job_card.make_pick_list = async function(frm) {
	const response = await frappe.call({
		method: "qcmc_logic.api.job_card_pick_list.make_pick_list",
		args: { job_card: frm.doc.name },
		freeze: true,
		freeze_message: __("Preparing Pick List..."),
	});
	if (!response.message) return;

	const docs = frappe.model.sync(response.message);
	const pick_list = docs?.[0] || response.message;
	frappe.set_route("Form", "Pick List", pick_list.name);
};

qcmc_logic.job_card.open_qr_dialog = async function(frm) {
	const item_code = frm.doc.production_item || frm.doc.item_code || "";
	const item_values = item_code
		? await frappe.db.get_value("Item", item_code, ["item_name", "stock_uom"])
		: { message: {} };
	const item = item_values.message || {};
	const bom_values = frm.doc.bom_no
		? await frappe.db.get_value("BOM", frm.doc.bom_no, ["custom_standard_pack", "quantity"])
		: { message: {} };
	const bom = bom_values.message || {};
	const packing_defaults = await frappe.call({
		method: "qcmc_logic.api.job_card_packing_label.get_packing_label_defaults",
		args: { job_card: frm.doc.name },
	});
	const qa_code = packing_defaults.message?.qa_code || "";
	const standard_pack_quantity = flt(bom.custom_standard_pack);
	const big_pack_quantity = flt(bom.quantity);

	const dialog = new frappe.ui.Dialog({
		title: __("Generate Job Card QR — {0}", [frm.doc.name]),
		fields: [
			{
				fieldname: "pack_type",
				fieldtype: "Select",
				label: __("Pack Type"),
				options: ["Standard Pack", "Big Pack"],
				default: "Standard Pack",
				reqd: 1,
				change() {
					const pack_type = dialog.get_value("pack_type");
					dialog.set_value(
						"quantity",
						pack_type === "Big Pack" ? big_pack_quantity : standard_pack_quantity
					);
				},
			},
			{ fieldname: "qa_passed", fieldtype: "Data", label: __("QA PASSED") },
			{ fieldname: "packed_date", fieldtype: "Date", label: __("PACKED DATE") },
			{ fieldname: "inspection_date", fieldtype: "Date", label: __("INSPECTION DATE") },
			{ fieldname: "dr_no", fieldtype: "Data", label: __("DR No.") },
			{ fieldname: "packed_by", fieldtype: "Data", label: __("PACKED BY"), default: frappe.session.user_fullname },
			{
				fieldname: "customer",
				fieldtype: "Link",
				label: __("CUSTOMER"),
				options: "Customer",
			},
			{ fieldname: "lot_no", fieldtype: "Data", label: __("LOT No.") },
			{
				fieldname: "part_name",
				fieldtype: "Data",
				label: __("Part Name / No. / Code"),
				default: [item_code, item.item_name].filter(Boolean).join(" — "),
			},
			{
				fieldname: "quantity",
				fieldtype: "Float",
				label: __("Quantity"),
				default: standard_pack_quantity,
				read_only: 1,
				reqd: 1,
			},
		],
		primary_action_label: __("Generate QR Code"),
		primary_action: async (values) => {
			if (!["EPE", "EPE1"].includes(values.customer)) {
				frappe.msgprint(__("QCSC Packing Tag is available only for Customer EPE or EPE1."));
				return;
			}
			if (!qa_code) {
				frappe.msgprint(__("No EPS QA Code is configured for Item {0}.", [item_code]));
				return;
			}
			const customer_values = await frappe.db.get_value(
				"Customer",
				values.customer,
				"customer_name"
			);
			values.customer_name = customer_values.message?.customer_name || values.customer;
			if (!item_code) {
				frappe.msgprint(__("The Job Card does not have an Item Code."));
				return;
			}
			if (flt(values.quantity) <= 0) {
				frappe.msgprint(__("Quantity must be greater than zero."));
				return;
			}
			if (!item.stock_uom) {
				frappe.msgprint(__("Stock UOM is missing for Item {0}.", [item_code]));
				return;
			}
			const job_quantity = flt(frm.doc.for_quantity || frm.doc.qty || 0);
			const label_count = job_quantity / flt(values.quantity);
			if (!job_quantity || Math.abs(label_count - Math.round(label_count)) > 0.000001) {
				frappe.msgprint(__(
					"Job Card quantity {0} cannot be divided evenly by pack quantity {1}.",
					[job_quantity, values.quantity]
				));
				return;
			}

			const payload_parts = [
				item_code,
				values.quantity,
				item.stock_uom,
				frm.doc.work_order,
				frm.doc.name,
			];
			if (payload_parts.some((value) => !value || String(value).includes(";"))) {
				frappe.msgprint(__("Item Code, Quantity, UOM, and Job Order are required and cannot contain semicolons."));
				return;
			}

			await qcmc_logic.job_card.show_qr_label(
				frm,
				values,
				payload_parts.join(";"),
				item,
				Math.round(label_count),
				qa_code
			);
			dialog.hide();
		},
	});
	dialog.show();
};

qcmc_logic.job_card.show_qr_label = async function(frm, values, payload, item, label_count, qa_code) {
	const response = await frappe.call({
		method: "qcmc_logic.api.generate_code.generate_qr",
		args: { item_code: payload },
		freeze: true,
		freeze_message: __("Generating QR code..."),
	});
	if (!response.message) return;

	const escape = (value) => frappe.utils.escape_html(String(value || ""));
	const logo = `<img src="/assets/qcmc_logic/images/QC.webp" alt="QCSC Logo" style="max-width:70px;max-height:70px;object-fit:contain">`;
	const line = (label, value) => `<div style="display:grid;grid-template-columns:105px 1fr;gap:5px;align-items:end;margin:5px 0">
		<span style="font-size:10px;font-weight:700;color:#555">${escape(label)}:</span>
		<span style="min-height:15px;border-bottom:1px solid #777;font-size:11px;font-weight:600;padding:0 3px 2px">${escape(value)}</span>
	</div>`;
	const label_html = `<div style="font-family:Arial,sans-serif;color:#222;width:430px;border:4px solid #333;padding:10px;box-sizing:border-box;background:#fff">
		<div style="display:grid;grid-template-columns:78px 1fr;gap:8px;border-bottom:1px solid #999;padding-bottom:7px">
			<div style="display:flex;justify-content:center;align-items:center">${logo}</div>
			<div>
				<div style="text-align:right;font-size:9px;color:#555;white-space:nowrap">PDN-QR-042 / rev 03 / ${escape(frappe.datetime.get_today())}</div>
				<div style="text-align:center;font-size:18px;font-weight:800;letter-spacing:.6px;margin:5px 0 7px">QCSC PACKING TAG</div>
				${line(__("QA PASSED"), values.qa_passed)}
				${line(__("PACKED DATE"), values.packed_date)}
				${line(__("INSPECTION DATE"), values.inspection_date)}
				${line(__("DR No."), values.dr_no)}
				${line(__("PACKED BY"), values.packed_by)}
			</div>
		</div>
		<div style="border:3px solid #555;display:inline-block;min-width:105px;text-align:center;padding:6px 9px;margin:9px 0;font-size:20px;font-weight:800">${escape(qa_code)}</div>
		<div style="display:grid;grid-template-columns:78px 1fr;gap:8px;align-items:end;margin:1px 0 5px;font-size:10px">
			<strong>${escape(__("Customer"))}:</strong>
			<span style="font-size:12px;font-weight:700;text-align:center;border-bottom:1px solid #777;padding-bottom:2px">${escape(values.customer_name || values.customer)}</span>
		</div>
		<div style="display:grid;grid-template-columns:180px 1fr;gap:10px;align-items:start">
			<div style="text-align:center">
				<img src="${response.message}" alt="Job Card QR" style="width:175px;height:175px;display:block">
			</div>
			<div style="padding-top:2px;font-size:10px">
				<table style="width:100%;border-collapse:collapse;table-layout:fixed">
					<tr>
						<td style="width:76px;font-weight:700;padding:4px 5px 4px 0;vertical-align:top">${escape(__("Lot No."))}:</td>
						<td style="padding:4px 2px;border-bottom:1px solid #777;vertical-align:top;overflow-wrap:anywhere">${escape(values.lot_no)}</td>
					</tr>
					<tr>
						<td style="width:76px;font-weight:700;padding:7px 5px 7px 0;vertical-align:top;line-height:1.35">${escape(__("Part Name / No. / Code"))}:</td>
						<td style="padding:7px 2px;vertical-align:top;line-height:1.35;overflow-wrap:anywhere">${escape(values.part_name)}</td>
					</tr>
					<tr>
						<td style="width:76px;font-weight:700;padding:4px 5px 4px 0;vertical-align:top">${escape(__("Quantity"))}:</td>
						<td style="padding:4px 2px;border-bottom:1px solid #777;vertical-align:top;font-size:12px;font-weight:700">${escape(`${values.quantity} ${item.stock_uom}`)}</td>
					</tr>
				</table>
			</div>
		</div>
	</div>`;
	let remainder_pdf_url = "";
	const qr_dialog = new frappe.ui.Dialog({
		title: __("Job Card QR — {0}", [frm.doc.name]),
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "qr",
				options: `<div class="alert alert-info" style="margin-bottom:12px">
					<strong>${escape(__("Total labels required"))}: ${label_count}</strong><br>
					<span>${escape(__("Master Sheet is the default. Enter the calculated Copies value in Chrome after preview opens."))}</span>
				</div>${label_html}`,
			},
			{
				fieldtype: "Select",
				fieldname: "print_orientation",
				label: __("Print Orientation"),
				options: ["Portrait", "Landscape"],
				default: "Landscape",
				reqd: 1,
			},
		],
		secondary_action_label: __("Open Remainder Preview"),
		secondary_action() {
			if (remainder_pdf_url) window.open(remainder_pdf_url, "_blank");
		},
		primary_action_label: __("Open Print Preview"),
		async primary_action(print_values) {
			const pdf_window = window.open("", "_blank");
			try {
				const result = await frappe.call({
					method: "qcmc_logic.api.job_card_packing_label.generate_packing_label_pdf",
					args: {
						job_card: frm.doc.name,
						pack_type: values.pack_type,
						orientation: print_values.print_orientation,
						label_data: JSON.stringify(values),
						master_sheet: 1,
					},
					freeze: true,
					freeze_message: __("Generating {0} packing labels...", [label_count]),
				});
				const data = result.message || {};
				if (!data.pdf_base64) throw new Error(__("The PDF response was empty."));
				let copy_message = __("Set Copies to {0} in Chrome.", [data.copies_required]);
				if (data.remaining_labels) {
					copy_message = __("Print the master tab with {0} copies, then print the remainder tab with 1 copy for the remaining {1} labels.", [data.copies_required, data.remaining_labels]);
				}
				frappe.show_alert({ message: copy_message, indicator: "blue" }, 20);
				const to_pdf_url = (encoded, filename) => {
					const binary = atob(encoded);
					const bytes = new Uint8Array(binary.length);
					for (let index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index);
					return URL.createObjectURL(new File([bytes], filename, { type: "application/pdf" }));
				};
				const pdf_url = to_pdf_url(data.pdf_base64, data.filename);
				pdf_window.location.href = pdf_url;
				setTimeout(() => URL.revokeObjectURL(pdf_url), 300000);
				if (data.remaining_pdf_base64) {
					const remainder_url = to_pdf_url(data.remaining_pdf_base64, data.remainder_filename);
					remainder_pdf_url = remainder_url;
					qr_dialog.get_secondary_btn().removeClass("hide");
					setTimeout(() => URL.revokeObjectURL(remainder_url), 300000);
				} else {
					remainder_pdf_url = "";
					qr_dialog.get_secondary_btn().addClass("hide");
				}
			} catch (error) {
				if (pdf_window) pdf_window.close();
				throw error;
			}
		},
	});
	qr_dialog.show();
	qr_dialog.get_secondary_btn().addClass("hide");
};
