const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

async function main() {
    let events, dialog;
    const buttons = {}, calls = [], properties = [], messages = [];
    const context = {
        cint: value => Number(value || 0), __: text => text,
        frappe: {
            ui: {form: {on: (doctype, handlers) => {events = handlers;}}, Dialog: class {
                constructor(options) {
                    this.options = options;
                    const data = options.fields.find(field => field.fieldname === "rules").data;
                    this.fields_dict = {rules: {grid: {
                        get_data: () => data,
                        get_selected_children: () => data.filter(row => row.__checked),
                        refresh() {}, add_custom_button: (label, action) => {buttons[label] = action;},
                    }}};
                    dialog = this;
                }
                show() {} hide() {this.hidden = true;}
                get_primary_btn() {return {prop() {}};}
            }},
            msgprint: text => messages.push(text), show_alert() {},
            call: async options => {
                calls.push(options);
                return {message: {version: "v1", rules: [
                    {rule: "RULE-A", location: "A", priority: 1},
                    {rule: "RULE-B", location: "B", priority: 2, disabled: 1},
                ]}};
            },
        },
    };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../public/js/putaway_rule.js"), "utf8"), context);
    const frm = {
        doc: {name: "RULE-A"}, perm: [{write: 1}], trigger() {}, is_new: () => false, is_dirty: () => false,
        set_df_property: (...args) => properties.push(args),
        add_custom_button: (label, action) => {buttons[label] = action;}, reload_doc: async () => {frm.reloaded = true;},
    };
    events.refresh(frm);
    assert.ok(properties.some(([field, property, value]) => field === "priority" && property === "read_only" && value === 1), "Priority must be automatically assigned, not typed");
    await buttons["Manage Location Order"]();
    assert.equal(calls[0].args.rule_name, "RULE-A");
    const rows = dialog.fields_dict.rules.grid.get_data();
    rows[1].__checked = 1;
    buttons["Move Up"]();
    assert.equal(rows[0].rule, "RULE-B");
    assert.equal(rows[0].idx, 1);
    await dialog.options.primary_action();
    assert.equal(calls[1].method, "qcmc_logic.putaway_priority.save_priority_order");
    assert.equal(calls[1].args.ordered_rules.join(","), "RULE-B,RULE-A");
    assert.equal(calls[1].args.version, "v1");
    assert.equal(frm.reloaded, true);
    assert.equal(dialog.hidden, true);
    frm.is_dirty = () => true;
    await buttons["Manage Location Order"]();
    assert.equal(calls.length, 2, "Unsaved form edits must not be discarded by ordering");
    assert.ok(messages.length);
    console.log("Putaway priority read-only field, reordering, save and unsaved-edit checks passed");
}

main().catch(error => {console.error(error); process.exitCode = 1;});
