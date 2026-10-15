const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Node {
    constructor() {this.children = []; this.dataset = {}; this.classList = {add() {}, remove() {}};}
    appendChild(child) {this.children.push(child);}
    querySelector() {return this.children[0] || null;}
    setAttribute(key, value) {this[key] = value;}
}
async function main() {
    const events = {}, realtime = {}, calls = [], opened = [], icon = new Node();
    let navbarHidden = false, rendered = 0;
    let count = 4, focusedComment = null, notificationRows = [{name: 'N-1'}];
    const context = {URL, console, setTimeout: callback => callback(), setInterval: callback => {events.poll = callback;},
        __: (text, args = []) => text.replace(/\{(\d+)\}/g, (_, i) => args[i]),
        document: {head: new Node(), body: new Node(), createElement: () => new Node(), querySelectorAll: selector => selector.includes('.sidebar-notification') ? [icon] : [],
            addEventListener: (name, callback) => {events[name] = callback;}},
        window: {location: {origin: 'https://erp.example'}, addEventListener() {}},
        MutationObserver: class {observe() {}},
        $: () => ({on: (name, callback) => {events[name] = callback;}, closest: selector => ({length: 1, closest: () => ({length: 1}), addClass(name) {if (name === 'hidden') navbarHidden = true;}, removeClass() {}, dropdown() {}}), trigger() {}}),
        frappe: {app: {sidebar: {notifications: {tabs: {notifications: {render_notifications_dropdown() {rendered++;}}}}}}, update_user_info() {}, boot: {}, session: {user: 'test@example.com'}, after_ajax: callback => callback(),
            realtime: {on: (name, callback) => {realtime[name] = callback;}},
            qcmc_login_notices: {open: (name, comment) => {opened.push(name); focusedComment = comment;}},
            call: async options => {calls.push(options); return {message: options.method.endsWith('get_unread_count') ? count : options.method.endsWith('get_notification_logs') ? {notification_logs: notificationRows, user_info: {}} : {announcement: 'ANN-1', comment: 'C-MENTION'}};}}
    };
    vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname, '../public/js/desk_notifications.js'), 'utf8'), context);
    await events.app_ready();
    assert.equal(icon.children[0].textContent, '4');
    await realtime.connect();
    assert.ok(rendered > 0, 'The native notification list also refreshes');
    count = 105; notificationRows = [{name: 'N-2'}]; await realtime.notification();
    assert.equal(icon.children[0].textContent, '99+');
    assert.equal(context.frappe.app.sidebar.notifications.tabs.notifications.dropdown_items[0].name, 'N-2', 'Realtime refreshes the list as well as its badge');
    count = 0; await realtime.connect();
    assert.equal(icon.children[0].hidden, true);
    count = 3; notificationRows = [{name: 'N-3'}]; await events.poll();
    assert.equal(icon.children[0].textContent, '3', 'Recovery check updates counts without a page refresh');
    assert.equal(context.frappe.app.sidebar.notifications.tabs.notifications.dropdown_items[0].name, 'N-3');
    let prevented = false;
    const item = {dataset: {name: 'N-1'}, getAttribute: () => '/desk?qcmc_announcement=ANN-1', classList: {remove() {}}};
    await events.click({target: {closest: selector => selector.startsWith('a.') ? item : null}, preventDefault() {prevented = true;}, stopImmediatePropagation() {}});
    assert.equal(prevented, true);
    assert.deepEqual(opened, ['ANN-1']);
    assert.equal(focusedComment, 'C-MENTION', 'Notification opens the specific mentioned comment');
    assert.equal(navbarHidden, false, 'Closing the menu never hides the navbar bell');
    const openCall = calls.find(call => call.method.endsWith('open_announcement_notification'));
    assert.equal(openCall.type, 'POST'); assert.equal(openCall.args.notification, 'N-1');
    item.getAttribute = () => '/desk/email-queue/QUEUE-1';
    await events.click({target: {closest: selector => selector.startsWith('a.') ? item : null}, preventDefault() {}, stopImmediatePropagation() {}});
    assert.equal(opened.length, 2, 'Old email-queue links also open the announcement popup');
    item.getAttribute = () => '/desk/quiz/Q-1'; prevented = false;
    await events.click({target: {closest: selector => selector.startsWith('a.') ? item : null}, preventDefault() {prevented = true;}});
    assert.equal(prevented, false, 'Unrelated notifications retain native behavior');
    console.log('Notification popup links, unread badge, realtime and isolation checks passed');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
