const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Node {
    constructor() {this.children = []; this.dataset = {}; this.listeners = {}; this.nodes = {}; this.classes = new Set(); this.classList = {add: name => this.classes.add(name), remove: name => this.classes.delete(name)};}
    scrollIntoView(options) {this.scrolled = options;}
    focus() {this.focused = true;}
    querySelector(selector) {return this.nodes[selector] ||= new Node();}
    querySelectorAll() {return this.menus || [];}
    appendChild(node) {this.children.push(node); node.parentElement = this;}
    addEventListener(event, callback) {this.listeners[event] = callback;}
    removeEventListener(event, callback) {if (this.listeners[event] === callback) delete this.listeners[event];}
    setAttribute(key, value) {this[key] = value;}
    closest() {return this;}
    fire(action, index) {return this.listeners.click({target: {closest: () => ({dataset: {action, index: String(index)}})}});}
}
async function main() {
    const calls = [], dialogs = [], controls = [], copied = [], counts = [], realtime = new Map(), timers = new Map(); let timerId = 0, failPost = false;
    let rows = [
        {name: 'C-1', author: 'author@example.com', author_name: 'Author <script>', content: '<p>Original</p>', creation: '2026-10-15', modified: '2026-10-15', can_manage: true},
        {name: 'C-2', author: 'other@example.com', author_name: 'Other', content: '<p>Reply</p>', parent: 'C-1', creation: '2026-10-16', modified: '2026-10-16', can_manage: false},
    ];
    const context = {
        document: Object.assign(new Node(), {head: new Node(), createElement: () => new Node()}), console: {...console, warn() {}},
        setTimeout: callback => {timers.set(++timerId, callback); return timerId;},
        clearTimeout: id => timers.delete(id),
        __: (text, args = []) => text.replace(/\{(\d+)\}/g, (_, i) => args[i]),
        frappe: {
            session: {user: 'test@example.com'}, user_info: () => ({fullname: 'Test User'}),
            realtime: {on: (event, callback) => realtime.set(event, callback)},
            utils: {copy_to_clipboard: email => copied.push(email), html2text: value => value.replace(/<[^>]*>/g, ''), escape_html: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;')},
            call: async options => {
                calls.push(options);
                if (failPost && (options.method.endsWith('add_comment') || options.method.endsWith('update_comment'))) throw new Error('Network unavailable');
                if (options.method.endsWith('get_comments')) return {message: {comments: rows, count: rows.length}};
                if (options.method.endsWith('get_mention_profile')) return {message: {name: 'Person <script>', department: 'MIS', position: 'Developer', email: 'person@example.com'}};
                if (options.method.endsWith('delete_comment')) rows = rows.filter(row => row.name !== options.args.comment);
                return {message: {count: rows.length}};
            },
            confirm: (message, yes) => yes(),
            ui: {form: {make_control: options => {
                const control = {options, value: '', get_value() {return this.value;}, clear() {this.value = ''; this.quill.ops = [];},
                    set_formatted_input(value) {this.value = value; this.quill.ops = [];}, disable() {}, enable() {}, set_focus() {this.focused = true;},
                    quill: {root: new Node(), ops: [], on() {}, getSelection: () => null, getLength: () => 1,
                        getContents() {return {ops: this.ops};},
                        insertEmbed(index, type, data) {this.ops.unshift({insert: {[type]: data}});},
                        deleteText() {this.ops.shift();}, setSelection() {}, insertText() {}}};
                controls.push(control); return control;
            }}, Dialog: class {
                constructor(options) {this.options = options; this.$wrapper = {0: new Node(), addClass() {}}; this.disabled = false; dialogs.push(this);}
                get_primary_btn() {return {prop: (key, value) => {this.disabled = value;}};}
                show() {this.visible = true;}
                hide() {this.visible = false;}
            }},
        },
    };
    vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname, '../public/js/announcement_comments.js'), 'utf8'), context);
    const parent = new Node();
    const thread = context.frappe.qcmc_announcement_comments.attach({parent, announcement: 'ANN-1', targetComment: 'C-2', onCount: count => counts.push(count)});
    await thread.refresh();
    const host = parent.children[0];
    const target = host.querySelector('[data-comment-index="1"]');
    assert.equal(target.scrolled?.block, 'center', 'Notification scrolls to its exact comment');
    assert.equal(target.classes.has('qcmc-comment-highlight'), true, 'Mentioned comment receives a visible highlight');
    const firstMenu = {open: true}, secondMenu = {open: true};
    host.menus = [firstMenu, secondMenu];
    assert.equal(typeof context.document.listeners.click, 'function', 'Menus support outside-click dismissal');
    context.document.listeners.click({target: {closest: () => firstMenu}});
    assert.equal(firstMenu.open, true, 'Clicking within a menu keeps it open');
    assert.equal(secondMenu.open, false, 'Opening another menu closes the previous one');
    context.document.listeners.click({target: {closest: () => null}});
    assert.equal(firstMenu.open, false, 'Clicking elsewhere closes the menu');
    firstMenu.open = true;
    context.document.listeners.keydown({key: 'Escape'});
    assert.equal(firstMenu.open, false, 'Escape closes the menu');
    assert.match(host.innerHTML, /Author &lt;script>/, 'Author names must be escaped');
    assert.match(host.innerHTML, /data-action="reply"/);
    assert.equal((host.innerHTML.match(/data-action="edit"/g) || []).length, 1, 'Only manageable comments expose edit');
    assert.equal((host.innerHTML.match(/data-action="delete"/g) || []).length, 1);
    assert.ok(host.innerHTML.indexOf('Original') < host.innerHTML.indexOf('Reply</p>'));
    assert.equal(counts.at(-1), 2);
    host.fire('reply', 1);
    const composer = parent.children[1], control = controls[0];
    assert.equal(dialogs.length, 0, 'Reply uses the inline composer');
    assert.equal(control.options.df.fieldtype, 'Comment');
    assert.equal(control.options.enable_mentions, true, 'Use native @mention suggestions');
    assert.equal(control.focused, true);
    const mention = control.quill.ops[0].insert.mention;
    assert.equal(mention.id, 'other@example.com', 'Reply mentions the original author');
    assert.equal(mention.value, 'Other');
    assert.equal(mention.denotationChar, '', 'Auto mentions omit @');
    host.fire('reply', 1);
    assert.equal(control.quill.ops.length, 1, 'Repeated Reply does not duplicate mentions');
    control.value = '<p>Draft text</p>';
    host.fire('reply', 0);
    assert.equal(control.quill.ops.length, 1, 'Switching recipients replaces the automatic mention');
    assert.equal(control.quill.ops[0].insert.mention.value, 'Author &lt;script>', 'Escape names before passing them to native HTML mention blot');
    assert.equal(control.value, '<p>Draft text</p>');
    composer.fire('cancel-reply');
    assert.equal(control.quill.ops.length, 0, 'Cancel removes the automatic mention');
    assert.equal(control.value, '<p>Draft text</p>', 'Cancel preserves typed content');
    host.fire('reply', 1);
    control.value = '<p>Hello</p>';
    await composer.fire('post');
    const add = calls.find(call => call.method.endsWith('add_comment'));
    assert.equal(add.args.parent, 'C-2'); assert.equal(add.args.name, 'ANN-1');
    assert.equal(add.type, 'POST');
    assert.equal(control.value, '');
    let prevented = false, stopped = false;
    await host.listeners.click({target: {closest: selector => selector.startsWith('.mention') ? {dataset: {id: 'person@example.com'}} : null},
        preventDefault() {prevented = true;}, stopPropagation() {stopped = true;}});
    const profile = dialogs.at(-1);
    assert.equal(profile.options.title, 'Profile');
    assert.equal(profile.visible, true);
    assert.match(profile.options.fields[0].options, /data-copy-email/, 'Email exposes a copy action');
    profile.$wrapper[0].listeners.click({target: {closest: () => ({})}, preventDefault() {}});
    assert.equal(copied.at(-1), 'person@example.com', 'Copy uses the actual email');
    assert.equal(prevented && stopped, true, 'Mention click opens popup instead of following the native link');
    assert.match(profile.options.fields[0].options, /Person &lt;script>/, 'Profile HTML escapes values');
    for (const label of ['Name', 'Department', 'Position', 'Email']) assert.match(profile.options.fields[0].options, new RegExp(label));
    assert.equal(calls.find(call => call.method.endsWith('get_mention_profile')).args.user, 'person@example.com');
    control.value = '<p>Keep on failure</p>'; failPost = true;
    await composer.fire('post');
    assert.equal(control.value, '<p>Keep on failure</p>', 'Failed posts preserve the draft');
    failPost = false;
    control.value = '<p><br></p>';
    const beforeEmpty = calls.length; await composer.fire('post');
    assert.equal(calls.length, beforeEmpty, 'Empty comments are not submitted');
    control.value = '<p>My pending draft</p>';
    firstMenu.open = true;
    const beforeEditDialogs = dialogs.length;
    host.fire('edit', 0);
    assert.equal(firstMenu.open, false, 'Choosing an action closes its menu');
    assert.equal(dialogs.length, beforeEditDialogs, 'Editing does not open a popup');
    assert.equal(control.value, '<p>Original</p>', 'Existing content loads in the inline composer');
    control.value = '<p>Changed</p>';
    await thread.refresh();
    assert.equal(control.value, '<p>Changed</p>', 'Realtime refresh preserves the edit draft');
    failPost = true;
    await composer.fire('post');
    assert.equal(control.value, '<p>Changed</p>', 'Failed edits stay in the composer');
    failPost = false;
    await composer.fire('post');
    assert.equal(calls.find(call => call.method.endsWith('update_comment')).args.comment, 'C-1');
    assert.equal(control.value, '<p>My pending draft</p>', 'Saving restores the pending comment draft');
    host.fire('edit', 0);
    control.value = '<p>Cancelled change</p>';
    const beforeCancel = calls.length;
    composer.fire('cancel-reply');
    assert.equal(control.value, '<p>My pending draft</p>');
    assert.equal(calls.length, beforeCancel, 'Cancel edit makes no server change');
    host.fire('edit', 1);
    assert.equal(control.value, '<p>My pending draft</p>', 'Another author cannot edit the comment');
    await host.fire('delete', 0); await Promise.resolve(); await Promise.resolve();
    await thread.refresh();
    assert.equal(counts.at(-1), 1);
    assert.match(host.innerHTML, /Reply to a deleted comment/);
    assert.doesNotMatch(host.innerHTML, /data-action="refresh"/, 'Realtime discussion must not require a Refresh button');
    rows.push({name: 'C-3', author_name: 'Live author', content: '<p>Live update</p>', can_manage: false});
    const changed = realtime.get('qcmc_announcement_comments_changed');
    control.value = '<p>Unsent draft</p>';
    changed({announcement: 'OTHER'});
    assert.equal(timers.size, 0, 'Unrelated announcements do not trigger a reload');
    changed({announcement: 'ANN-1'}); changed({announcement: 'ANN-1'});
    assert.equal(timers.size, 1, 'Burst events are combined');
    const flush = async () => {const callbacks = [...timers.values()]; timers.clear(); callbacks.forEach(callback => callback()); await Promise.resolve(); await Promise.resolve();};
    await flush();
    assert.match(host.innerHTML, /Live update/);
    assert.equal(counts.at(-1), 2, 'Remote comments update the count');
    assert.equal(control.value, '<p>Unsent draft</p>', 'Realtime updates preserve the draft');
    assert.equal(controls.length, 1, 'The native editor is created once');
    host.fire('reply', 0); composer.fire('cancel-reply');
    assert.equal(control.value, '<p>Unsent draft</p>', 'Cancel reply preserves the draft');
    await composer.fire('post');
    assert.equal(calls.filter(call => call.method.endsWith('add_comment')).at(-1).args.parent, null);
    host.fire('sort');
    assert.match(host.innerHTML, /Oldest first/);
    rows[1].content = '<p>Live edit</p>'; changed({announcement: 'ANN-1'}); await flush();
    assert.match(host.innerHTML, /Live edit/);
    rows.pop(); changed({announcement: 'ANN-1'}); await flush();
    assert.doesNotMatch(host.innerHTML, /Live edit/);
    const beforeReconnect = calls.length; realtime.get('connect')(); await flush();
    assert.equal(calls.length, beforeReconnect + 1, 'Reconnect checks for missed changes');
    thread.destroy();
    assert.equal(context.document.listeners.click, undefined, 'Closing the discussion removes document listeners');
    changed({announcement: 'ANN-1'});
    assert.equal(timers.size, 0, 'Closed threads unsubscribe');
    const previous = counts.length; await thread.refresh();
    assert.equal(counts.length, previous, 'Closed dialogs must not receive stale updates');
    console.log('Announcement comment thread, composer, replies, ownership and counts checks passed');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
