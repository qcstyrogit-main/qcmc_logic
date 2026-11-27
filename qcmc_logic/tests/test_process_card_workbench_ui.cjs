// Site-free UI behavior tests: node qcmc_logic/tests/test_process_card_workbench_ui.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function fixture() {
	const routes = [];
	const storage = {};
	const calls = [];
	const alerts = [];
	const messages = [];
	const local = {};
	const context = vm.createContext({
		frappe: {pages: {'process-card-workbench': {}, 'production-floor-workbench': {}}, set_route: (...args) => routes.push(args), utils: {escape_html: value => String(value)}, get_route: () => context.route || [], call: async options => { calls.push(options); return {message: {success: true}}; }, show_alert: alert => alerts.push(alert), msgprint: message => messages.push(message)},
		sessionStorage: {setItem: (key, value) => {storage[key] = value;}, getItem: key => storage[key] || null, removeItem: key => {delete storage[key];}},
		localStorage: {setItem: (key, value) => {local[key] = value;}, getItem: key => local[key] || null, removeItem: key => {delete local[key];}},
		__: value => value,
	});
	const files = [
		'../qcmc_logics/page/process_card_workbench/process_card_workbench.js',
		'../qcmc_logics/page/production_floor_workbench/production_floor_workbench.js',
	];
	vm.runInContext(files.map(file => fs.readFileSync(path.join(__dirname, file), 'utf8')).join('\n') +
		'\nglobalThis.ProcessCardWorkbenchClass = ProcessCardWorkbench; globalThis.ProductionFloorWorkbenchClass = ProductionFloorWorkbench;', context);
	return {context, routes, storage, local, calls, alerts, messages};
}

test('floor Process Card action opens the dedicated workbench route and saves floor context', async () => {
	const {context, routes} = fixture();
	const wb = Object.create(context.ProductionFloorWorkbenchClass.prototype);
	let saved = false;
	Object.assign(wb, {remember_floor_context: () => {saved = true;}});
	await wb.action('open-card', 'PC-1');
	assert.deepEqual(routes, [['process-card-workbench', 'PC-1']]);
	assert.equal(saved, true);
});

test('Floor Navigator return context preserves site, machine, and shift filters', () => {
	const {context, storage} = fixture();
	const wb = Object.create(context.ProductionFloorWorkbenchClass.prototype);
	Object.assign(wb, {site: 'Guyong', building: 'Building-1', selected: 'Machine-1', shift_date: '2026-11-10', shift_type: 'Day'});
	wb.remember_floor_context();
	assert.deepEqual(JSON.parse(storage.qcmc_floor_workbench_return), {site: 'Guyong', building: 'Building-1', selected: 'Machine-1', shift_date: '2026-11-10', shift_type: 'Day'});
});

test('Batch Encoding opens from a building with saved site and shift context', async () => {
	const {context, routes, storage} = fixture();
	context.frappe.datetime = {get_today: () => '2026-11-10'};
	const wb = Object.create(context.ProductionFloorWorkbenchClass.prototype);
	Object.assign(wb, {site: 'Guyong', shift_type: 'Day'});
	await wb.action('open-batch', 'building-1');
	assert.deepEqual(routes, [['process-card-workbench', 'batch']]);
	assert.deepEqual(JSON.parse(storage.qcmc_process_card_batch_context), {site: 'Guyong', building: 'building-1', shift_date: '2026-11-10', shift_type: 'Day'});
});

test('Workbench reads a direct Desk route identifier and ignores stale card loads', async () => {
	const {context} = fixture();
	context.route = ['process-card-workbench', 'PC-2'];
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	let resolveOld, resolveNew;
	Object.assign(wb, {render() {}, call: () => new Promise(resolve => { if (!resolveOld) resolveOld = resolve; else resolveNew = resolve; })});
	const first = wb.load_from_route();
	context.route = ['process-card-workbench', 'PC-3'];
	const second = wb.load_from_route();
	resolveNew({process_card: {name: 'PC-3'}, job_cards: []});
	await second;
	resolveOld({process_card: {name: 'PC-2'}, job_cards: []});
	await first;
	assert.equal(wb.process_card, 'PC-3');
	assert.equal(wb.context.process_card.name, 'PC-3');
});

test('page show does not start a duplicate load while the same route is already active', () => {
	const {context} = fixture();
	context.route = ['process-card-workbench', 'new'];
	let loads = 0;
	const workbench = {route_key: 'new', load_from_route() { loads += 1; }};
	context.frappe.pages['process-card-workbench'].on_page_show({process_card_workbench: workbench});
	assert.equal(loads, 0);
	context.route = ['process-card-workbench', 'PC-1'];
	context.frappe.pages['process-card-workbench'].on_page_show({process_card_workbench: workbench});
	assert.equal(loads, 1);
});

test('Workbench uses GET for context reads and POST for mutations', async () => {
	const {context, calls} = fixture();
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	await wb.call('get_process_card_context', {process_card: 'PC-1'});
	await wb.call_post('add_job_cards', {process_card: 'PC-1', job_cards: '["JC-1"]'});
	assert.equal(calls[0].type, 'GET');
	assert.equal(calls[0].method, 'qcmc_logic.api.process_card_workbench.get_process_card_context');
	assert.equal(calls[1].type, 'POST');
	assert.equal(calls[1].method, 'qcmc_logic.api.process_card_workbench.add_job_cards');
});

test('Return action routes to the Floor Navigator', () => {
	const {context, routes} = fixture();
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	wb.return_to_floor();
	assert.deepEqual(routes, [['production-floor-workbench']]);
});

test('failed Process Card load produces an error state', async () => {
	const {context} = fixture();
	context.route = ['process-card-workbench', 'PC-FAIL'];
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	Object.assign(wb, {render() {}, call: async () => {throw new Error('denied');}});
	await wb.load_from_route();
	assert.match(wb.error, /Could not load this Process Card/);
});

test('Workbench keeps standard Process Card form access available', async () => {
	const {context, routes} = fixture();
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	wb.process_card = 'PC-1';
	await wb.handle_action('open-process-card-form');
	assert.deepEqual(routes, [['Form', 'Process Card', 'PC-1']]);
});

test('existing Process Card form exposes the Workbench while standard form routes remain available', () => {
	const root = path.join(__dirname, '../public/js/process_card.js');
	const form = fs.readFileSync(root, 'utf8');
	const page = fs.readFileSync(path.join(__dirname, '../qcmc_logics/page/process_card_workbench/process_card_workbench.js'), 'utf8');
	assert.match(form, /frappe\.set_route\("process-card-workbench", frm\.doc\.name\)/);
	assert.match(form, /qcmc_logic\.api\.process_card_services\.get_process_card_shift_summary/);
	assert.match(page, /frappe\.set_route\("Form", "Job Card", id\)/);
	assert.match(page, /for_quantity/);
	assert.match(page, /total_completed_qty/);
	assert.match(page, /actual_start_date/);
	assert.match(page, /actual_end_date/);
	assert.match(page, /No Job Cards are linked to this Process Card/);
});

test('Process Card Workbench saves output through Task 01 Time Log API and refreshes', async () => {
	const {context, calls, alerts} = fixture();
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	let refreshed = false;
	const values = {'.pcw-output-job': 'JC-1', '.pcw-output-from': '06:30', '.pcw-output-to': '07:15', '.pcw-output-good': '10.5', '.pcw-output-rejected': '1', '.pcw-output-remarks': 'Checkpoint note'};
	Object.assign(wb, {
		process_card: 'PC-1', selected_checkpoint: 0, output_pending: false,
		context: {can_record_output: true, process_card: {shift_date: '2026-11-10', shift_start: '2026-11-10 06:00:00', shift_end: '2026-11-10 18:00:00'}, job_cards: [{name: 'JC-1'}], production_output: {checkpoints: [], per_job: [{job_card: 'JC-1', entries: []}]}},
		$root: {find: selector => ({val: () => values[selector]})}, render() {}, load_from_route: async () => {refreshed = true;},
	});
	await wb.handle_action('save-output');
	assert.equal(calls[0].method, 'qcmc_logic.api.job_card_time_log.save_process_card_output');
	assert.equal(calls[0].args.process_card, 'PC-1');
	assert.equal(calls[0].args.job_card, 'JC-1');
	assert.equal(calls[0].args.from_time, '2026-11-10 06:30:00');
	assert.equal(calls[0].args.to_time, '2026-11-10 07:15:00');
	assert.equal(calls[0].args.good_qty, '10.5');
	assert.equal(calls[0].args.rejected_qty, '1');
	assert.equal(refreshed, true);
	assert.equal(alerts.length, 1);
});

test('time-only output controls inherit the Process Card date and resolve overnight intervals', () => {
	const {context} = fixture();
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	assert.equal(JSON.stringify(wb.compose_output_interval('06:00', '08:00', '2026-11-10 06:00:00', '2026-11-10 18:00:00', '2026-11-10')), JSON.stringify({from_time: '2026-11-10 06:00:00', to_time: '2026-11-10 08:00:00'}));
	assert.equal(JSON.stringify(wb.compose_output_interval('23:00', '01:00', '2026-11-10 22:00:00', '2026-11-11 06:00:00', '2026-11-10')), JSON.stringify({from_time: '2026-11-10 23:00:00', to_time: '2026-11-11 01:00:00'}));
	assert.equal(JSON.stringify(wb.compose_output_interval('02:00', '04:00', '2026-11-10 22:00:00', '2026-11-11 06:00:00', '2026-11-10')), JSON.stringify({from_time: '2026-11-11 02:00:00', to_time: '2026-11-11 04:00:00'}));
});

test('batch shared-machine time unions overlapping Job Card periods once', () => {
	const {context} = fixture();
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	wb.batch = {rows: [
		{workstation: 'WS-1', from_time: '2026-11-10T06:00', to_time: '2026-11-10T08:00'},
		{workstation: 'WS-1', from_time: '2026-11-10T06:00', to_time: '2026-11-10T08:00'},
		{workstation: 'WS-1', from_time: '2026-11-10T07:30', to_time: '2026-11-10T09:00'},
		{workstation: 'WS-2', from_time: '2026-11-10T06:00', to_time: '2026-11-10T07:00'},
	]};
	assert.equal(wb.unique_machine_minutes(), 240);
});

test('batch correction checks per-row Job Card permission without requiring an individual-card context', () => {
	const {context, messages} = fixture();
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	Object.assign(wb, {batch: {rows: [{existing_entry: {time_log_id: 'TL-1'}, can_correct_output: false}]}});
	wb.correct_batch_output(0);
	assert.match(messages[0], /permission to correct output/);
});

test('mobile output only offers Job Cards the current user can write', () => {
	const {context} = fixture();
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	Object.assign(wb, {context: {production_output: {per_job: []}}});
	const html = wb.mobile_output_form([
		{name: 'JC-ALLOWED', operation: 'Cut', status: 'Open', can_record_output: true},
		{name: 'JC-DENIED', operation: 'Pack', status: 'Open', can_record_output: false},
	]);
	assert.match(html, /JC-ALLOWED/);
	assert.doesNotMatch(html, /JC-DENIED/);
});

test('Mobile quantity strip shows target, official, all-card, current-card, and remaining values', () => {
	const {context} = fixture();
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	Object.assign(wb, {context: {job_cards: [{name: 'JC-1', for_quantity: 100}], production_output: {per_job: [{job_card: 'JC-1', target_qty: 100, official_completed_qty: 40, all_process_card_output_qty: 30, all_process_card_good_qty: 28, all_process_card_rejected_qty: 2, current_process_card_output_qty: 10, remaining_qty: 30}]}}});
	const html = wb.job_quantity_balance_html('JC-1');
	for (const text of ['Target', 'Official Completed', 'All Process Card Output', 'This Process Card', 'Available', '100', '40', '30', '10']) assert.ok(html.includes(text));
});

test('Mobile Save and Next advances only to another writable Job Card and retains time period', async () => {
	const {context, local} = fixture();
	local.qcmc_mobile_output_period = JSON.stringify({from: '06:00', to: '08:00'});
	const values = {'.pcw-output-job': 'JC-1', '.pcw-output-from': '06:00', '.pcw-output-to': '08:00', '.pcw-output-good': '10', '.pcw-output-rejected': '0', '.pcw-output-remarks': ''};
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	Object.assign(wb, {process_card: 'PC-1', output_pending: false, context: {can_record_output: true, process_card: {shift_date: '2026-11-10', shift_start: '2026-11-10 06:00:00', shift_end: '2026-11-10 18:00:00'}, job_cards: [{name: 'JC-1', can_record_output: true}, {name: 'JC-DENIED', can_record_output: false}, {name: 'JC-2', can_record_output: true}], production_output: {per_job: []}}, $root: {find: selector => ({val: () => values[selector]})}, render() {}, call_output: async () => ({}), load_from_route: async () => {}});
	await wb.save_output_entry(true);
	assert.deepEqual(JSON.parse(local['qcmc_mobile_output_PC-1']), {job: 'JC-2', from: '06:00', to: '08:00', good: '', rejected: '0', remarks: ''});
	assert.deepEqual(JSON.parse(local.qcmc_mobile_output_period), {from: '06:00', to: '08:00'});
});

test('Mobile output blocks a concurrent second submission while the first request is pending', async () => {
	const {context} = fixture();
	const values = {'.pcw-output-job': 'JC-1', '.pcw-output-from': '06:00', '.pcw-output-to': '08:00', '.pcw-output-good': '10', '.pcw-output-rejected': '0', '.pcw-output-remarks': ''};
	let resolveSave, calls = 0;
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	Object.assign(wb, {process_card: 'PC-1', output_pending: false, context: {can_record_output: true, process_card: {shift_date: '2026-11-10', shift_start: '2026-11-10 06:00:00', shift_end: '2026-11-10 18:00:00'}, job_cards: [{name: 'JC-1', can_record_output: true}], production_output: {per_job: []}}, $root: {find: selector => ({val: () => values[selector]})}, render() {}, call_output: () => {calls += 1; return new Promise(resolve => {resolveSave = resolve;});}, load_from_route: async () => {}});
	const first = wb.save_output_entry();
	await wb.save_output_entry();
	assert.equal(calls, 1);
	resolveSave({});
	await first;
});

test('Mobile output failure keeps its unsaved draft for correction and retry', async () => {
	const {context, local, messages} = fixture();
	const draft = {job: 'JC-1', from: '06:00', to: '08:00', good: 'bad', rejected: '0', remarks: 'retain'};
	local['qcmc_mobile_output_PC-1'] = JSON.stringify(draft);
	const values = {'.pcw-output-job': 'JC-1', '.pcw-output-from': '06:00', '.pcw-output-to': '08:00', '.pcw-output-good': 'bad', '.pcw-output-rejected': '0', '.pcw-output-remarks': 'retain'};
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	Object.assign(wb, {process_card: 'PC-1', output_pending: false, context: {can_record_output: true, process_card: {shift_date: '2026-11-10', shift_start: '2026-11-10 06:00:00', shift_end: '2026-11-10 18:00:00'}, job_cards: [{name: 'JC-1', can_record_output: true}], production_output: {per_job: []}}, $root: {find: selector => ({val: () => values[selector]})}, render() {}, call_output: async () => {throw new Error('Quantity invalid');}, load_from_route: async () => {}});
	await wb.save_output_entry();
	assert.deepEqual(JSON.parse(local['qcmc_mobile_output_PC-1']), draft);
	assert.equal(messages[0], 'Quantity invalid');
});

test('batch save refresh keeps failed row values and attaches saved output from authority response', async () => {
	const {context, calls, alerts} = fixture();
	let refreshCalled = false;
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	const failed = {process_card: 'PC-1', job_card: 'JC-1', workstation: 'WS-1', process_shift_start: '2026-11-10 06:00:00', process_shift_end: '2026-11-10 18:00:00', from_time: '2026-11-10 06:00:00', to_time: '2026-11-10 08:00:00', good_qty: '11', rejected_qty: '2', remarks: 'keep me', dirty: true, entry_status: 'Modified', existing_entries: []};
	const saved = {process_card: 'PC-2', job_card: 'JC-2', workstation: 'WS-2', process_shift_start: '2026-11-10 06:00:00', process_shift_end: '2026-11-10 18:00:00', from_time: '2026-11-10 06:00:00', to_time: '2026-11-10 08:00:00', good_qty: '20', rejected_qty: '0', remarks: '', dirty: true, entry_status: 'Modified', existing_entries: []};
	Object.assign(wb, {
		batch_pending: false, batch: {loaded: true, site: 'Guyong', shift_date: '2026-11-10', shift_type: 'Day', building: '', from_time: '06:00', to_time: '08:00', rows: [failed, saved]},
		render() {},
		call_output: async () => ({success_count: 1, results: [{success: false, message: 'Overproduced'}, {success: true}]}),
		call: async () => { refreshCalled = true; return {rows: [
			{...failed, from_time: '2026-11-10 06:00:00', to_time: '2026-11-10 18:00:00', existing_entries: []},
			{...saved, from_time: '2026-11-10 06:00:00', to_time: '2026-11-10 18:00:00', existing_entries: [{from_time: '2026-11-10 06:00:00', to_time: '2026-11-10 08:00:00', good_qty: 20, rejected_qty: 0, remarks: '', time_log_id: 'TL-2'}]},
		]};},
	});
	await wb.save_batch_rows();
	assert.equal(refreshCalled, true);
	assert.equal(wb.batch.rows[0].good_qty, '11');
	assert.equal(wb.batch.rows[0].remarks, 'keep me');
	assert.equal(wb.batch.rows[0].dirty, true);
	assert.equal(wb.batch.rows[0].entry_status, 'Overproduced');
	assert.equal(wb.batch.rows[1].existing_entry.time_log_id, 'TL-2');
	assert.equal(wb.batch.rows[1].entry_status, 'Saved');
	assert.equal(wb.batch.rows[1].dirty, false);
	assert.equal(alerts.length, 1);
	assert.ok(calls.length >= 0);
});

test('machine creation defaults load into the Workbench with Shift Type times', async () => {
	const {context, storage} = fixture();
	context.route = ['process-card-workbench', 'new'];
	storage.qcmc_process_card_create_context = JSON.stringify({company: 'Company A', site: 'Guyong', workstation: 'WS-1', shift_date: '2026-11-10', shift_type: 'Day'});
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	Object.assign(wb, {render() {}, call: async () => ({workstation: {name: 'WS-1', workstation_name: 'AVM 1'}, shift_types: [{name: 'Day', start_time: '06:00:00', end_time: '18:00:00'}], job_cards: [{name: 'JC-1'}]})});
	await wb.load_from_route();
	assert.equal(wb.creation.workstation.name, 'WS-1');
	assert.equal(wb.creation.shift_start, '2026-11-10T06:00:00');
	assert.equal(wb.creation.shift_end, '2026-11-10T18:00:00');
	assert.deepEqual(wb.creation.job_cards.map(row => row.name), ['JC-1']);
});

test('creation render failures replace the permanent loading indicator with an error', async () => {
	const {context, storage} = fixture();
	context.route = ['process-card-workbench', 'new'];
	storage.qcmc_process_card_create_context = JSON.stringify({company: 'Company A', site: 'Guyong', workstation: 'WS-1', shift_date: '2026-11-10'});
	const notices = [];
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	Object.assign(wb, {
		loading: false,
		$root: {find: selector => ({html: value => notices.push([selector, value]), empty: () => notices.push([selector, 'empty'])})},
		call: async () => ({workstation: {name: 'WS-1'}, shift_types: [], job_cards: []}),
		render() { if (!this.loading) throw new Error('control render failure'); },
	});
	await wb.load_from_route();
	assert.equal(wb.loading, false);
	assert.match(wb.error, /control render failure/);
	assert.match(notices[0][1], /control render failure/);
});

test('creation form hydration is silent and shift edits keep the active Link control mounted', async () => {
	const {context} = fixture();
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	const inputs = {};
	const controls = [];
	let changeEvents = 0;
	context.frappe.ui = {form: {make_control(options) {
		const control = {
			df: options.df,
			set_input(value) { this.value = value; },
			get_value() { return this.value; },
			set_value(value) {
				this.value = value;
				return Promise.resolve().then(() => { changeEvents += 1; this.df.change.call(this); });
			},
		};
		controls.push(control);
		return control;
	}}};
	const content = {html() {}, find: () => ({})};
	Object.assign(wb, {
		creation: {workstation: {name: 'WS-1'}, shift_type: '', shift_date: '2026-11-10', shift_start: '', shift_end: '', shift_types: [{name: 'Day', start_time: '06:00:00', end_time: '18:00:00'}]},
		$root: {find: selector => ({val: value => { inputs[selector] = value; }})},
		render() { throw new Error('Shift edits must not recreate the form'); },
	});
	wb.render_creation(content);
	await new Promise(setImmediate);
	assert.equal(changeEvents, 0);
	assert.equal(controls.length, 1);
	await controls[0].set_value('Day');
	assert.equal(wb.creation.shift_type, 'Day');
	assert.equal(wb.creation.shift_start, '2026-11-10T06:00:00');
	assert.equal(wb.creation.shift_end, '2026-11-10T18:00:00');
	assert.equal(inputs['.pcw-create-shift-start'], wb.creation.shift_start);
	assert.equal(inputs['.pcw-create-shift-end'], wb.creation.shift_end);
	assert.equal(controls.length, 1);
	wb.render_creation(content);
	await new Promise(setImmediate);
	assert.equal(changeEvents, 1);
	assert.equal(controls[1].get_value(), 'Day');
	await controls[0].set_value('Obsolete shift');
	assert.equal(wb.creation.shift_type, 'Day');
});

test('Desk bootstrap discards the stale cached Workbench script and preserves current and unrelated caches', () => {
	const source = fs.readFileSync(path.join(__dirname, '../public/js/process_card_workbench_cache.js'), 'utf8');
	const pageSource = fs.readFileSync(path.join(__dirname, '../qcmc_logics/page/process_card_workbench/process_card_workbench.js'), 'utf8');
	const storage = {'_page:process-card-workbench': 'old script', '_page:other-page': 'unrelated', qcmc_process_card_create_context: 'machine defaults'};
	const context = vm.createContext({localStorage: {getItem: key => storage[key], removeItem: key => { delete storage[key]; }}});
	vm.runInContext(source, context);
	assert.equal(storage['_page:process-card-workbench'], undefined);
	assert.equal(storage['_page:other-page'], 'unrelated');
	assert.equal(storage.qcmc_process_card_create_context, 'machine defaults');
	storage['_page:process-card-workbench'] = JSON.stringify([{script: pageSource}]);
	vm.runInContext(source, context);
	assert.ok(storage['_page:process-card-workbench']);
});

test('blocked browser storage does not prevent Desk bootstrap', () => {
	const source = fs.readFileSync(path.join(__dirname, '../public/js/process_card_workbench_cache.js'), 'utf8');
	const context = vm.createContext({localStorage: {getItem() { throw new Error('Storage blocked'); }}});
	assert.doesNotThrow(() => vm.runInContext(source, context));
});

test('creation saves selected Job Cards with shift and machine context then opens the created card', async () => {
	const {context, routes, storage, calls, alerts} = fixture();
	const values = {'.pcw-create-shift-start': '2026-11-10T06:00', '.pcw-create-shift-end': '2026-11-10T18:00'};
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	Object.assign(wb, {
		creation: {company: 'Company A', site: 'Guyong', workstation: {name: 'WS-1'}, shift_date: '2026-11-10', shift_type: 'Day', selected_job_cards: ['JC-1'], remarks: ''},
		$root: {find: selector => ({val: () => values[selector]})}, render() {},
		call_post: async (method, args) => { calls.push({method, args}); return {name: 'PC-NEW'}; },
	});
	await wb.submit_creation();
	assert.equal(calls[0].method, 'create_process_card');
	assert.equal(calls[0].args.workstation, 'WS-1');
	assert.deepEqual(JSON.parse(calls[0].args.job_cards), ['JC-1']);
	assert.deepEqual(routes, [['process-card-workbench', 'PC-NEW']]);
	assert.equal(storage.qcmc_process_card_create_context, undefined);
	assert.equal(alerts.length, 1);
});

test('primary UI removes generated checkpoints and exposes collapsed actual production history', () => {
	const source = fs.readFileSync(path.join(__dirname, '../qcmc_logics/page/process_card_workbench/process_card_workbench.js'), 'utf8');
	assert.doesNotMatch(source, /Checkpoint Timeline/);
	assert.doesNotMatch(source, /Missing entries for linked Job Cards/);
	assert.doesNotMatch(source, /select-output-checkpoint/);
	assert.match(source, /<details class="pcw-history">/);
	assert.match(source, /Production History/);
	assert.match(source, /data-action="correct-output"/);
	assert.match(source, /Correction history/);
	assert.match(source, /permission to enter output on the linked Job Cards, or this Process Card is locked/);
	assert.match(source, /save_process_card_output/);
	assert.match(source, /correct_process_card_output/);
	assert.match(source, /Batch Encoding/);
	assert.match(source, /Save & Next Operation/);
	assert.match(source, /class=\"form-control pcw-output-from\" type=\"time\"/);
	assert.match(source, /class=\"form-control pcw-batch-from\" type=\"time\"/);
	assert.match(source, /datetime-local/); // Process Card shift bounds remain date-time values.
	assert.match(source, /get_batch_output_context/);
	assert.match(source, /save_process_card_output_batch/);
	assert.match(source, /Computed Remaining Minutes/);
});

test('individual encoding mode defaults to Mobile and persists the selected mode across refresh', async () => {
	const {context, storage} = fixture();
	context.frappe.datetime = {get_today: () => '2026-11-10'};
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	Object.assign(wb, {render() {}});
	assert.equal(wb.load_encoding_mode('PC-1'), 'mobile');
	wb.process_card = 'PC-1';
	await wb.handle_action('encoding-mode', 'batch');
	assert.equal(storage['qcmc_process_card_encoding_mode_PC-1'], 'batch');
	assert.equal(wb.load_encoding_mode('PC-1'), 'batch');
	await wb.handle_action('encoding-mode', 'mobile');
	assert.equal(wb.load_encoding_mode('PC-1'), 'mobile');
});

test('route refresh restores the per-card mode and batch route defaults directly to Batch', async () => {
	const {context, storage} = fixture();
	context.route = ['process-card-workbench', 'PC-1'];
	storage['qcmc_process_card_encoding_mode_PC-1'] = 'batch';
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	Object.assign(wb, {render() { this.batch_rendered = this.route_key === "batch"; }, call: async () => ({process_card: {name: 'PC-1'}, job_cards: []})});
	await wb.load_from_route();
	assert.equal(wb.encoding_mode, 'batch');
	context.route = ['process-card-workbench', 'batch'];
	wb.render_batch = () => { wb.batch_rendered = true; };
	wb.load_batch_defaults = () => ({site: 'Guyong', shift_date: '2026-11-10', shift_type: 'Day'});
	await wb.load_from_route();
	assert.equal(wb.encoding_mode, 'batch');
	assert.equal(wb.batch_rendered, true);
});

test('single-card Batch defaults use its saved Process Card date and shift', () => {
	const {context, storage} = fixture();
	context.frappe.datetime = {get_today: () => '2026-11-10'};
	storage.qcmc_process_card_batch_context = JSON.stringify({site: 'Old Site', shift_date: '2026-11-09', shift_type: 'Old Shift'});
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	wb.context = {process_card: {site: 'Guyong', building: 'Building 1', shift_date: '2026-11-10', shift_type: 'Shift Type 1'}};
	const batch = wb.load_batch_defaults();
	assert.equal(batch.site, 'Guyong');
	assert.equal(batch.building, 'Building 1');
	assert.equal(batch.shift_date, '2026-11-10');
	assert.equal(batch.shift_type, 'Shift Type 1');
});

test('Batch reporting period inputs persist across refresh', () => {
	const {context, storage} = fixture();
	const values = {'.pcw-batch-date': '2026-11-10', '.pcw-batch-building': 'Building 1', '.pcw-batch-from': '2026-11-10T06:00', '.pcw-batch-to': '2026-11-10T08:00'};
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	Object.assign(wb, {batch: {site: 'Guyong', shift_type: 'Day'}, $root: {find: selector => ({val: () => values[selector]})}, batch_site_control: {get_value: () => 'Guyong'}, batch_shift_type_control: {get_value: () => 'Day'}});
	wb.remember_batch_period();
	const saved = JSON.parse(storage.qcmc_process_card_batch_context);
	assert.equal(saved.shift_date, values['.pcw-batch-date']);
	assert.equal(saved.from_time, values['.pcw-batch-from']);
	assert.equal(saved.to_time, values['.pcw-batch-to']);
	assert.equal(saved.building, 'Building 1');
});

test('Production History uses saved intervals and keeps correction actions', () => {
	const {context} = fixture();
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	Object.assign(wb, {history_filter: {job_card: '', date: ''}, context: {can_record_output: true, job_cards: [{name: 'JC-1', operation: 'Printing', can_correct_output: true}], production_output: {checkpoints: [{from_time: '2026-11-10 06:00', entries: []}], per_job: [{job_card: 'JC-1', production_item: 'ITEM-1', uom: 'pcs', entries: [{time_log_id: 'TL-1', from_time: '2026-11-10 06:00', to_time: '2026-11-10 08:00', good_qty: 10000, rejected_qty: 2, entered_by: 'Foreman', entered_at: '2026-11-10 08:01'}]}]}}});
	const html = wb.render_history_html();
	assert.match(html, /JC-1/);
	assert.match(html, /Printing/);
	assert.match(html, /ITEM-1/);
	assert.match(html, /10000/);
	assert.match(html, /Foreman/);
	assert.match(html, /TL-1/);
	assert.match(html, /data-action="correct-output"/);
	assert.doesNotMatch(html, /Checkpoint/);
});

test('output save errors are shown and the Workbench refreshes authoritative totals', async () => {
	const {context, messages} = fixture();
	context.frappe.call = async () => { throw new Error('Overlapping Job Card interval'); };
	const wb = Object.create(context.ProcessCardWorkbenchClass.prototype);
	let refreshed = false;
	Object.assign(wb, {
		process_card: 'PC-1', selected_checkpoint: 0, output_pending: false,
		context: {can_record_output: true, process_card: {shift_date: '2026-11-10', shift_start: '2026-11-10 06:00:00', shift_end: '2026-11-10 18:00:00'}, job_cards: [{name: 'JC-1'}], production_output: {checkpoints: [{from_time: '2026-11-10 06:00:00', to_time: '2026-11-10 08:00:00'}], per_job: [{job_card: 'JC-1', entries: []}]}},
		$root: {find: selector => ({val: () => ({'.pcw-output-job': 'JC-1', '.pcw-output-from': '06:00', '.pcw-output-to': '08:00', '.pcw-output-good': '1', '.pcw-output-rejected': '0'}[selector])})}, render() {},
		load_from_route: async () => {refreshed = true;},
	});
	await wb.handle_action('save-output');
	assert.equal(messages[0], 'Overlapping Job Card interval');
	assert.equal(refreshed, true);
	assert.equal(wb.output_pending, false);
});

test('Work Order history displays machine, employee name, QA readings and material request links', async () => {
	const source = fs.readFileSync(path.join(__dirname, '../public/js/work_order.js'), 'utf8');
	new vm.Script(source);
	let html = '';
	let shown = false;
	const history = {
		operations: [],
		job_cards: [],
		process_cards: [{
			name: 'PC-1', workstation: 'Machine-A', shift_type: 'Day',
			shift_start: '2026-11-25 06:00', shift_end: '2026-11-25 18:00',
			section_access: {Employee: true, 'Quality Inspection': true},
			output: [],
			participation: [{employee: 'EMP-1', employee_name: 'Test Operator', job_card: 'JC-1', pay_mode: 'DR', from_time: '06:00', to_time: '07:00'}],
			qa: [],
			measurements: [{quality_inspection: 'QI-1', specification: 'Weight', readings: ['2.45', '2.50', '0'], uom: 'Gram', result: 'Accepted'}],
			qa_rejections: [],
			downtime: [],
			repairs: [],
		}],
		stock_entries: [{name: 'SE-1', purpose: 'Material Transfer for Manufacture', posting_date: '2026-11-25', job_card: 'JC-1',
			items: [{item_code: 'RM-1', qty: 5, uom: 'Kg', from_warehouse: 'RAW', to_warehouse: 'WIP', material_request: 'MR-1'}],
			allocations: []}],
	};
	const context = vm.createContext({
		__: value => value,
		frappe: {
			call: async args => {
				assert.equal(args.args.work_order, 'WO-1');
				return {message: history};
			},
			utils: {
				escape_html: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
				get_form_link: (doctype, name) => '/app/' + doctype + '/' + name,
			},
			ui: {Dialog: class {
				constructor() { this.fields_dict = {history: {[String.fromCharCode(36) + 'wrapper']: {html: value => {html = value;}}}}; }
				show() { shown = true; }
			}},
		},
	});
	const offset = source.indexOf('async function show_manufacturing_history(frm)');
	assert.ok(offset >= 0);
	vm.runInContext(source.slice(offset), context);
	await context.show_manufacturing_history({doc: {name: 'WO-1'}});
	assert.equal(shown, true);
	for (const expected of ['Machine-A', 'Test Operator', 'Product Weight / Measurements', '2.45, 2.50, 0', 'Gram', 'MR-1', 'JC-1', 'RAW', 'WIP']) {
		assert.ok(html.includes(expected), expected + ' missing from history');
	}
	assert.ok(html.includes('/app/Material Request/MR-1'));
});

test('Work Order history remains readable when measurement and request fields are absent', async () => {
	const source = fs.readFileSync(path.join(__dirname, '../public/js/work_order.js'), 'utf8');
	let html = '';
	const context = vm.createContext({
		__: value => value,
		frappe: {
			call: async () => ({message: {
				operations: [], job_cards: [],
				process_cards: [{name: 'PC-1', section_access: {Employee: false}, output: [], participation: [], qa: [], qa_rejections: [], downtime: [], repairs: []}],
				stock_entries: [{name: 'SE-1', items: [{item_code: 'RM-1'}], allocations: []}],
			}}),
			utils: {escape_html: value => String(value), get_form_link: (doctype, name) => '/app/' + doctype + '/' + name},
			ui: {Dialog: class {
				constructor() { this.fields_dict = {history: {[String.fromCharCode(36) + 'wrapper']: {html: value => {html = value;}}}}; }
				show() {}
			}},
		},
	});
	vm.runInContext(source.slice(source.indexOf('async function show_manufacturing_history(frm)')), context);
	await context.show_manufacturing_history({doc: {name: 'WO-1'}});
	assert.ok(html.includes('Some sections are restricted by your permissions.'));
	assert.ok(!html.includes('Material Request/undefined'));
});

test('Job Card manpower dialog saves through separate participation API without modifying output rows', async () => {
	const source = fs.readFileSync(path.join(__dirname, '../public/js/job_card.js'), 'utf8');
	new vm.Script(source);
	let config;
	let reloaded = false;
	let hidden = false;
	let calls = [];
	const context = vm.createContext({
		qcmc_logic: {job_card: {}},
		__: value => value,
		frappe: {
			ui: {Dialog: class {
				constructor(options) { config = options; }
				show() {}
				hide() { hidden = true; }
			}},
			call: async args => {calls.push(args); return {message: {time_log_id: 'TL-2'}};},
			show_alert() {},
			msgprint() {},
		},
	});
	const start = source.indexOf('qcmc_logic.job_card.record_manpower_participation = function');
	const end = source.indexOf('qcmc_logic.job_card.record_process_card_output = function');
	assert.ok(start >= 0 && end > start);
	vm.runInContext(source.slice(start, end), context);
	const frm = {doc: {name: 'JC-1', company: 'Company A', workstation: 'WS-1',
		time_logs: [{name: 'TL-1', qcmc_process_card: 'PC-1', qcmc_good_qty: 2000}]},
		is_dirty: () => false, reload_doc: async () => {reloaded = true;}};
	context.qcmc_logic.job_card.record_manpower_participation(frm);
	assert.equal(config.fields.find(row => row.fieldname === 'process_card').default, 'PC-1');
	await config.primary_action({process_card: 'PC-1', employee: 'EMP-1', pay_mode: 'DR', from_time: '2026-11-26 06:00:00', to_time: '2026-11-26 14:00:00'});
	assert.equal(calls.length, 1);
	assert.equal(calls[0].method, 'qcmc_logic.api.process_card_services.save_process_card_participation');
	assert.equal(calls[0].args.job_card, 'JC-1');
	assert.equal(calls[0].args.employee, 'EMP-1');
	assert.equal(frm.doc.time_logs[0].qcmc_good_qty, 2000);
	assert.equal(hidden, true);
	assert.equal(reloaded, true);
});

test('Shift Summary uses extra-large dialog with responsive tables', async () => {
	const source = fs.readFileSync(path.join(__dirname, '../public/js/process_card.js'), 'utf8');
	let handlers, config, html = '', shown = false;
	const buttons = {};
	const context = vm.createContext({
		__: value => value,
		frappe: {
			ui: {
				form: {on: (doctype, events) => {handlers = events;}},
				Dialog: class {
					constructor(options) {
						config = options;
						this.fields_dict = {summary: {[String.fromCharCode(36) + 'wrapper']: {html: value => {html = value;}}}};
					}
					show() {shown = true;}
				},
			},
			utils: {escape_html: value => String(value)},
			call: async () => ({message: {
				production_output: {per_job: [{job_card: 'JC-1', production_item: 'ITEM-1', good_qty: 2000, rejected_qty: 0}]},
				manpower_participation: [{employee_name: 'Employee One', job_card: 'JC-1', from_time: '2026-11-26 03:30:00', to_time: '2026-11-26 11:30:00', pay_mode: 'PCR'}],
				qa_rejections: [], quality_inspections: [], measurements: [], downtime_entries: [], breakdowns: [],
				machine_metrics: {availability_percent: 100, available_hours: 12, shift_hours: 12, downtime_hours: 0, recorded_output_interval_hours: 8, definitions: {availability: 'Availability', actual_run_hours: 'Recorded hours'}},
			}}),
		},
	});
	vm.runInContext(source, context);
	handlers.refresh({doc: {name: 'PC-1', status: 'In Progress'}, is_new: () => false, add_custom_button: (name, fn) => {buttons[name] = fn;}});
	buttons['Shift Summary']();
	await new Promise(resolve => setImmediate(resolve));
	assert.equal(config.size, 'extra-large');
	assert.ok(html.includes('table-responsive'));
	assert.ok(html.includes('min-width: 620px'));
	assert.ok(html.includes('2000.00'));
	assert.ok(html.includes('Employee One'));
	assert.equal(shown, true);
});
