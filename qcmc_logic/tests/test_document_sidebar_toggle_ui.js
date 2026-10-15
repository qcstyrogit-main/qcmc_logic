const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {Element} = require('./test_list_column_resize_ui');
const path = require('node:path').join(__dirname, '../public/js/document_sidebar_toggle.js');

class Node extends Element {
    constructor() {super(); this.classList.toggle = (name, enabled) => enabled ? this.classList.add(name) : this.classList.remove(name);}
    addEventListener(event, callback) {
        const previous = this.listeners[event];
        this.listeners[event] = value => {previous?.(value); callback(value);};
    }
    appendChild(child) {
        if (child.parentElement) child.parentElement.children = child.parentElement.children.filter(item => item !== child);
        super.appendChild(child);
    }
    prepend(child) {
        if (child.parentElement) child.parentElement.children = child.parentElement.children.filter(item => item !== child);
        this.children = [child, ...this.children.filter(item => item !== child)]; child.parentElement = this;
    }
}

async function main() {
    assert.ok(fs.existsSync(path), 'Document sidebar toggle is missing');
    const events = new Map(), storage = new Map(), timers = [], observers = []; let storageBlocked = false;
    const context = {
        document: {head: new Node(), createElement: () => new Node(), querySelector: () => null},
        window: {localStorage: {
            getItem(key) {if (storageBlocked) throw Error('blocked'); return storage.get(key) ?? null;},
            setItem(key, value) {if (storageBlocked) throw Error('blocked'); storage.set(key, value);},
        }},
        frappe: {session: {user: 'first@example.com'}, get_route: () => ['Form', 'Stock Entry', 'STE-1']},
        __: text => text, $: target => ({on: (event, handler) => events.set(event, handler), trigger: event => target.dispatchEvent({type: event}), tooltip(options) {if (typeof options === 'object') target.tooltipOptions = options;}}),
        setTimeout: callback => {timers.push(callback);},
        getComputedStyle: () => ({display: 'block'}),
        MutationObserver: class {
            constructor(callback) {this.callback = callback; observers.push(this);}
            observe(target) {this.target = target;}
            disconnect() {this.target = null;}
        },
    };
    function form(doctype = 'Stock Entry', isNew = false) {
        const layout = new Node(), sidebar = new Node(), toolbar = new Node(), panel = new Node();
        layout.appendChild(sidebar);
        const targets = {};
        ['.add-assignment-label', '.add-attachment-btn', '.tags-input', '.share-label'].forEach(selector => {
            const target = new Node(); target.clicked = 0; target.focused = 0;
            target.click = () => target.clicked++;
            target.focus = () => target.focused++;
            targets[selector] = target;
        });
        ['.form-print button', '.liked-by .like-icon'].forEach(selector => {
            const target = new Node(); target.clicked = 0; target.click = () => target.clicked++;
            targets[selector] = target;
        });
        targets['.liked-by'] = new Node();
        // Native heart is SVG, which does not implement HTMLElement.click().
        delete targets['.liked-by .like-icon'].click;
        targets['.liked-by .like-icon'].dispatchEvent = event => {
            if (event.type === 'click') targets['.liked-by .like-icon'].clicked++;
        };
        const tagsSection = new Node(); panel.isConnected = true; panel.appendChild(tagsSection);
        tagsSection.appendChild(targets['.tags-input']);
        tagsSection.querySelector = () => targets['.tags-input'];
        sidebar.querySelector = selector => selector === '.form-sidebar' ? panel : selector === '.form-tags' ? tagsSection : targets[selector] || null;
        toolbar.can_rename = () => true;
        return {doctype, doc: {name: 'STE-1', __islocal: isNew, owner: 'creator@example.com', modified_by: 'editor@example.com', modified: '2026-10-15 10:00:00', creation: '2026-10-01 08:00:00'}, page: {sidebar: [sidebar], page_actions: [toolbar]}, layout, sidebar, toolbar, targets,
            renamed: 0,
            rename_doc() {this.renamed++;},
            tags: {tags: {active: false, activate() {this.active = true;}}}};
    }
    const dialogs = [];
    context.frappe.ui = {Dialog: class {
        constructor(options) {this.options = options; this.body = new Node(); dialogs.push(this);}
        show() {this.shown = true;}
        hide() {this.options.on_hide?.();}
    }};
    vm.runInNewContext(fs.readFileSync(path, 'utf8'), context);
    const navigation = new Node(); let navigationToggles = 0;
    context.document.querySelector = selector => selector === '.body-sidebar' ? navigation : null;
    context.frappe.app = {sidebar: {toggle_width() {navigationToggles++;}}};
    // Frappe starts routing asynchronously; app_ready can run while the
    // router's current_route is still null.
    const getRoute = context.frappe.get_route;
    context.frappe.get_route = () => null;
    assert.doesNotThrow(() => events.get('app_ready')(), 'Unresolved startup route must not interrupt Desk startup');
    assert.doesNotThrow(() => events.get('page-change')(), 'Unresolved route must be safe during navigation');
    assert.equal(navigation.children.length, 0, 'Keep the native left navigation untouched');
    assert.equal(navigationToggles, 0, 'The details control must not toggle left navigation');
    context.frappe.get_route = getRoute;
    const frm = form(); const original = JSON.stringify(frm.doc); context.window.cur_frm = frm;
    events.get('form-refresh')({}, frm);
    const button = frm._qcmcDocumentDetailsToggle.button;
    assert.equal(button.parentElement, frm.sidebar, 'Expanded toggle belongs at the bottom of the details panel');
    assert.equal(frm.sidebar.children.at(-1), button);
    assert.equal(frm.toolbar.children.length, 0, 'No toolbar toggle remains');
    assert.equal(button.attributes['aria-expanded'], 'true');
    assert.equal(button.attributes['aria-label'], 'Hide details');
    assert.equal(button.tooltipOptions.placement, 'left');
    assert.equal(button.tooltipOptions.boundary, 'window', 'Tooltip must not be squeezed into the narrow scrollable sidebar');
    assert.match(button.tooltipOptions.template, /qcmc-action-tooltip/, 'Tooltip has a noninteractive hover surface');
    assert.equal(button.tooltipOptions.title(), 'Hide details');
    assert.equal(button._qcmcTooltipEnabled, false, 'Expanded details must not show tooltips');
    assert.equal(button.children.length, 0, 'The toolbar toggle must be icon-only');
    const edge = frm._qcmcDocumentDetailsToggle.edge;
    assert.ok(edge, 'The panel must have a border target');
    edge.fire('click');
    assert.equal(frm.layout.classList.contains('qcmc-document-details-collapsed'), true, 'A single border click must collapse');
    edge.fire('click');
    assert.equal(frm.layout.classList.contains('qcmc-document-details-collapsed'), false, 'A single border click must reopen');
    button.fire('click');
    assert.equal(frm.layout.classList.contains('qcmc-document-details-collapsed'), true);
    assert.equal(button.attributes['aria-expanded'], 'false');
    assert.equal(button.attributes['aria-label'], 'Show details');
    assert.equal(button.tooltipOptions.title(), 'Show details', 'Tooltip follows the current toggle state');
    assert.equal(button._qcmcTooltipEnabled, true, 'Collapsed details enables tooltips');
    assert.equal(edge.parentElement, frm.sidebar, 'The collapsed click target stays on the rail divider beside the form');
    edge.fire('click');
    assert.equal(frm.layout.classList.contains('qcmc-document-details-collapsed'), false);
    assert.equal(edge.parentElement, frm.sidebar, 'The expanded border follows the panel');
    edge.fire('click');
    assert.equal(button.attributes['aria-controls'], frm.sidebar.id);
    events.get('form-refresh')({}, frm);
    assert.equal(frm.sidebar.children.filter(child => child === button).length, 1, 'Refresh must not duplicate the collapsed control');
    assert.equal(button.parentElement, frm.sidebar, 'Collapsed toggle stays accessible in the narrow sidebar rail');
    assert.equal(frm.layout.classList.contains('qcmc-document-details-collapsed'), true, 'Native sidebar refresh must not reopen a collapsed panel');
    const shortcuts = frm._qcmcDocumentDetailsToggle.shortcuts;
    assert.ok(shortcuts, 'Collapsed panel provides action shortcuts');
    assert.equal(shortcuts.hidden, false);
    assert.equal(shortcuts.children.length, 8);
    assert.equal(shortcuts.children[0].tooltipOptions.title(), 'Assign');
    for (const [index, selector] of ['.add-assignment-label', '.add-attachment-btn', '.tags-input', '.share-label'].entries()) {
        shortcuts.children[index].fire('click');
        assert.equal(frm.layout.classList.contains('qcmc-document-details-collapsed'), true, 'Shortcut must keep the panel collapsed');
        timers.splice(0).forEach(callback => callback());
        assert.equal(frm.targets[selector][index === 2 ? 'focused' : 'clicked'], 1, 'Shortcut opens the native action');
        assert.equal(shortcuts.hidden, false, 'Action icons remain available');
        if (index === 2) {
            assert.equal(dialogs.at(-1).shown, true, 'Tags opens a popup editor');
            assert.equal(dialogs.at(-1).options.size, 'small', 'Tags editor uses a compact popup');
            assert.equal(frm.tags.tags.active, true, 'Activate the native tag input before focusing it');
            assert.equal(dialogs.at(-1).body.classList.contains('qcmc-tags-dialog-body'), true);
            dialogs.at(-1).hide();
            assert.equal(frm.sidebar.querySelector('.form-tags').parentElement, frm.sidebar.querySelector('.form-sidebar'), 'Closing Tags restores the native editor');
        }
    }
    events.get('form-refresh')({}, frm);
    assert.equal(shortcuts.children.length, 8, 'Refresh does not duplicate shortcuts');
    shortcuts.children[4].fire('click');
    assert.equal(frm.renamed, 1, 'Rename uses the native action');
    shortcuts.children[5].fire('click');
    assert.equal(frm.targets['.form-print button'].clicked, 1, 'Print opens the native print view');
    shortcuts.children[6].fire('click');
    assert.equal(frm.targets['.liked-by .like-icon'].clicked, 1, 'Favorite uses the native action');
    frm.targets['.liked-by'].style.setProperty('pointer-events', 'none');
    shortcuts.children[6].fire('click');
    assert.equal(frm.targets['.liked-by .like-icon'].clicked, 1, 'Do not submit duplicate favorite requests while saving');
    frm.targets['.liked-by'].style.removeProperty('pointer-events');
    frm.targets['.liked-by'].classList.add('liked');
    const favoriteObserver = observers.find(observer => observer.target === frm.targets['.liked-by']);
    assert.ok(favoriteObserver, 'Favorite state must update without refreshing the form');
    favoriteObserver.callback();
    assert.equal(shortcuts.children[6].attributes['aria-pressed'], 'true', 'Favorite reflects native state');
    frm.targets['.liked-by'].classList.remove('liked');
    favoriteObserver.callback();
    assert.equal(shortcuts.children[6].attributes['aria-pressed'], 'false', 'Removing favorite restores the outline state');
    edge.fire('click');
    assert.equal(frm.layout.classList.contains('qcmc-document-details-collapsed'), false, 'Border still opens after using shortcuts');
    edge.fire('click');
    shortcuts.children[7].fire('click');
    assert.equal(dialogs.at(-1).options.title, 'Document info');
    const infoText = dialogs.at(-1).body.children.map(row => row.children.map(cell => cell.textContent).join(': ')).join('\n');
    assert.ok(infoText.includes('STE-1') && infoText.includes('creator@example.com') && infoText.includes('editor@example.com') && infoText.includes('2026-10-15 10:00:00'));
    assert.equal(frm.layout.classList.contains('qcmc-document-details-collapsed'), true, 'Extra actions keep the panel collapsed');
    frm.toolbar.can_rename = () => false;
    events.get('form-refresh')({}, frm);
    assert.equal(shortcuts.children[4].hidden, true, 'Rename respects native permissions');
    shortcuts.children[4].fire('click');
    assert.equal(frm.renamed, 1, 'Rename remains guarded if permissions change');
    delete frm.targets['.form-print button'];
    events.get('form-refresh')({}, frm);
    assert.equal(shortcuts.children[5].hidden, true, 'Print is hidden when the native action is unavailable');
    delete frm.targets['.share-label'];
    events.get('form-refresh')({}, frm);
    assert.equal(shortcuts.children[3].hidden, true, 'Missing native actions are hidden');
    assert.equal(JSON.stringify(frm.doc), original, 'Shortcuts must not change document data');
    const second = form('Sales Order'); events.get('form-refresh')({}, second);
    assert.equal(second.layout.classList.contains('qcmc-document-details-collapsed'), true, 'Preference follows the user across forms');
    second._qcmcDocumentDetailsToggle.button.fire('click');
    assert.equal(second.layout.classList.contains('qcmc-document-details-collapsed'), false);
    assert.equal(JSON.stringify(frm.doc), original, 'Toggling must not modify document data');
    second._qcmcDocumentDetailsToggle.button.fire('click');
    assert.equal(second.layout.classList.contains('qcmc-document-details-collapsed'), true);
    context.frappe.session.user = 'another@example.com';
    const another = form(); events.get('form-refresh')({}, another);
    assert.equal(another.layout.classList.contains('qcmc-document-details-collapsed'), false, 'Users have separate preferences');
    const unsaved = form('Stock Entry', true); events.get('form-refresh')({}, unsaved);
    assert.equal(unsaved._qcmcDocumentDetailsToggle.button.hidden, true, 'Do not offer an empty sidebar on new documents');
    unsaved.doc.__islocal = false; events.get('form-refresh')({}, unsaved);
    assert.equal(unsaved._qcmcDocumentDetailsToggle.button.hidden, false, 'The toggle becomes available after the first save');
    storageBlocked = true;
    another._qcmcDocumentDetailsToggle.button.fire('click'); events.get('form-refresh')({}, another);
    assert.equal(another.layout.classList.contains('qcmc-document-details-collapsed'), true, 'Blocked browser storage must not break toggling');
    const disabled = form(); disabled.sidebar.querySelector = () => null;
    events.get('form-refresh')({}, disabled);
    assert.equal(disabled._qcmcDocumentDetailsToggle.button.hidden, true, 'Respect Desk settings that disable the form sidebar');
    assert.equal(disabled.layout.classList.contains('qcmc-document-details-collapsed'), false);
    console.log('Document sidebar hide/show, persistence, refresh and document-safety checks passed');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
