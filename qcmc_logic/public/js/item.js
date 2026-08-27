frappe.ui.form.on("Item", {
	setup(frm) {
		frm.set_query("custom_eps_process_main_item", () => {
			return {
				filters: {
					custom_is_eps_process_main_item: 1,
					disabled: 0,
				},
			};
		});
	},

	refresh(frm) {
		if (frm.is_new() || !frm.doc.is_stock_item) return;
		frm.add_custom_button(__("Material Scanner QR"), () => {
			open_material_scanner_qr_dialog(frm);
		}, __("Scanner"));
	},

	custom_is_eps_process_main_item(frm) {
		if (cint(frm.doc.custom_is_eps_process_main_item)) {
			frm.set_value("custom_eps_process_main_item", "");
		}
	},

	validate(frm) {
		if (
			frm.doc.custom_eps_process_main_item
			&& frm.doc.custom_eps_process_main_item === frm.doc.name
		) {
			frappe.throw(__("EPS Process Main Item cannot point to the same Item."));
		}
	},
});

function open_material_scanner_qr_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Create Material Scanner QR — {0}", [frm.doc.name]),
		fields: [
			{
				fieldname: "quantity",
				fieldtype: "Float",
				label: __("Quantity"),
				reqd: 1,
			},
			{
				fieldname: "uom",
				fieldtype: "Link",
				options: "UOM",
				label: __("UOM"),
				default: frm.doc.stock_uom,
				reqd: 1,
			},
			{
				fieldname: "batch_serial",
				fieldtype: frm.doc.has_batch_no ? "Link" : "Data",
				options: frm.doc.has_batch_no ? "Batch" : undefined,
				label: frm.doc.has_serial_no
					? __("Serial Number")
					: __("Batch / Serial (Optional)"),
				description: __("Leave blank when the Item does not require a batch or serial number."),
			},
		],
		primary_action_label: __("Generate QR"),
		primary_action: async (values) => {
			if (flt(values.quantity) <= 0) {
				frappe.msgprint(__("Quantity must be greater than zero."));
				return;
			}
			const parts = [frm.doc.name, values.quantity, values.uom, values.batch_serial || ""];
			if (parts.some((value) => String(value).includes(";"))) {
				frappe.msgprint(__("Item, UOM, and batch/serial values cannot contain a semicolon."));
				return;
			}
			await show_material_scanner_qr(frm, parts.join(";"));
			dialog.hide();
		},
	});
	if (frm.doc.has_batch_no) {
		dialog.fields_dict.batch_serial.get_query = () => ({
			filters: { item: frm.doc.name, disabled: 0 },
		});
	}
	dialog.show();
}

async function show_material_scanner_qr(frm, payload) {
	const response = await frappe.call({
		method: "qcmc_logic.api.generate_code.generate_qr",
		args: { item_code: payload },
		freeze: true,
		freeze_message: __("Generating QR code..."),
	});
	if (!response.message) return;

	const item_code = frappe.utils.escape_html(frm.doc.name);
	const item_name = frappe.utils.escape_html(frm.doc.item_name || "");
	const escaped_payload = frappe.utils.escape_html(payload);
	const label_html = `<div style="text-align:center;padding:18px">
		<div style="font-size:20px;font-weight:700">${item_code}</div>
		<div style="font-size:13px;margin:4px 0 10px">${item_name}</div>
		<img src="${response.message}" alt="Material QR" style="width:260px;height:260px">
		<div style="font-family:monospace;font-size:13px;font-weight:700;margin-top:10px;overflow-wrap:anywhere">${escaped_payload}</div>
	</div>`;
	const qr_dialog = new frappe.ui.Dialog({
		title: __("Material Scanner QR — {0}", [frm.doc.name]),
		fields: [{ fieldtype: "HTML", fieldname: "qr", options: label_html }],
		primary_action_label: __("Print QR Label"),
		primary_action() {
			const print_window = window.open("", "_blank", "width=520,height=680");
			print_window.document.write(`<html><head><title>${item_code}</title></head><body>${label_html}<script>window.onload=function(){window.print();}<\/script></body></html>`);
			print_window.document.close();
		},
	});
	qr_dialog.show();
}
