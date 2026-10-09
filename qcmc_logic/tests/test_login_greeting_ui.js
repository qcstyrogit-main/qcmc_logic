const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(require("node:path").join(__dirname, "../public/js/login_notices.js"), "utf8");

async function main() {
    const dialogs = [], calls = [], messages = [];
    let ready, failSend = false, releaseSend;
    const button = {dataset: {greetKind: "birthdays", greetIndex: "0"}, addEventListener: (event, handler) => { button[event] = handler; }};
    const root = {querySelectorAll: selector => selector === "[data-greet-kind]" ? [button] : []};
    const payload = {month: 10, year: 2026, can_greet: true, announcements: [], anniversaries: [], birthdays: [{employee_name: "Birthday Person", department: "MIS", day: 31, user_id: "person@example.com"}]};
    const context = {
        document: {getElementById: () => null, querySelector: () => ({prepend() {}}), createElement: () => ({style: {}, setAttribute() {}, addEventListener() {}, appendChild() {}})},
        window: {localStorage: {getItem() {}, setItem() {}}},
        console: {warn() {}},
        $: () => ({on: (event, handler) => {ready = handler;}}),
        __: (text, args = []) => text.replace(/\{(\d+)\}/g, (_, i) => args[i]),
        frappe: {
            session: {user: "sender@example.com"}, boot: {qcmc_login_notice_session: "session"},
            utils: {escape_html: String}, msgprint: text => messages.push(text), show_alert() {},
            set_route: () => {throw Error("Greeting must not navigate to Tweet");},
            call: async options => {
                if (options.method.endsWith("get_login_notices")) return {message: payload};
                calls.push(options);
                if (options.method.endsWith("create_conversation")) return {message: "ROOM-1"};
                if (failSend) throw Error("Network error");
                if (releaseSend) await new Promise(resolve => {releaseSend = resolve;});
                return {message: {name: "MESSAGE-1"}};
            },
            ui: {Dialog: class {
                constructor(options) {
                    this.options = options; this.$wrapper = {addClass() {}};
                    this.fields_dict = {content: {$wrapper: {0: {querySelector: () => root}, html() {}}}};
                    this.primary = {prop: (key, value) => {this[key] = value; return this.primary;}, text: () => this.primary};
                    dialogs.push(this);
                }
                show() {this.visible = true;}
                hide() {this.visible = false; if (this.options.onhide) this.options.onhide();}
                get_primary_btn() {return this.primary;}
            }},
        },
    };
    vm.runInNewContext(source, context);
    await ready();
    await button.click();
    assert.equal(dialogs.length, 2);
    const composer = dialogs[1];
    const field = composer.options.fields.find(field => field.fieldname === "message");
    assert.equal(field.fieldtype, "Small Text");
    assert.match(field.default, /Birthday Person/);
    assert.match(field.default, /\n/);
    assert.equal(calls.length, 0, "Opening the composer must not create or send anything");
    composer.options.secondary_action();
    assert.equal(calls.length, 0, "Cancel must not send a message");
    await button.click();
    const sendDialog = dialogs[2];
    await sendDialog.options.primary_action({message: "   "});
    await sendDialog.options.primary_action({message: "x".repeat(10001)});
    assert.equal(calls.length, 0, "Invalid messages must not create a conversation");
    const multiline = "Happy birthday!\n\nHave a wonderful year.";
    failSend = true;
    await sendDialog.options.primary_action({message: multiline});
    assert.equal(sendDialog.visible, true, "Failed sending must keep the draft open");
    assert.equal(sendDialog.disabled, false);
    failSend = false;
    releaseSend = true;
    const sending = sendDialog.options.primary_action({message: multiline});
    await Promise.resolve();
    const callsWhileSending = calls.length;
    await sendDialog.options.primary_action({message: multiline});
    assert.equal(calls.length, callsWhileSending, "Double clicks must not send twice");
    releaseSend();
    await sending;
    assert.equal(sendDialog.visible, false);
    assert.equal(calls.filter(call => call.method.endsWith("create_conversation")).length, 1, "Retry must reuse the conversation");
    const sent = calls.filter(call => call.method.endsWith("send_message")).at(-1);
    assert.equal(sent.args.conversation, "ROOM-1");
    assert.equal(sent.args.content, multiline);
    assert.equal(calls[0].args.users[0], "person@example.com");
    assert.ok(messages.length >= 2);
    console.log("Greeting composer checks passed");
}
main().catch(error => {console.error(error); process.exitCode = 1;});
