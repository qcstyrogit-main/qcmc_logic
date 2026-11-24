// Site-free browser logic tests: node --test this file
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function fixture() {
	const routes = [];
	const messages = [];
	const storage = {};
	const context = vm.createContext({
		frappe: {pages: {'production-floor-workbench': {}}, set_route: (...args) => routes.push(args), new_doc: (...args) => routes.push(args), msgprint: message => messages.push(message)},
		__: value => value,
		window: {confirm: () => true},
		console: {error() {}},
		sessionStorage: {setItem: (key, value) => {storage[key] = value;}},
	});
	vm.runInContext(fs.readFileSync(path.join(__dirname, '../qcmc_logics/page/production_floor_workbench/production_floor_workbench.js'), 'utf8') +
		'\nglobalThis.Workbench = ProductionFloorWorkbench;', context);
	return {Workbench: context.Workbench, routes, messages, storage};
}

test('machine request sequence drops stale Process Card response', async () => {
	const {Workbench} = fixture();
	const wb = Object.create(Workbench.prototype);
	let selected = {id: 'm1', kind: 'machine', workstation: 'WS-1'};
	const pending = [];
	Object.assign(wb, {
		site: 'Guyong', selected_element: () => selected, shift_date: '2026-11-10', shift_type: '',
		call: () => new Promise(resolve => pending.push(resolve)), render_details() {}, machineRequestId: 0,
	});
	const oldRequest = wb.load_selected_machine();
	selected = {id: 'm2', kind: 'machine', workstation: 'WS-2'};
	const newRequest = wb.load_selected_machine();
	pending[1]({workstation: {name: 'WS-2'}, process_cards: [{name: 'PC-2'}], can_create: false});
	await newRequest;
	pending[0]({workstation: {name: 'WS-1'}, process_cards: [{name: 'PC-1'}], can_create: false});
	await oldRequest;
	assert.equal(wb.machineContext.workstation.name, 'WS-2');
});

test('existing Process Card and Workstation routes use standard Desk form route', async () => {
	const {Workbench, routes} = fixture();
	const wb = Object.create(Workbench.prototype);
	wb.remember_floor_context = () => {};
	await wb.action('open-card', 'PC-1');
	await wb.action('open-workstation', 'WS-1');
	assert.deepEqual(routes, [['process-card-workbench', 'PC-1'], ['Form', 'Workstation', 'WS-1']]);
});

test('Process Card create action opens its Workbench and carries machine shift defaults', async () => {
	const {Workbench, routes, storage} = fixture();
	const wb = Object.create(Workbench.prototype);
	Object.assign(wb, {
		machineContext: {can_create: true, workstation: {name: 'WS-1'}}, site: 'Guyong', company: 'Company A',
		shift_date: '2026-11-10', shift_type: 'Day', remember_floor_context() {},
	});
	await wb.action('create-card');
	assert.deepEqual(routes[0], ['process-card-workbench', 'new']);
	assert.deepEqual(JSON.parse(storage.qcmc_process_card_create_context), {company: 'Company A', site: 'Guyong', workstation: 'WS-1', shift_date: '2026-11-10', shift_type: 'Day'});
	wb.machineContext.can_create = false;
	await wb.action('create-card');
	assert.equal(routes.length, 1);
});

test('authorized users can enter building edit mode on mobile and desktop', async () => {
	const {Workbench} = fixture();
	const wb = Object.create(Workbench.prototype);
	let renders = 0;
	Object.assign(wb, {can_edit: true, mode: 'view', render: () => renders++});
	await wb.action('edit');
	assert.equal(wb.mode, 'edit');
	assert.equal(renders, 1);
	assert.doesNotMatch(fs.readFileSync(path.join(__dirname, '../qcmc_logics/page/production_floor_workbench/production_floor_workbench.js'), 'utf8'), /matchMedia\("\(min-width: 900px\)"\)/);
});

test('building stays selected for renaming while its machine interior is open', async () => {
	const {Workbench} = fixture();
	const wb = Object.create(Workbench.prototype);
	const building = {id: 'b1', kind: 'building', label: 'Old name', x: 0, y: 0, w: 500, h: 400, interior: {width: 1200, height: 800, elements: [{id: 'm1', kind: 'machine', workstation: 'WS-1'}]}};
	Object.assign(wb, {
		layout: {buildings: [building]}, building: null, selected: null, mode: 'edit', expandedBuildings: new Set(),
		machineRequestId: 0, render() {}, render_details() {}, render_canvas() {}, render_toolbar() {},
	});
	await wb.action('building', 'b1');
	assert.equal(wb.selected_element(), building);
	wb.update_property({target: {dataset: {property: 'label'}, value: 'Renamed building'}});
	assert.equal(building.label, 'Renamed building');
	assert.equal(building.interior.elements[0].workstation, 'WS-1');
});

test('deleting a selected building removes it and its contained machines after confirmation', async () => {
	const {Workbench} = fixture();
	const wb = Object.create(Workbench.prototype);
	const building = {id: 'b1', kind: 'building', label: 'Building A', interior: {width: 1200, height: 800, elements: [{id: 'm1', kind: 'machine', workstation: 'WS-1'}]}};
	Object.assign(wb, {
		layout: {buildings: [building]}, building: 'b1', selected: 'b1', mode: 'edit', expandedBuildings: new Set(['b1']),
		changed() { this.did_change = true; },
	});
	await wb.action('remove');
	assert.deepEqual(wb.layout.buildings, []);
	assert.equal(wb.building, null);
	assert.equal(wb.did_change, true);
});

test('site layout remains open when Workstation context request fails', async () => {
	const {Workbench, messages} = fixture();
	const wb = Object.create(Workbench.prototype);
	Object.assign(wb, {
		dirty: false, expandedBuildings: new Set(), zoom: 1, pan: {x: 0, y: 0},
		call: async method => method === 'get_layout'
			? {layout: {width: 1200, height: 800, buildings: []}, version: 3, can_edit: true, company: 'Company A', plant_floors: ['Floor A']}
			: Promise.reject(new Error('Permission denied for Workstation list')),
		render() {}, render_tree() {}, render_canvas() {},
	});
	await wb.open_site('Guyong');
	assert.equal(wb.layout.buildings.length, 0);
	assert.equal(wb.context.workstations.length, 0);
	assert.match(messages[0].message, /Permission denied/);
});

test('machine selection starts empty-state filtered discovery and date defaults to today', () => {
	const source = fs.readFileSync(path.join(__dirname, '../qcmc_logics/page/production_floor_workbench/production_floor_workbench.js'), 'utf8');
	assert.match(source, /this\.shift_date = frappe\.datetime\.get_today\(\)/);
	assert.match(source, /No Process Card for the selected machine and shift\./);
	assert.match(source, /fieldtype: "Link", options: "Shift Type"/);
	assert.match(source, /this\.call\("get_machine_context"/);
});
