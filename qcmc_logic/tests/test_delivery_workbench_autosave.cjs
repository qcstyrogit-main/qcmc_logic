// Run with node --test qcmc_logic/tests/test_delivery_workbench_autosave.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function workbench(call) {
 const context = vm.createContext({
  frappe: {pages: {'delivery-schedule-workbench': {}}, call, msgprint() {}},
  __: value => value, clearTimeout, setTimeout,
 });
 vm.runInContext(fs.readFileSync(path.join(__dirname,
  '../qcmc_logics/page/delivery_schedule_workbench/delivery_schedule_workbench.js'), 'utf8') +
  '\nglobalThis.Workbench = DeliveryScheduleWorkbench;', context);
 const instance = Object.create(context.Workbench.prototype);
 Object.assign(instance, {
  rows: [{delivery_note: 'DN', dn_detail: 'A', document_modified: 'v1'},
   {delivery_note: 'DN', dn_detail: 'B', document_modified: 'v1'}],
  dirty_rows: new Set([0, 1]), autosave_timers: {}, save_chain: Promise.resolve(),
  save_failed: false, set_save_status() {},
 });
 return instance;
}

test('flush waits for saves, serializes them and carries document versions forward', async () => {
 let finish;
 const calls = [];
 const wb = workbench(({args}) => {
  calls.push(args.row);
  if (calls.length === 1) return new Promise(resolve => { finish = resolve; });
  return Promise.resolve({message: {saved: true, document_modified: 'v3'}});
 });
 const flushed = wb.flush_saves();
 await Promise.resolve();
 assert.equal(calls.length, 1);
 finish({message: {saved: true, document_modified: 'v2'}});
 assert.equal(await flushed, true);
 assert.equal(calls.length, 2);
 assert.equal(calls[1].document_modified, 'v2');
 assert.equal(wb.dirty_rows.size, 0);
});

test('failed saves retain edits and block navigation or release', async () => {
 let calls = 0;
 const wb = workbench(async () => { calls++; throw new Error('Conflict'); });
 assert.equal(await wb.flush_saves(), false);
 assert.equal(calls, 1);
 assert.equal(wb.dirty_rows.size, 2);
 assert.equal(await wb.flush_saves(), false);
});

test('edits during an in-flight save are flushed before continuing', async () => {
 let finish;
 let calls = 0;
 const wb = workbench(() => {
  calls++;
  if (calls === 1) return new Promise(resolve => { finish = resolve; });
  return Promise.resolve({message: {saved: true, document_modified: 'v3'}});
 });
 wb.dirty_rows = new Set([0]);
 const flushed = wb.flush_saves();
 await Promise.resolve();
 wb.rows[0].logistics_proposed_qty = 5;
 wb.dirty_rows.add(0);
 finish({message: {saved: true, document_modified: 'v2'}});
 assert.equal(await flushed, true);
 assert.equal(calls, 2);
});
