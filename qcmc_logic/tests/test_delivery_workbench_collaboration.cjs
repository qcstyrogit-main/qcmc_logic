// Site-free browser logic tests: node --test <this file>
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function fixture(call = async () => ({})) {
 const timers = new Set();
 const context = vm.createContext({
  frappe: {pages: {'delivery-schedule-workbench': {}}, call, msgprint() {}},
 document: {activeElement: null},
  __: value => value,
  setTimeout: fn => {timers.add(fn); return fn;}, clearTimeout: fn => timers.delete(fn),
 });
 vm.runInContext(fs.readFileSync(path.join(__dirname,
  '../qcmc_logics/page/delivery_schedule_workbench/delivery_schedule_workbench.js'), 'utf8') +
  '\nglobalThis.Workbench = DeliveryScheduleWorkbench;', context);
 const wb = Object.create(context.Workbench.prototype);
 Object.assign(wb, {
  rows: [{delivery_note: 'DN', document_modified: 'v1', qty: 10}],
  dirty_rows: new Set(), autosave_timers: {}, save_chain: Promise.resolve(),
  save_failed: false, load_sequence: 0, collaboration_enabled: true, collaboration_active: true,
  edit_leases: {}, edit_locks: {}, lock_requests: {}, release_requests: {},
  data_revision: 1, remote_pending: true, client_id: 'a'.repeat(20),
  paint_locks() {}, render() {}, set_save_status() {},
  get_filters: () => ({company: 'Test', delivery_date: '2026-11-06'}),
  focused_v2_field: () => false,
 });
 return {wb, timers};
}

test('remote refresh never flushes or overwrites unsaved edits', async () => {
 let calls = 0;
 const {wb, timers} = fixture(async () => {calls++;});
 wb.dirty_rows.add(0);
 wb.flush_saves = () => {throw new Error('Remote refresh must never flush');};
 wb.drain_remote_refresh();
 assert.equal(timers.size, 0);
 await wb.refresh({background: true});
 assert.equal(calls, 0);
 assert.equal(wb.rows[0].qty, 10);
 assert.equal(wb.remote_pending, true);
});

test('idle viewers coalesce notifications into a background refresh', () => {
 const {wb, timers} = fixture();
 let calls = 0;
 wb.refresh = options => {assert.equal(options.background, true); calls++; return Promise.resolve();};
 wb.drain_remote_refresh();
 wb.drain_remote_refresh();
 assert.equal(timers.size, 1);
 [...timers][0]();
 assert.equal(calls, 1);
});

test('typing after a refresh request starts preserves the edited rows', async () => {
 let options;
 const {wb} = fixture(async value => {options = value;});
 await wb.refresh({background: true});
 wb.dirty_rows.add(0);
 options.callback({message: {rows: [{qty: 99}], revision: 2}});
 assert.equal(wb.rows[0].qty, 10);
 assert.equal(wb.remote_pending, true);
});

test('successful background load replaces the grid and records its revision', async () => {
 const {wb} = fixture(async options => options.callback({message: {rows: [{qty: 99}], revision: 2}}));
 wb.poll_collaboration = () => {};
 let renders = 0;
 wb.render = () => renders++;
 await wb.refresh({background: true});
 assert.equal(wb.rows[0].qty, 99);
 assert.equal(wb.data_revision, 2);
 assert.equal(wb.remote_pending, false);
 assert.equal(renders, 1);
});

test('two local controls share one pending acquisition; foreign holder has no token', async () => {
 let finish, calls = 0;
 const {wb} = fixture(() => {calls++; return new Promise(resolve => {finish = resolve;});});
 const first = wb.ensure_edit(wb.rows[0]), second = wb.ensure_edit(wb.rows[0]);
 finish({message: {acquired: false, lock: {mine: false, owner_name: 'Other'}}});
 assert.equal(await first, false);
 assert.equal(await second, false);
 assert.equal(calls, 1);
 assert.equal(wb.edit_leases.DN, undefined);
 assert.equal(wb.edit_locks.DN.owner_name, 'Other');
});

test('expiry preserves unsaved edits and blocks automatic retry', async () => {
 const {wb} = fixture(async () => ({message: {locks: {DN: null}, renewed: [], revision: 2}}));
 wb.edit_leases.DN = 'expired-token';
 wb.dirty_rows.add(0);
 await wb.poll_collaboration();
 assert.equal(wb.rows[0].qty, 10);
 assert.equal(wb.dirty_rows.size, 1);
 assert.equal(wb.save_failed, true);
 assert.equal(wb.edit_leases.DN, undefined);
 assert.equal(wb.remote_pending, true);
});

test('fallback revision polling detects a missed socket notification', async () => {
 const {wb, timers} = fixture(async () => ({message: {locks: {DN: null}, renewed: [], revision: 2}}));
 wb.remote_pending = false;
 await wb.poll_collaboration();
 assert.equal(wb.remote_pending, true);
 assert.equal(timers.size, 1);
});

test('schedule-only rows do not send missing Delivery Note IDs to the lease endpoint', async () => {
	let received;
	const {wb} = fixture(async options => {
		received = options.args.delivery_notes;
		return {message: {locks: {}, renewed: [], revision: 1}};
	});
	wb.rows = [{name: 'SCHED-1', sales_order: 'SO-1'}];
	wb.remote_pending = false;
	await wb.poll_collaboration();
	assert.equal(Array.from(received).length, 0);
	assert.equal(wb.collaboration_offline, false);
});

test('acquisition waits for release to finish before requesting a new token', async () => {
 let finishRelease;
 const calls = [];
 const {wb} = fixture(options => {
  calls.push(options.method);
  if (options.method.endsWith('release_edit')) return new Promise(resolve => {finishRelease = resolve;});
  return Promise.resolve({message: {acquired: true, token: 'new', lock: {mine: true}}});
 });
 wb.edit_leases.DN = 'old';
 const released = wb.release_edit('DN');
 const acquired = wb.ensure_edit(wb.rows[0]);
 assert.equal(calls.length, 1);
 finishRelease({message: {released: true}});
 await released;
 assert.equal(await acquired, true);
 assert.equal(calls.length, 2);
 assert.equal(wb.edit_leases.DN, 'new');
});
