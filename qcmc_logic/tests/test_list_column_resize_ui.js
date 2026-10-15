const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path').join(__dirname, '../public/js/list_column_resize.js');

class Element {
    constructor(width = 120) {
        this.defaultWidth = width; this.children = []; this.attributes = {}; this.listeners = {};
        const values = new Map();
        this.style = {
            getPropertyValue: key => values.get(key) || '', getPropertyPriority: () => '',
            setProperty: (key, value) => values.set(key, String(value)), removeProperty: key => values.delete(key),
        };
        const classes = new Set();
        this.classList = {add: name => classes.add(name), remove: name => classes.delete(name), contains: name => classes.has(name)};
    }
    appendChild(child) {this.children.push(child); child.parentElement = this;}
    remove() {this.parentElement.children = this.parentElement.children.filter(child => child !== this);}
    setAttribute(key, value) {this.attributes[key] = String(value);}
    getAttribute(key) {return this.attributes[key] ?? null;}
    getBoundingClientRect() {return {width: (parseFloat(this.style.getPropertyValue('width')) || this.defaultWidth) + (this.style.getPropertyValue('white-space') === 'pre' ? this.formattingWhitespaceWidth || 0 : 0)};}
    addEventListener(event, callback) {this.listeners[event] = callback;}
    cloneNode(deep) {
        const copy = new Element(this.intrinsicWidth ?? this.defaultWidth);
        copy.formattingWhitespaceWidth = this.formattingWhitespaceWidth;
        copy.className = this.className; copy.tagName = this.tagName || 'DIV';
        copy.querySelectorAll = selector => {
            const descendants = [];
            const visit = node => node.children.forEach(child => {descendants.push(child); visit(child);}); visit(copy);
            return selector === '*' ? descendants : selector === '.qcmc-list-column-resizer' ? descendants.filter(child => child.className === 'qcmc-list-column-resizer') : [];
        };
        if (deep) this.children.forEach(child => copy.appendChild(child.cloneNode(true)));
        return copy;
    }
    removeAttribute(key) {delete this.attributes[key];}
    setPointerCapture() {}
    releasePointerCapture() {}
    querySelector() {return this.children.find(child => child.className === 'qcmc-list-column-resizer') || null;}
    querySelectorAll() {return this.children;}
    fire(type, extra = {}) {
        const event = {button: 0, pointerId: 1, clientX: 100, preventDefault() {this.prevented = true;}, stopPropagation() {this.stopped = true;}, ...extra};
        this.listeners[type]?.(event); return event;
    }
}

async function main() {
    assert.ok(fs.existsSync(path), 'Global list column resizing is missing');
    const events = new Map(), settings = {}, saves = [], scrollTargets = [];
    class ListView {
        constructor(doctype) {
            this.doctype = doctype; this.view_name = 'List'; this.renders = 0;
            this.columns = [{type: 'Subject', df: {fieldname: 'name', label: 'ID'}}, {type: 'Status'}, {type: 'Field', df: {fieldname: 'posting_date', label: 'Posting Date'}}];
            this.freshRows();
        }
        freshRows() {
            this.groups = [new Element(), new Element(), new Element()];
            this.groups.forEach(group => [180, 120, 160].forEach(width => group.appendChild(new Element(width))));
            this.root = {
                parentElement: {},
                querySelector: () => this.groups[0],
                querySelectorAll: () => this.groups,
            };
            this.$result = [this.root];
        }
        render_list() {this.renders++; this.freshRows(); return 42;}
    }
    const body = new Element(), head = new Element();
    const media = {matches: false, addEventListener(event, callback) {this.change = callback;}};
    const frappe = {
        qcmc_horizontal_scroll: {register: root => scrollTargets.push(root), refresh() {}},
        session: {user: 'first@example.com'}, views: {},
        get_user_settings: (doctype, key) => settings[`${frappe.session.user}:${doctype}`]?.[key] || {},
        model: {user_settings: {save: async (doctype, key, widths) => {
            const entry = `${frappe.session.user}:${doctype}`;
            settings[entry] ||= {}; settings[entry][key] = {...widths};
            saves.push({user: frappe.session.user, doctype, widths: {...widths}});
        }}},
    };
    const context = {
        frappe, window: {matchMedia: () => media}, console, __: (value, args = []) => value.replace(/\{(\d+)\}/g, (_, i) => args[i]),
        getComputedStyle: () => ({direction: 'ltr'}),
        document: {body, head, getElementById: () => null, createElement: () => new Element()},
        $: () => ({on: (event, handler) => events.set(event, handler)}),
    };
    vm.runInNewContext(fs.readFileSync(path, 'utf8'), context);
    events.get('app_ready')(); // The List bundle has not loaded yet.
    frappe.views.ListView = ListView;
    const list = new ListView('Stock Reconciliation'); context.window.cur_list = list;
    events.get('page-change')();
    assert.equal(scrollTargets.at(-1), list.root.parentElement, 'Visible scrollbar uses the native list scroll container');
    assert.equal(list.groups[0].children[0].children.length, 1, 'Lazy-loaded list headers receive handles');
    const handle = list.groups[0].children[0].querySelector();
    assert.equal(handle.attributes.role, 'separator');
    assert.equal(handle.fire('click').stopped, true, 'Dragging controls must not trigger sorting');
    handle.fire('pointerdown'); handle.fire('pointermove', {clientX: 170}); handle.fire('pointerup');
    await new Promise(setImmediate);
    list.groups.forEach(group => assert.equal(group.children[0].style.getPropertyValue('width'), '250px'));
    assert.equal(settings['first@example.com:Stock Reconciliation'].qcmc_list_column_widths['field:name'], 250);
    assert.equal(saves.length, 1, 'Save once at the end of a drag');
    assert.equal(list.render_list(), 42, 'Preserve native render return values');
    list.groups.forEach(group => assert.equal(group.children[0].getBoundingClientRect().width, 250));
    events.get('page-change')();
    assert.equal(list.groups[0].children[0].children.length, 1, 'Do not duplicate handles');
    const nextHandle = list.groups[0].children[0].querySelector();
    nextHandle.fire('pointerdown'); nextHandle.fire('pointermove', {clientX: 140});
    assert.equal(body.classList.contains('qcmc-resizing-list-column'), true);
    list.render_list();
    assert.equal(body.classList.contains('qcmc-resizing-list-column'), false, 'Realtime rerender must cancel a drag and restore text selection');
    nextHandle.fire('pointerup'); await new Promise(setImmediate);
    assert.equal(saves.length, 1, 'An interrupted drag must not save a pending width');
    const currentHandle = list.groups[0].children[0].querySelector();
    currentHandle.fire('pointerdown'); currentHandle.fire('pointermove', {clientX: 10000});
    assert.equal(list.groups[0].children[0].getBoundingClientRect().width, 1200, 'Clamp overly large widths');
    currentHandle.fire('pointercancel');
    assert.equal(list.groups[0].children[0].getBoundingClientRect().width, 250, 'Cancelled drags restore the prior width');
    assert.equal(saves.length, 1);
    currentHandle.fire('keydown', {key: 'ArrowRight'});
    await new Promise(setImmediate);
    assert.equal(list.groups[1].children[0].getBoundingClientRect().width, 260);
    list.groups[0].children[0].intrinsicWidth = 210;
    list.groups[1].children[0].intrinsicWidth = 360;
    list.groups[2].children[0].intrinsicWidth = 240;
    currentHandle.fire('dblclick'); await new Promise(setImmediate);
    assert.equal(list.groups[0].children[0].getBoundingClientRect().width, 370, 'Double-click fits the longest loaded value plus divider clearance');
    assert.equal(settings['first@example.com:Stock Reconciliation'].qcmc_list_column_widths['field:name'], 370, 'Auto-fit width is saved');
    assert.equal(body.children.length, 0, 'Measurement clones are removed');
    list.groups[0].children[0].intrinsicWidth = 430;
    currentHandle.fire('dblclick'); await new Promise(setImmediate);
    assert.equal(list.groups[1].children[0].getBoundingClientRect().width, 440, 'Header width is included');
    list.groups[1].children[0].intrinsicWidth = 5000;
    currentHandle.fire('dblclick'); await new Promise(setImmediate);
    assert.equal(list.groups[1].children[0].getBoundingClientRect().width, 1200, 'Auto-fit respects the maximum width');
    list.groups.forEach(group => {group.children[0].intrinsicWidth = 90;});
    currentHandle.fire('dblclick'); await new Promise(setImmediate);
    assert.equal(list.groups[1].children[0].getBoundingClientRect().width, 160, 'Auto-fit can shrink a wide column down to its minimum');
    assert.equal(list.groups[1].children[1].getBoundingClientRect().width, 120, 'Other columns remain unchanged');
    list.groups.forEach(group => {group.children[0].intrinsicWidth = 240; group.children[0].formattingWhitespaceWidth = 800;});
    currentHandle.fire('dblclick'); await new Promise(setImmediate);
    assert.equal(list.groups[1].children[0].getBoundingClientRect().width, 250, 'HTML formatter indentation must not inflate the measured width');
    currentHandle.fire('keydown', {key: 'Home'}); await new Promise(setImmediate);
    assert.equal(list.groups[0].children[0].getBoundingClientRect().width, 180, 'Reset restores the native width');
    assert.equal(settings['first@example.com:Stock Reconciliation'].qcmc_list_column_widths['field:name'], null);
    const statusHandle = list.groups[0].children[1].querySelector();
    statusHandle.fire('keydown', {key: 'ArrowRight', shiftKey: true}); await new Promise(setImmediate);
    assert.equal(settings['first@example.com:Stock Reconciliation'].qcmc_list_column_widths['type:Status'], 170);
    const reloaded = new ListView('Stock Reconciliation'); reloaded.render_list();
    assert.equal(reloaded.groups[0].children[1].getBoundingClientRect().width, 170, 'A new list instance restores server-saved widths');
    const other = new ListView('Sales Order'); other.render_list();
    assert.equal(other.groups[0].children[1].getBoundingClientRect().width, 120, 'Widths are isolated by DocType');
    frappe.session.user = 'second@example.com';
    const second = new ListView('Stock Reconciliation'); second.render_list();
    assert.equal(second.groups[0].children[1].getBoundingClientRect().width, 120, 'Widths are isolated by user');
    context.getComputedStyle = () => ({direction: 'rtl'});
    const rtlHandle = second.groups[0].children[0].querySelector();
    rtlHandle.fire('pointerdown'); rtlHandle.fire('pointermove', {clientX: 70}); rtlHandle.fire('pointerup');
    await new Promise(setImmediate);
    assert.equal(second.groups[0].children[0].getBoundingClientRect().width, 210, 'RTL drags grow in the correct direction');
    context.window.cur_list = second;
    media.matches = true; media.change();
    assert.equal(second.groups[0].children[0].getBoundingClientRect().width, 180, 'Mobile layouts retain native widths');
    media.matches = false; media.change();
    assert.equal(second.groups[0].children[0].getBoundingClientRect().width, 210, 'Returning to desktop restores personal widths');
    const report = new ListView('Stock Reconciliation'); report.view_name = 'Report'; report.render_list();
    assert.equal(report.groups[0].children[0].children.length, 0, 'Do not change report grids');
    console.log('Global list column drag, persistence, reset and isolation checks passed');
}
module.exports = {Element};
if (require.main === module) main().catch(error => {console.error(error); process.exitCode = 1;});
