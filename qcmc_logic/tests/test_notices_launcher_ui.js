const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../public/js/login_notices.js'), 'utf8');

async function load(user) {
    let requests = 0;
    let route = [];
    let hasToolbar = true, hasNavbar = true, hasSidebar = true;
    const events = new Map(), routerEvents = new Map();
    const elements = new Map();
    function node() {
        return {children: [], style: {}, attributes: {},
            appendChild(child) {
                if (child.parentElement) child.parentElement.children = child.parentElement.children.filter(item => item !== child);
                this.children.push(child); child.parentElement = this;
                if (child.id) elements.set(child.id, child);
            },
            prepend(child) {this.appendChild(child); this.children = [child, ...this.children.filter(item => item !== child)];},
            setAttribute(key, value) {this.attributes[key] = value;},
            addEventListener(event, callback) {this[event] = callback;},
        };
    }
    const body = node(), head = node(), toolbar = node(), navbar = node(), sidebar = node(), search = node();
    sidebar.appendChild(search);
    const context = {
        document: {body, head, getElementById: id => elements.get(id), createElement: node,
            querySelector: selector => selector.includes('.standard-items-sections') ? (hasSidebar ? sidebar : null) : (hasNavbar ? navbar : null)},
        window: {localStorage: {getItem() {}, setItem() {}}}, console: {warn() {}},
        __: text => text, $: target => ({on(event, handler) {events.set(event, handler);}, tooltip(options) {if (typeof options === 'object') target.tooltipOptions = options;}}),
        frappe: {session: {user}, boot: {qcmc_login_notice_session: 'test'},
            get_route: () => route,
            router: {on(event, handler) {routerEvents.set(event, handler);}},
            container: {page: {querySelector: () => hasToolbar ? toolbar : null}},
            call: async () => {requests++; throw Error('offline');}},
    };
    vm.runInNewContext(source, context);
    const ready = events.get('app_ready');
    await ready();
    return {body, head, toolbar, navbar, sidebar, search, ready, get requests() {return requests;},
        setRoute(next, options = {}) {
            route = next; hasToolbar = options.toolbar ?? true; hasNavbar = options.navbar ?? true;
            hasSidebar = options.sidebar ?? true;
            routerEvents.get('change')?.();
            events.get('page-change')?.();
        },
    };
}

async function main() {
    const app = await load('employee@example.com');
    const launcher = app.body.children.find(child => child.id === 'qcmc-open-notices');
    assert.ok(launcher, 'The main Desk screen must show the compact launcher');
    assert.equal(launcher.type, 'button');
    assert.equal(launcher.attributes['aria-haspopup'], 'dialog');
    assert.equal(launcher.attributes['aria-label'], 'News & Celebrations', 'The collapsed sparkle button must retain its accessible name');
    assert.equal(launcher.title, undefined, 'Launcher must not use the browser tooltip');
    assert.equal(launcher.tooltipOptions.container, 'body');
    assert.equal(launcher.tooltipOptions.boundary, 'window');
    assert.equal(launcher.tooltipOptions.title(), 'News & Celebrations');
    assert.equal(launcher.children.at(-1).textContent, 'News & Celebrations');
    assert.match(launcher.className, /qcmc-launcher-compact/);
    assert.match(launcher.className, /qcmc-launcher-desk/);
    assert.ok(!launcher.innerHTML?.includes('<svg'), 'Desk must use the compact sparkle style without balloons');
    const requestsBefore = app.requests;
    await launcher.click();
    assert.equal(app.requests, requestsBefore + 1, 'Launcher reopens the existing notices flow');
    await app.ready();
    assert.equal(app.body.children.length, 1, 'Repeated app_ready must not add duplicate launchers');
    app.setRoute(['List', 'Stock Reconciliation', 'List']);
    assert.equal(launcher.parentElement, app.sidebar, 'Transaction pages must put the button in their sidebar');
    assert.equal(app.sidebar.children[0], launcher, 'The button must appear above Search');
    assert.equal(app.sidebar.children[1], app.search);
    assert.match(launcher.className, /qcmc-launcher-compact/);
    assert.equal(launcher.hidden, false);
    assert.equal(app.body.children.length, 0, 'No floating button may cover transaction controls');
    app.setRoute(['Form', 'Stock Reconciliation', 'MAT-1']);
    assert.equal(app.sidebar.children.length, 2, 'Route changes must reuse a single sidebar button');
    assert.equal(app.toolbar.children.length, 0, 'Do not crowd the transaction toolbar');
    app.setRoute(['query-report', 'Stock Balance'], {sidebar: false});
    assert.equal(launcher.parentElement, app.toolbar, 'Layouts without a sidebar retain toolbar access');
    app.setRoute(['query-report', 'Stock Balance'], {sidebar: false, toolbar: false});
    assert.equal(launcher.parentElement.parentElement, app.navbar, 'Layouts without a page toolbar use the navbar');
    app.setRoute(['Form', 'User', 'employee@example.com'], {sidebar: false, toolbar: false, navbar: false});
    assert.equal(launcher.hidden, true, 'While a transaction header loads, do not show a floating fallback');
    app.setRoute(['Workspaces', 'Inventory']);
    assert.equal(launcher.parentElement, app.sidebar, 'Inventory dashboards must use their sidebar');
    assert.match(launcher.className, /qcmc-launcher-compact/);
    app.setRoute(['Workspaces', 'Home']);
    assert.equal(launcher.parentElement, app.sidebar, 'A workspace named Home is still a dashboard');
    app.setRoute(['dashboard', 'Sales']);
    assert.equal(launcher.parentElement, app.sidebar);
    app.setRoute([]);
    assert.equal(launcher.parentElement, app.body);
    assert.equal(launcher.hidden, false);
    assert.match(launcher.className, /qcmc-launcher-compact/);
    assert.match(launcher.className, /qcmc-launcher-desk/);
    const guest = await load('Guest');
    assert.equal(guest.body.children.length, 0, 'Guest pages must not show company notices');
    console.log('Floating celebration launcher checks passed');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
