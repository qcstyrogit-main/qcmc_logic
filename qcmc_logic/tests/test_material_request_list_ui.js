const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

async function run() {
    let previousOnload = 0, refreshes = 0, failSave = false, change;
    const calls = [], alerts = [];
    let checkboxStyles;
    const checkbox = {
        closest(selector) {
            assert.equal(selector, ".checkbox");
            return {css(styles) {checkboxStyles=styles;}};
        },
        values: {checked: false, disabled: false},
        prop(key, value) {
            if (arguments.length === 1) return this.values[key];
            this.values[key] = value;
            return this;
        },
        on(event, callback) {assert.equal(event, "change");change=callback;return this;},
    };
    const frappe = {
        show_alert(value) {alerts.push(value);},
        listview_settings: {"Material Request": {onload() {previousOnload++;}, marker: true}},
        async call(args) {
            calls.push(args);
            if (args.method.endsWith("get_history_preference")) return {message: 1};
            if (args.method.endsWith("get_previous_approval_count")) return {message: 0};
            if (failSave) throw new Error("Save failed");
            assert.ok(args.args.enabled === 0 || args.args.enabled === 1);
            return {message: args.args.enabled};
        },
    };
    const listview = {
        start: 100, last_args: "cached", count_upper_bound: 1001,
        page: {
            fields_dict: {material_request_type: {get_value() {return "Purchase";}}},
            show_form() {},
            add_check() {return checkbox;},
            add_field() {throw new Error("Preference must not register as a database filter");},
        },
        get_filters_for_args() {
            // Model Frappe's enumeration of toolbar fields plus a stale saved filter.
            return Object.entries(this.page.fields_dict).map(([key, field]) =>
                ["Material Request", key, "=", field.get_value()]
            ).concat([["Material Request", "qcmc_include_previously_approved", "=", 1]]);
        },
        async refresh() {
            refreshes++;
            const filters = this.get_filters_for_args();
            assert.equal(filters.length, 1);
            assert.equal(filters[0][1], "material_request_type");
        },
    };
    vm.runInNewContext(fs.readFileSync("qcmc_logic/public/js/material_request_list.js", "utf8"),
                       {frappe, __: text => text});
    frappe.listview_settings["Material Request"].onload(listview);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(previousOnload, 1);
    assert.equal(frappe.listview_settings["Material Request"].marker, true);
    assert.equal(checkboxStyles.flex, "0 0 100%", "Preference occupies a separate toolbar row");
    assert.equal(checkbox.prop("checked"), true);
    assert.equal(listview.count_upper_bound, 0);
    for (const checked of [false, true, false]) {
        checkbox.prop("checked", checked);
        await change();
        assert.equal(calls.findLast(call => call.method.endsWith("set_history_preference")).args.enabled, Number(checked));
        assert.equal(checkbox.prop("checked"), checked);
        assert.equal(listview.start, 0);
        assert.equal(listview.last_args, null);
    }
    assert.equal(refreshes, 4);
    assert.ok(alerts.some(alert => alert.indicator === "orange" && alert.message.includes("No recorded previous approvals")));
    failSave = true;checkbox.prop("checked", true);
    await assert.rejects(change(), /Save failed/);
    assert.equal(checkbox.prop("checked"), false);
    assert.equal(checkbox.prop("disabled"), false);
    const previousCalls = calls.length;
    frappe.listview_settings["Material Request"].onload(listview);
    assert.equal(calls.length, previousCalls, "Returning to the list must not duplicate controls or handlers");
    console.log("Material Request checkbox toggles and generated query filters verified");
}
run().catch(error => {console.error(error);process.exitCode=1;});
