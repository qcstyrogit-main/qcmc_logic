const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const handlers = {};
const context = {
	console,
	Map,
	Set,
	String,
	frappe: {
		ui: { form: { on: (doctype, events) => { handlers[doctype] = events; } } },
		utils: { escape_html: String },
	},
	__: (value) => value,
	cint: (value) => Number(value || 0),
	flt: (value) => Number(value || 0),
	format_number: String,
};
vm.createContext(context);
vm.runInContext(
	fs.readFileSync(path.resolve(__dirname, "../public/js/stock_reconciliation.js"), "utf8"),
	context,
);

const labels = [];
const grid = {
	update_docfield_property() {},
	set_column_disp() {},
};
const frm = {
	doc: {
		custom_physical_count: 1,
		docstatus: 1,
		workflow_state: "Submitted",
		custom_physical_count_results: [],
	},
	fields_dict: { items: { grid } },
	set_df_property() {},
	refresh_field() {},
	toggle_display() {},
	add_custom_button(label) { labels.push(label); },
};

(async () => {
	await handlers["Stock Reconciliation"].refresh(frm);
	assert(!labels.includes("Refresh Physical Count Details"));
	assert(!labels.includes("View Audit History"));
	assert(!labels.includes("Show Effective Counts"));
	console.log("Stock Reconciliation hidden-menu test passed");
})().catch((error) => {
	console.error(error);
	process.exit(1);
});
