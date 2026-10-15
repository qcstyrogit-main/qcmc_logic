const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../public/js/login_notices.js'), 'utf8');

async function main() {
    const dialogs = [];
    const viewCalls = [];
    const viewLabel = {}, commentLabel = {};
    let discussionOptions, destroyed = false;
    let countSubscription;
    let ready;
    const button = {dataset: {announcementIndex: '0'}, addEventListener(event, handler) {this[event] = handler;}, focus() {this.focused = true;}};
    const root = {querySelectorAll: selector => selector === '[data-announcement-index]' ? [button] : [], querySelector: selector => selector.includes('data-announcement-comments') ? commentLabel : viewLabel};
    const text = 'A long announcement with several paragraphs. '.repeat(30);
    const row = {name: 'ANN-00001', title: 'News <special>', image: '/api/method/qcmc_logic.api.login_notices.get_announcement_image?name=ANN-00001', announcement: `<p><strong>${text}</strong></p>`};
    const context = {
        document: {head: {appendChild() {}}, body: {appendChild() {}}, getElementById() {}, querySelector: () => ({prepend() {}}), createElement: () => ({style: {}, setAttribute() {}, addEventListener() {}, appendChild() {}})},
        window: {localStorage: {getItem() {}, setItem() {}}}, console,
        $: () => ({on(event, handler) {ready = handler;}}),
        __: (value, args = []) => value.replace(/\{(\d+)\}/g, (_, i) => args[i]),
        frappe: {
            qcmc_announcement_comments: {attach(options) {discussionOptions = options; return {destroy() {destroyed = true;}};}, subscribe(callback) {countSubscription = callback; return () => {}; }},
            session: {user: 'employee@example.com'}, boot: {qcmc_login_notice_session: 'test'},
            utils: {html2text: value => value.replace(/<[^>]*>/g, ''), escape_html: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;')},
            call: async options => {
                if (options.method.endsWith('get_comment_count')) return {message: {count: 4}};
                if (options.method.endsWith('record_announcement_view')) {
                    viewCalls.push(options);
                    return {message: {views: 1}};
                }
                return {message: {year: 2026, month: 10, announcements: [row], anniversaries: [], birthdays: []}};
            },
            ui: {Dialog: class {
                constructor(options) {
                    this.options = options;
                    this.$wrapper = {addClass() {}};
                    this.fields_dict = {};
                    for (const field of options.fields) {
                        this.fields_dict[field.fieldname] = {$wrapper: {0: {querySelector: () => root}, html: value => {this.html = value;}}};
                    }
                    dialogs.push(this);
                }
                show() {this.visible = true;}
                hide() {this.visible = false; this.options.onhide?.();}
            }},
        },
    };
    vm.runInNewContext(source, context);
    await ready();
    const cards = dialogs[0];
    assert.equal(cards.visible, true);
    assert.match(cards.html, /data-announcement-views="0"/);
    assert.match(cards.html, /0 views/);
    assert.match(cards.html, /data-announcement-comments="0"/);
    assert.match(cards.html, /0 comments/);
    assert.equal(viewCalls.length, 0, 'Showing preview cards must not count as a view');
    assert.match(cards.html, /News &lt;special>/);
    assert.ok(!cards.html.includes(text), 'Long content must be shortened in the card');
    assert.ok(!cards.html.includes('<strong>A long announcement'), 'Card preview must contain plain text');
    assert.match(cards.html, /grid-template-columns:repeat\(3,minmax\(0,1fr\)\)/);
    assert.match(cards.html, /@media\(max-width:576px\).*grid-template-columns:minmax\(0,1fr\)/);
    button.click();
    await Promise.resolve();
    const detail = dialogs[1];
    assert.equal(cards.visible, false);
    assert.equal(detail.visible, true);
    assert.ok(detail.html.includes(row.announcement), 'Read more must preserve complete formatted content');
    assert.ok(detail.html.includes(row.image), 'Read more must preserve the authenticated image URL');
    assert.equal(detail.options.title, 'News &lt;special>');
    assert.equal(viewLabel.textContent, '1 view');
    assert.equal(viewCalls[0].args.name, row.name);
    assert.equal(viewCalls[0].type, 'POST');
    assert.equal(discussionOptions.announcement, row.name);
    discussionOptions.onCount(3);
    assert.equal(commentLabel.textContent, '3 comments', 'Discussion changes update card counts');
    assert.equal(detail.options.primary_action, undefined, 'Details use the close icon without a redundant footer button');
    detail.hide();
    assert.equal(detail.visible, false);
    assert.equal(cards.visible, true);
    assert.equal(button.focused, true, 'Return keyboard focus to the Read more button');
    assert.equal(destroyed, true, 'Closing details stops discussion updates');
    countSubscription({announcement: row.name}); await Promise.resolve();
    assert.equal(commentLabel.textContent, '4 comments', 'Card counts update without opening the thread');
    button.click();
    await Promise.resolve();
    assert.equal(viewLabel.textContent, '1 view', 'Reopening uses the authoritative unique count');
    dialogs.at(-1).hide();
    await context.frappe.qcmc_login_notices.open(row.name, 'C-MENTION');
    const notificationDetail = dialogs.at(-1);
    assert.equal(discussionOptions.targetComment, 'C-MENTION', 'Notification target reaches the comment renderer');
    assert.equal(cards.visible, false, 'Notification opens only the detail popup');
    notificationDetail.hide();
    assert.equal(cards.visible, false, 'Closing notification detail does not reopen the cards');
    await context.frappe.qcmc_login_notices.open(row.name);
    assert.equal(dialogs.at(-1).visible, true, 'Notification can be opened repeatedly');
    dialogs.at(-1).hide();
    context.window.location = {search: '?qcmc_announcement=ANN-00001'};
    context.URLSearchParams = URLSearchParams;
    context.window.localStorage.getItem = () => 'test'; // Already seen this login.
    const previousDialogs = dialogs.length;
    vm.runInNewContext(source, context);
    await ready();
    assert.equal(dialogs.length, previousDialogs + 2, 'Mention link opens the requested announcement despite the once-per-login marker');
    assert.equal(dialogs.at(-1).visible, true);
    assert.equal(dialogs.at(-1).options.title, 'News &lt;special>');
    dialogs.at(-1).hide();
    assert.notEqual(dialogs.at(-2).visible, true, 'Deep links do not show a list underneath or after closing');
    console.log('Announcement card and full-detail checks passed');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
