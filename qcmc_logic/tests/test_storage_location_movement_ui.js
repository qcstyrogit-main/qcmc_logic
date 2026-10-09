const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const context = {
	console,
	frappe: { treeview_settings: {}, utils: { escape_html: String } },
	__: (value) => value,
	format_number: (value) => Number(value).toFixed(3),
};
vm.createContext(context);
vm.runInContext(
	fs.readFileSync(
		path.resolve(
			__dirname,
			"../qcmc_logics/doctype/storage_location/storage_location_tree.js"
		),
		"utf8"
	),
	context
);

assert.match(context.physical_count_adjustment_display(900, "PCS"), /text-success/);
assert.match(context.physical_count_adjustment_display(-5000, "PCS"), /text-danger/);
assert.match(context.physical_count_adjustment_display(0, "PCS"), /color: #2490ef/);
assert.match(context.physical_count_adjustment_display(0, "PCS"), /No adjustment/);

console.log("Storage Location movement color test passed");
