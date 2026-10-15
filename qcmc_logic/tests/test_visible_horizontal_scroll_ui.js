const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {Element} = require('./test_list_column_resize_ui');

const frames = [], events = new Map(), observers = [];
const body = new Element(), head = new Element();
const context = {
    document: {body, head, createElement: () => new Element(), addEventListener: (event, handler) => events.set(event, handler)},
    window: {innerHeight: 800, innerWidth: 1200, addEventListener: (event, handler) => events.set(event, handler), matchMedia: () => ({matches: false})},
    frappe: {}, __: text => text, getComputedStyle: () => ({direction: 'ltr'}),
    requestAnimationFrame: callback => frames.push(callback),
    ResizeObserver: class {constructor(callback) {this.callback = callback; observers.push(this);} observe() {} disconnect() {}},
    MutationObserver: class {constructor(callback) {this.callback = callback;} observe() {} disconnect() {}},
    $: () => ({on: (event, handler) => events.set(event, handler)}),
};
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname, '../public/js/visible_horizontal_scroll.js'), 'utf8'), context);
const root = new Element();
root.isConnected = true; root.clientWidth = 900; root.scrollWidth = 1600; root.scrollLeft = 0;
root.removeEventListener = () => {};
let rect = {left: 100, right: 1000, top: 150, bottom: 1500, width: 900, height: 1350};
root.getBoundingClientRect = () => rect;
const flush = () => {while (frames.length) frames.shift()();};
context.frappe.qcmc_horizontal_scroll.register(root); flush();
const bar = body.children[0];
assert.equal(bar.hidden, false, 'Scrollbar is visible before reaching the final row');
assert.equal(bar.style.getPropertyValue('left'), '100px');
bar.scrollLeft = 250; bar.fire('scroll');
assert.equal(root.scrollLeft, 250, 'Pinned scrollbar moves the actual table');
root.scrollLeft = 400; root.fire('scroll');
assert.equal(bar.scrollLeft, 400, 'Native scrolling updates the pinned scrollbar');
context.frappe.qcmc_horizontal_scroll.register(root); flush();
assert.equal(body.children.length, 1, 'Rerenders reuse one scrollbar');
root.scrollWidth = 900; observers[0].callback(); flush();
assert.equal(bar.hidden, true, 'Hide when columns fit');
root.scrollWidth = 1700; observers[0].callback(); flush();
assert.equal(bar.hidden, false, 'Resizing a column restores the scrollbar');
rect = {...rect, bottom: 650}; events.get('scroll')(); flush();
assert.equal(bar.hidden, false, 'Keep scrollbar visible when the table or list panel ends inside the viewport');
assert.equal(bar.style.getPropertyValue('top'), '634px', 'Place scrollbar above the list footer');
rect = {...rect, bottom: 1500, top: 900}; events.get('scroll')(); flush();
assert.equal(bar.hidden, true, 'Off-screen tables do not show a scrollbar');
rect = {...rect, top: 150}; context.getComputedStyle = () => ({direction: 'rtl'});
events.get('resize')(); flush();
assert.equal(bar.style.getPropertyValue('direction'), 'rtl');
bar.scrollLeft = -125; bar.fire('scroll');
assert.equal(root.scrollLeft, -125, 'RTL scrolling preserves native negative offsets');
root.isConnected = false; events.get('page-change')(); flush();
assert.equal(bar.hidden, true, 'Navigation removes stale scroll targets');
const inner = new Element(), viewport = new Element();
inner.isConnected = true; inner.clientWidth = 900; inner.scrollWidth = 1800; inner.scrollLeft = 0;
inner.removeEventListener = () => {};
inner.getBoundingClientRect = () => ({left: 100, right: 1000, top: 150, bottom: 1500, width: 900});
viewport.getBoundingClientRect = () => ({left: 100, right: 1000, top: 150, bottom: 600, width: 900});
context.frappe.qcmc_horizontal_scroll.register(inner, viewport); flush();
assert.equal(bar.hidden, false, 'Lists with a tall inner result and an independently scrolling outer panel are supported');
assert.equal(bar.style.getPropertyValue('top'), '584px');
bar.scrollLeft = -180; bar.fire('scroll');
assert.equal(inner.scrollLeft, -180, 'The actual inner horizontal scroller is synchronized');
console.log('Visible horizontal scrollbar synchronization, resize, navigation and RTL checks passed');
