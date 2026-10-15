const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../public/js/realtime_same_origin.js'), 'utf8');
for (const [configured, development, expected, origin = 'https://erp.example'] of [[false, true, 'native'], [true, false, 'native'], [true, true, 'https://erp.example/erp.local'], [true, true, 'native', 'http://localhost:8000']]) {
    const original = () => 'native';
    const context = {URL, frappe: {boot: {qcmc_realtime_same_origin: configured, qcmc_realtime_proxy_origin: 'https://erp.example', sitename: 'erp.local'}, realtime: {get_host: original}},
        window: {dev_server: development, location: {origin}}};
    vm.runInNewContext(source, context);
    assert.equal(context.frappe.realtime.get_host(), expected);
}
console.log('Configured development realtime URL and native production fallback checks passed');
