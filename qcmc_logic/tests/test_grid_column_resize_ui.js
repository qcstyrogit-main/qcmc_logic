const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {Element} = require('./test_list_column_resize_ui');
const base = require('node:path').join(__dirname, '../public/js');

async function main() {
    assert.ok(fs.existsSync(`${base}/grid_column_resize.js`), 'Form table resizing is missing');
    const events = new Map(), frames = [], settings = {}, saves = [], scrollTargets = [];
    const body = new Element(), head = new Element();
    class Grid {
        constructor(parent, field = 'items') {
            this.frm = parent; this.df = {fieldname: field}; this.renders = 0;
            this.visible_columns = [[{fieldname: 'item_code', label: 'Item Code'}, 2], [{fieldname: 'qty', label: 'Qty', sticky: 1}, 1]];
            this.rebuild();
        }
        rebuild() {
            const root = new Element();
            this.groups = [new Element(), new Element(), new Element()];
            this.groups.forEach(group => {
                group.closest = () => root;
                group.appendChild(new Element(31)); // Checkbox remains fixed.
                group.appendChild(new Element(40)); // Row number remains fixed.
                ['item_code', 'qty'].forEach((field, index) => {
                    const cell = new Element(index ? 100 : 180);
                    cell.setAttribute('data-fieldname', field); group.appendChild(cell);
                });
                group.appendChild(new Element(30)); // Row-edit button remains fixed.
            });
            this.foreignRow = new Element(); this.foreignRow.closest = () => new Element();
            this.foreignCell = new Element(77); this.foreignCell.setAttribute('data-fieldname', 'item_code');
            this.foreignRow.appendChild(this.foreignCell);
            root.querySelectorAll = () => [...this.groups, this.foreignRow];
            this.form_grid = [root]; this.wrapper = [root];
            this.header_row = {row: [this.groups[0]]};
        }
        refresh() {this.renders++; this.rebuild(); return 17;}
        render_result_rows() {this.rebuild(); return 23;}
    }
    const frm = {doctype: 'Stock Entry', grids: [], dirty() {throw Error('Resizing must never dirty the transaction');}};
    const grid = new Grid(frm); frm.grids.push({grid});
    const media = {matches: false, addEventListener(event, callback) {this.listeners ||= []; this.listeners.push(callback);}};
    const frappe = {
        qcmc_horizontal_scroll: {register: root => scrollTargets.push(root), refresh() {}},
        session: {user: 'employee@example.com'}, views: {},
        get_user_settings: (doctype, key) => settings[`${frappe.session.user}:${doctype}`]?.[key] || {},
        model: {user_settings: {save: async (doctype, key, widths) => {
            const entry = `${frappe.session.user}:${doctype}`;
            settings[entry] ||= {}; settings[entry][key] = {...widths}; saves.push({doctype, key, widths: {...widths}});
        }}},
    };
    const context = {frappe, window: {cur_frm: frm, matchMedia: () => media}, console,
        ResizeObserver: class {constructor(callback) {this.callback = callback;} observe(root) {this.root = root;} disconnect() {}},
        document: {body, head, createElement: () => new Element()},
        getComputedStyle: () => ({direction: 'ltr'}),
        __: (text, args = []) => text.replace(/\{(\d+)\}/g, (_, i) => args[i]),
        $: () => ({on: (event, handler) => {const previous = events.get(event); events.set(event, (...args) => {previous?.(...args); handler(...args);});}}),
        requestAnimationFrame: callback => {frames.push(callback); return frames.length;},
    };
    vm.runInNewContext(fs.readFileSync(`${base}/list_column_resize.js`, 'utf8'), context);
    events.get('app_ready')();
    vm.runInNewContext(fs.readFileSync(`${base}/grid_column_resize.js`, 'utf8'), context);
    const flush = async () => {while (frames.length) frames.shift()(); await new Promise(setImmediate);};
    events.get('form-refresh')({}, frm); await flush();
    assert.equal(scrollTargets.at(-1), grid.form_grid[0], 'Grid registers its own scroll container');
    const handle = grid.groups[0].children[2].querySelector();
    assert.ok(handle, 'Items header receives a resize handle');
    assert.equal(grid.groups[0].children[0].children.length, 0, 'Checkbox has no resize handle');
    assert.equal(grid.groups[0].children[1].children.length, 0, 'Row number has no resize handle');
    assert.equal(grid.groups[0].children.at(-1).children.length, 0, 'Row-edit button has no resize handle');
    handle.fire('pointerdown'); handle.fire('pointermove', {clientX: 170}); handle.fire('pointerup'); await flush();
    grid.groups.forEach(group => {
        assert.equal(group.children[2].getBoundingClientRect().width, 250);
        assert.equal(group.children[3].getBoundingClientRect().width, 100, 'Other columns retain their widths');
        assert.equal(group.children[3].style.getPropertyValue('left'), '71px', 'A nonsticky column must not move the pinned-column offset');
    });
    assert.equal(saves.at(-1).key, 'qcmc_grid_column_widths_items');
    assert.equal(saves.at(-1).doctype, 'Stock Entry');
    assert.equal(grid.foreignCell.getBoundingClientRect().width, 77, 'Nested tables must not inherit outer table widths');
    grid.visible_columns[0][0].sticky = 1;
    events.get('form-refresh')({}, frm); await flush();
    assert.equal(grid.groups[0].children[3].style.getPropertyValue('left'), '321px', 'Contiguous pinned columns use the resized preceding pinned width');
    grid.visible_columns[0][0].sticky = 0;
    events.get('form-refresh')({}, frm); await flush();
    assert.equal(grid.refresh(), 17); await flush();
    grid.groups.forEach(group => assert.equal(group.children[2].getBoundingClientRect().width, 250));
    const drag = grid.groups[0].children[2].querySelector();
    const savedCount = saves.length;
    drag.fire('pointerdown'); drag.fire('pointermove', {clientX: 130}); grid.refresh(); await flush();
    assert.equal(body.classList.contains('qcmc-resizing-list-column'), false);
    assert.equal(saves.length, savedCount);
    grid.groups[0].children[2].intrinsicWidth = 220;
    grid.groups[1].children[2].intrinsicWidth = 410;
    grid.groups[2].children[2].intrinsicWidth = 270;
    grid.groups[0].children[2].querySelector().fire('dblclick'); await flush();
    assert.equal(grid.groups[0].children[2].getBoundingClientRect().width, 420, 'Grid auto-fit uses its longest value');
    assert.equal(saves.at(-1).widths['field:item_code'], 420);
    grid.groups[0].children[2].querySelector().fire('keydown', {key: 'Home'}); await flush();
    assert.equal(grid.groups[0].children[2].getBoundingClientRect().width, 180);
    assert.equal(saves.at(-1).widths['field:item_code'], null);
    const other = new Grid(frm, 'scrap_items'); frm.grids.push({grid: other});
    events.get('form-refresh')({}, frm); await flush();
    other.groups[0].children[2].querySelector().fire('keydown', {key: 'ArrowRight'}); await flush();
    assert.equal(settings['employee@example.com:Stock Entry'].qcmc_grid_column_widths_scrap_items['field:item_code'], 190);
    assert.equal(grid.groups[0].children[2].getBoundingClientRect().width, 180, 'Tables have separate settings');
    assert.equal(other.render_result_rows(), 23); await flush();
    assert.equal(other.groups[1].children[2].getBoundingClientRect().width, 190, 'Pagination/new rows restore the saved width');
    const nextForm = {doctype: 'Stock Entry', grids: []};
    const reloaded = new Grid(nextForm, 'scrap_items'); nextForm.grids.push({grid: reloaded});
    events.get('form-refresh')({}, nextForm); await flush();
    assert.equal(reloaded.groups[0].children[2].getBoundingClientRect().width, 190, 'New documents restore personal table widths');
    const differentParent = {doctype: 'Sales Order', grids: []};
    const separate = new Grid(differentParent, 'scrap_items'); differentParent.grids.push({grid: separate});
    events.get('form-refresh')({}, differentParent); await flush();
    assert.equal(separate.groups[0].children[2].getBoundingClientRect().width, 180, 'Parent DocTypes have independent table widths');
    frappe.session.user = 'another@example.com';
    const otherUser = new Grid(nextForm, 'scrap_items'); nextForm.grids = [{grid: otherUser}];
    events.get('form-refresh')({}, nextForm); await flush();
    assert.equal(otherUser.groups[0].children[2].getBoundingClientRect().width, 180, 'Users have independent table widths');
    const hidden = new Grid(nextForm, 'hidden_items'); nextForm.grids = [{grid: hidden}];
    hidden.form_grid[0].defaultWidth = 0;
    hidden.groups.forEach(group => {group.children[2].defaultWidth = 0; group.children[3].defaultWidth = 0;});
    events.get('form-refresh')({}, nextForm); await flush();
    assert.equal(hidden.groups[0].children[2].querySelector(), null);
    assert.ok(hidden._qcmcResizeObserver, 'Initially hidden sections must still be observed');
    hidden.form_grid[0].defaultWidth = 400;
    hidden.groups.forEach(group => {group.children[2].defaultWidth = 180; group.children[3].defaultWidth = 100;});
    hidden._qcmcResizeObserver.callback([{contentRect: {width: 400}}]); await flush();
    assert.ok(hidden.groups[0].children[2].querySelector(), 'Opening a hidden section installs handles');
    console.log('Form table resizing, reset, refresh, pagination and table isolation checks passed');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
