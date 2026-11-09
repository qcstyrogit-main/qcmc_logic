const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

async function main() {
    const routes = [], buttons = [];
    const context = {
        __: value => value,
        frappe: {
            query_reports: {}, treeview_settings: {}, defaults: {get_user_default: () => "WH"},
            set_route: (...args) => routes.push(args),
            db: {get_value: async () => ({message: {custom_warehouse: "WH"}})},
        },
    };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../qcmc_logics/report/storage_location_summary/storage_location_summary.js"), "utf8"), context);
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../qcmc_logics/doctype/storage_location/storage_location_tree.js"), "utf8"), context);
    const report = context.frappe.query_reports["Storage Location Summary"];
    assert.equal(report.tree, true);
    assert.equal(report.filters.find(filter => filter.fieldname === "warehouse").reqd, 1);
    assert.equal(report.formatter(0, {}, {fieldname: "stock_qty"}, {stock_qty: null}, () => "0"), "", "Mixed-UOM summaries must not display a false zero quantity");
    assert.equal(report.formatter(12, {}, {fieldname: "stock_qty"}, {stock_qty: 12}, value => String(value)), "12");
    report.onload({
        get_filter_value: () => "WH",
        page: {add_inner_button: (label, action) => buttons.push({label, action})},
    });
    buttons[0].action();
    assert.equal(routes.at(-1).join("/"), "Tree/Storage Location");

    const summary = context.frappe.treeview_settings["Storage Location"].toolbar.find(action => action.label === "Stock Summary");
    assert.equal(summary.condition({is_root: true}), false);
    const branch = {is_root: false, data: {value: "RACK-2"}};
    assert.equal(summary.condition(branch), true);
    summary.click(branch);
    await new Promise(setImmediate);
    assert.equal(routes.at(-1).join("/"), "query-report/Storage Location Summary");
    assert.equal(context.frappe.route_options.storage_location, "RACK-2");
    assert.equal(context.frappe.route_options.warehouse, "WH");
    console.log("Storage Location Summary tree navigation and mixed-UOM display checks passed");
}

main().catch(error => {console.error(error); process.exitCode = 1;});
