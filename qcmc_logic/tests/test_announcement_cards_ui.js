const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../public/js/login_notices.js'), 'utf8');

async function main() {
    const dialogs = [];
    let ready;
    const button = {dataset: {announcementIndex: '0'}, addEventListener(event, handler) {this[event] = handler;}, focus() {this.focused = true;}};
    const root = {querySelectorAll: selector => selector === '[data-announcement-index]' ? [button] : []};
    const text = 'A long announcement with several paragraphs. '.repeat(30);
    const row = {name: 'ANN-00001', title: 'News <special>', image: '/api/method/qcmc_logic.api.login_notices.get_announcement_image?name=ANN-00001', announcement: `<p><strong>${text}</strong></p>`};
    const context = {
        document: {getElementById() {}, querySelector: () => ({prepend() {}}), createElement: () => ({style: {}, setAttribute() {}, addEventListener() {}, appendChild() {}})},
        window: {localStorage: {getItem() {}, setItem() {}}}, console,
        $: () => ({on(event, handler) {ready = handler;}}),
        __: value => value,
        frappe: {
            session: {user: 'employee@example.com'}, boot: {qcmc_login_notice_session: 'test'},
            utils: {html2text: value => value.replace(/<[^>]*>/g, ''), escape_html: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;')},
            call: async () => ({message: {year: 2026, month: 10, announcements: [row], anniversaries: [], birthdays: []}}),
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
    assert.match(cards.html, /News &lt;special>/);
    assert.ok(!cards.html.includes(text), 'Long content must be shortened in the card');
    assert.ok(!cards.html.includes('<strong>A long announcement'), 'Card preview must contain plain text');
    assert.match(cards.html, /grid-template-columns:repeat\(3,minmax\(0,1fr\)\)/);
    assert.match(cards.html, /@media\(max-width:576px\).*grid-template-columns:minmax\(0,1fr\)/);
    button.click();
    const detail = dialogs[1];
    assert.equal(cards.visible, false);
    assert.equal(detail.visible, true);
    assert.ok(detail.html.includes(row.announcement), 'Read more must preserve complete formatted content');
    assert.ok(detail.html.includes(row.image), 'Read more must preserve the authenticated image URL');
    assert.equal(detail.options.title, 'News &lt;special>');
    detail.options.primary_action();
    assert.equal(detail.visible, false);
    assert.equal(cards.visible, true);
    assert.equal(button.focused, true, 'Return keyboard focus to the Read more button');
    console.log('Announcement card and full-detail checks passed');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
