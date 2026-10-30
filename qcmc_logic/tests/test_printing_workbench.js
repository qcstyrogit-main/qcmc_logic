// Run with node; exercises the actual page class without a browser or site.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const calls = [];
const preview = {closed: false, close() { this.closed = true; }, location: {replace(url) { this.url = url; }}};
const context = {
	frappe: {pages: {"delivery-note-printing-workbench": {}}, call: options => calls.push(options)},
	__: value => value,
	window: {open: () => preview}
};
vm.createContext(context);
const source = path.join(__dirname, "../qcmc_logics/page/delivery_note_printing_workbench/delivery_note_printing_workbench.js");
vm.runInContext(fs.readFileSync(source, "utf8") + "\nthis.Workbench = DeliveryNotePrintingWorkbench;", context);
const workbench = Object.create(context.Workbench.prototype);
workbench.$summary = {text() {}};
workbench.render = () => {};
workbench.filters = {company: "QC", delivery_date: "2026-10-29"};
workbench.refresh();
const pending = calls.pop();
workbench.filters.company = "";
workbench.refresh();
assert.equal(workbench.rows.length, 0);
pending.callback({message: {rows: [{delivery_note: "STALE"}]}});
assert.equal(workbench.rows.length, 0, "old requests must not repopulate cleared filters");
console.log("PASS: clearing filters clears rows and ignores pending responses");

workbench.rows = [{delivery_note: "DN", invoices: [{name: "SI"}]}];
workbench.create_invoice("DN");
const verify = calls.pop();
assert.ok(verify.method.endsWith("verify_sales_invoice_for_preview"));
assert.equal(verify.args.sales_invoice, "SI");
assert.equal(calls.length, 0, "existing invoices must not trigger creation");
verify.callback({message: {verified: true, sales_invoice: "SI"}});
assert.ok(preview.location.url.includes("name=SI"));
assert.ok(!preview.location.url.includes("format="));
console.log("PASS: existing invoice is verified and previewed with the default format");

workbench.create_invoice("DN");
calls.pop().error();
assert.equal(preview.closed, true);
console.log("PASS: failed verification closes the preview window");
