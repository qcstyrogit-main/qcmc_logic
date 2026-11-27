const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const forms = {};
const calls = [];
const routes = [];
const context = {
    __: text => text,
    frappe: {
        ui: {form: {on: (name, handlers) => { forms[name] = handlers; }}},
        session: {user: "Administrator"},
        datetime: {get_today: () => "2026-11-25"},
        defaults: {get_user_default: () => "Co"},
        query_reports: {},
        confirm: async (message, action) => action(),
        call: async args => { calls.push(args); return {message: {batch: "batch", rows: [{demand_period_method: "Rolling Days"}]}}; },
        set_route: (...args) => routes.push(args),
        msgprint: message => { throw new Error(message); }
    }
};
vm.createContext(context);
vm.runInContext(fs.readFileSync("qcmc_logic/public/js/dynamic_reorder.js", "utf8"), context);
vm.runInContext(fs.readFileSync("qcmc_logic/qcmc_logics/report/reorder_analysis/reorder_analysis.js", "utf8"), context);
const queries = {};
forms["Reorder Policy Mapping"].setup({doc: {company: "Co", warehouses: [{warehouse: "A"}, {warehouse: "B"}]},
    set_query: (...args) => { queries[args[0]] = args.at(-1); }});
assert.equal(queries.warehouse().filters.company, "Co");
assert.equal(queries.warehouse().filters.is_group, 0);
assert.equal(queries.warehouse().filters.disabled, 0);
assert.deepEqual(Array.from(queries.replenishment_warehouse().filters.name[1]), ["A", "B"]);
let buttons = [];
forms["Reorder Calculation History"].refresh({doc: {mapping: "M", status: "Preview"},
    dashboard: {set_headline_alert() {}}, add_custom_button: label => buttons.push(label)});
assert.equal(buttons.length, 0);
let savePreview;
context.frappe.query_reports["Reorder Analysis"].onload({
    page: {add_inner_button: (label, action) => { savePreview = action; }},
    get_filter_values: () => ({company: "Co", mapping: "M", item_code: "I"})
});
(async () => {
    await savePreview();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].args.mapping, "M");
    assert.equal(calls[0].args.period_method, null);
    assert.equal(calls[0].args.warehouse, undefined);
    assert.equal(routes[0][1], "Reorder Calculation History");
    console.log("PASS: warehouse filters, destination scope, preview-only history and mapping-based preview using policy period");
})().catch(error => { console.error(error); process.exitCode = 1; });
