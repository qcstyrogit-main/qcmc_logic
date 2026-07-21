const APPROVED_PRODUCTION_WAREHOUSES = [
	"RMFS - Guyong",
	"Recycling - Guyong",
	"RMFS - Sta Clara",
	"Recycling - Sta Clara",
	"Recycling - MC1",
	"Recycling - MC2",
	"RMFS - MC1",
	"RMFS - MC2",
];

frappe.ui.form.on("Production Plantilla", {
	setup(frm) {
		frm.set_query("warehouse", () => ({
			filters: {
				company: frm.doc.company,
				warehouse_name: ["in", APPROVED_PRODUCTION_WAREHOUSES],
				disabled: 0,
			},
		}));
		frm.set_query("section", () => ({
			filters: {
				company: frm.doc.company,
				warehouse: frm.doc.warehouse,
			},
		}));
		frm.set_query("machine", () => ({
			filters: {
				plant_floor: frm.doc.section,
				disabled: 0,
			},
		}));
	},
	company(frm) {
		frm.set_value("warehouse", null);
		frm.set_value("section", null);
		frm.set_value("machine", null);
	},
	warehouse(frm) {
		frm.set_value("section", null);
		frm.set_value("machine", null);
	},
	section(frm) {
		frm.set_value("machine", null);
	},
});
