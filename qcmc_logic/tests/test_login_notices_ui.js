const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const sourcePath = require("node:path").join(__dirname, "../public/js/login_notices.js");

async function main() {
    assert.ok(fs.existsSync(sourcePath), "Login notice popup is not implemented");
    const source = fs.readFileSync(sourcePath, "utf8");
    const storage = new Map();
    const dialogs = [];
    let requests = 0;
    let failRequest = false;
    let lockTail = Promise.resolve();
    let insideLock = false;
    const payload = {
        month: 10, year: 2026,
        announcements: [
            {announcement: "<p>Company news</p>", image: "javascript:alert(1)"},
            {announcement: "<p>Private image</p>", image: "/api/method/qcmc_logic.api.login_notices.get_announcement_image?name=ANN-00001"},
        ],
        birthdays: [{employee_name: '<img src=x onerror="alert(1)">', department: "MIS", day: 31}],
        anniversaries: [{employee_name: "Veteran", department: "MIS", day: 31, years: 6}],
    };
    async function load(session, user = "Administrator", useLocks = true) {
        let ready;
        const context = {
            document: {
                getElementById: () => null,
                querySelector: () => ({prepend() {}}),
                createElement: () => ({style: {}, setAttribute() {}, addEventListener() {}, appendChild() {}}),
            }, console: {warn() {}}, URL,
            navigator: {locks: {request: (key, callback) => {
                const next = lockTail.then(async () => {
                    insideLock = true;
                    try { return await callback(); } finally { insideLock = false; }
                });
                lockTail = next.catch(() => {});
                return next;
            }}},
            window: {localStorage: {getItem: key => storage.get(key), setItem: (key, val) => storage.set(key, val)}},
            $: () => ({on: (event, handler) => { ready = handler; }}),
            __: (value, args = []) => value.replace(/\{(\d+)\}/g, (_, i) => args[i]),
            frappe: {
                session: {user}, boot: {qcmc_login_notice_session: session},
                utils: {html2text: value => value.replace(/<[^>]*>/g, ""), escape_html: value => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;")},
                call: async () => { requests++; if (failRequest) throw Error("offline"); return {message: payload}; },
                ui: {Dialog: class {
                    constructor(options) {
                        this.options = options;
                        this.$wrapper = {addClass() {}};
                        this.fields_dict = {};
                        this.contents = {};
                        for (const field of options.fields.filter(field => field.fieldtype === "HTML")) {
                            this.fields_dict[field.fieldname] = {$wrapper: {0: {querySelector: () => ({querySelectorAll: () => []})}, html: html => {
                                this.contents[field.fieldname] = html;
                                this.html = Object.values(this.contents).join("");
                            }}};
                        }
                    }
                    show() { assert.ok(!useLocks || insideLock, "Showing the popup must hold the cross-tab lock"); dialogs.push(this); }
                    hide() { this.hidden = true; }
                }},
            },
        };
        if (!useLocks) delete context.navigator;
        vm.runInNewContext(source, context);
        await ready();
        return context;
    }
    await load("session-1");
    assert.equal(dialogs.length, 1);
    assert.match(dialogs[0].html, /Company news/);
    assert.match(dialogs[0].html, /&lt;img/);
    assert.doesNotMatch(dialogs[0].html, /javascript:/);
    assert.match(dialogs[0].html, /<img src="\/api\/method\/qcmc_logic.api.login_notices.get_announcement_image\?name=ANN-00001"/);
    assert.match(dialogs[0].html, /6 years/);
    assert.match(dialogs[0].html, /qcmc-announcement-grid/);
    assert.match(dialogs[0].html, /data-announcement-index="0"/);
    assert.match(dialogs[0].html, /Read more/);
    dialogs[0].options.primary_action();
    assert.equal(dialogs[0].hidden, true);
    await load("session-1");
    assert.equal(dialogs.length, 1, "Refreshing must not reopen the popup");
    assert.equal(requests, 1, "Refreshing must not fetch notice data again");
    await load("session-2");
    assert.equal(dialogs.length, 2, "A fresh login must show the popup");
    await load("guest", "Guest");
    assert.equal(dialogs.length, 2);
    failRequest = true;
    await load("session-3");
    assert.equal(dialogs.length, 2);
    failRequest = false;
    payload.announcements = []; payload.birthdays = []; payload.anniversaries = [];
    await load("session-3");
    assert.equal(dialogs.length, 3, "A failed request must allow a retry");
    assert.match(dialogs[2].html, /No announcements/);
    assert.match(dialogs[2].html, /No birthdays/);
    assert.match(dialogs[2].html, /No work anniversaries/);
    await Promise.all([load("session-4"), load("session-4")]);
    assert.equal(dialogs.length, 4, "Concurrent tabs must show only one popup for the login");
    await load("session-5", "Administrator", false);
    const refreshed = await load("session-5", "Administrator", false);
    assert.equal(dialogs.length, 5, "Browsers without Web Locks must still support the popup and refresh suppression");
    const requestsBeforeReopen = requests;
    await refreshed.frappe.qcmc_login_notices.open();
    assert.equal(dialogs.length, 6, "Manual reopening must work after the session popup was already seen");
    assert.equal(requests, requestsBeforeReopen + 1);
    dialogs[5].hide();
    await refreshed.frappe.qcmc_login_notices.open();
    assert.equal(dialogs[6], dialogs[5], "Reopening reuses the existing dialog");
    assert.equal(requests, requestsBeforeReopen + 1, "Reopening an existing dialog must not fetch it again");
    console.log("Login notice UI tests passed");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
