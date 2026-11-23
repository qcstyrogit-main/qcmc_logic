const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const handlers = {};
const context = {
    frappe: { ui: { form: { on: (doctype, events) => { handlers[doctype] = events; } } },
        utils: { escape_html: (v) => String(v).replaceAll('<', '&lt;'), get_form_link: (dt, name) => `/app/${dt}/${name}` } },
    __: (v) => v,
    format_number: (v) => Number(v).toFixed(3),
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('qcmc_logic/public/js/purchase_receipt.js', 'utf8'), context);
const api = context.qcmc_wrr_allocation;
assert(api);
const fieldChanges = [];
const grid = { update_docfield_property: (...args) => fieldChanges.push(args), refresh: () => {} };
const properties = [];
const frm = { doc: { name: 'NEW', docstatus: 0, is_return: 0, __islocal: 1 },
    fields_dict: { items: { grid } }, set_df_property: (...args) => properties.push(args) };
const assignments = [];
frm.set_value = (...args) => assignments.push(args);
api.configure(frm);
assert(properties.some(([name, prop, value]) => name === 'apply_putaway_rule' && prop === 'read_only' && value === 0));
assert.strictEqual(assignments.length, 0, 'Refresh must not check Apply Putaway Rule automatically');
for (const field of ['location', 'from_location', 'rejected_location']) {
    assert(fieldChanges.some(([name, prop, value]) => name === field && prop === 'hidden' && value === 1));
}
assert(properties.some(([name, prop, value]) => name === 'custom_warehouse_allocation_section' && prop === 'hidden' && value === 1));
const refreshed = [];
frm.refresh_field = (name) => refreshed.push(name);
frm.doc.__islocal = 0;
frm.doc.custom_wrr_allocation_enabled = 1;
api.load(frm);
assert(refreshed.includes('custom_warehouse_allocation'), 'Saved allocations must use the native Table control');
assert.strictEqual(typeof api.render, 'undefined', 'Do not render an HTML allocation table');
console.log('WRR bulk fields, manual checkbox and native allocation grid checks passed');
