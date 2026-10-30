const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function element() {
    return {value: "", attributes: {}, html(value) { this.value = value; return this; },
        text(value) { this.value = value; return this; }, empty() { this.value = ""; return this; },
        attr(key, value) { this.attributes[key] = value; return this; },
        find() { return element(); }};
}

async function main() {
    const requests = [];
    const context = {
        __: text => text,
        frappe: {
            pages: {"user-transaction-dashboard": {}},
            utils: {escape_html: value => String(value).replace(/[&<>"']/g,
                char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]))},
            call: options => new Promise((resolve, reject) => requests.push({options, resolve, reject})),
        },
    };
    const filename = path.join(__dirname, "../qcmc_logics/page/user_transaction_dashboard/user_transaction_dashboard.js");
    vm.runInNewContext(fs.readFileSync(filename, "utf8") + "\nglobalThis.Dashboard = UserTransactionDashboard;", context);

    // Exercise constructor wiring: date/selection controls must live inside the
    // displayed dashboard, and adding the dashboard must preserve Page's toolbar.
    const controls = [];
    const nodes = new Map();
    function dom(name) {
        if (nodes.has(name)) return nodes.get(name);
        const node = {...element(), name, append(html) { this.value += html; return this; },
            appendTo(parent) { this.parent = parent; return this; },
            find(selector) { return dom(`${name} ${selector}`); }, on() { return this; }};
        nodes.set(name, node);
        return node;
    }
    const mainNode = dom("main");
    mainNode.value = "<div class='page-form'>Native toolbar</div>";
    context.$ = () => dom(`control-parent-${controls.length}`);
    context.document = {getElementById: () => ({})};
    context.frappe.datetime = {month_start: () => "2026-10-01", get_today: () => "2026-10-30"};
    context.frappe.ui = {form: {make_control: ({parent, df}) => {
        controls.push({parent, df});
        let value = df.fieldtype === "MultiSelectList" ? [] : "";
        return {refresh() {}, get_value: () => value, set_input(input) { value = input; },
            get_placeholder_text: () => df.placeholder, set_status(text) { this.status = text; },
            update_status() { this.set_status(value[0] || df.placeholder); }};
    }}};
    const constructed = new context.Dashboard({main: mainNode, set_primary_action() {}});
    assert.match(mainNode.value, /Native toolbar/, "Dashboard construction preserves the connected native toolbar");
    assert.deepEqual(controls.map(control => control.df.label),
        ["Date From", "Date To", "Modules", "Displayed DocTypes", "Displayed Users", "Activity View"]);
    assert.ok(controls.every(control => control.parent.parent.name.endsWith(".utd-filters")),
        "Every filter is mounted in the visible dashboard filter container");
    assert.equal(constructed.date_from.get_value(), "2026-10-01");
    assert.equal(constructed.date_to.get_value(), "2026-10-30");
    assert.equal(constructed.activity_view.get_value(), "With Activity");
    assert.equal(requests.length, 1, "Current-month data starts loading automatically");
    assert.equal(requests[0].options.args.date_from, "2026-10-01");
    context.frappe.pages["user-transaction-dashboard"].on_page_show({transaction_dashboard: constructed});
    assert.equal(requests.length, 1, "Page-show does not duplicate initial load");
    requests.shift().resolve({message: {doctypes: [], rows: []}});
    await Promise.resolve();
    constructed.doctypes.set_input(['<img src=x onerror=alert(1)>']);
    constructed.doctypes.update_status();
    assert.equal(constructed.doctypes.status, '&lt;img src=x onerror=alert(1)&gt;',
        "A selected value absent from current options must never reach native status HTML unescaped");
    const dashboard = Object.create(context.Dashboard.prototype);
    dashboard.sequence = 0;
    dashboard.$results = element();
    dashboard.$status = element();
    dashboard.$root = element();
    let from = "2026-10-01", to = "2026-10-30";
    dashboard.date_from = {get_value: () => from};
    dashboard.date_to = {get_value: () => to};
    const data = {
        doctypes: ["Purchase Order", "<img src=x onerror=alert(1)>"],
        rows: [{user: "a@example.com", employee_name: "<script>bad()</script>",
            monitored: true, can_create: ["Purchase Order"],
            counts: {"Purchase Order": 56, "<img src=x onerror=alert(1)>": 30}, total: 86}],
        totals: {counts: {"Purchase Order": 56, "<img src=x onerror=alert(1)>": 30}, total: 86},
        summary: {documents: 86, active_users: 1, active_doctypes: 2},
    };
    dashboard.render(data);
    assert.ok(dashboard.$results.value.includes("&lt;script&gt;bad()&lt;/script&gt;"));
    assert.ok(dashboard.$results.value.includes("&lt;img src=x onerror=alert(1)&gt;"));
    assert.ok(!dashboard.$results.value.includes("<script>"));
    assert.match(dashboard.$results.value, /a@example.com/);
    assert.match(dashboard.$results.value, /<tfoot>[\s\S]*56[\s\S]*30[\s\S]*86/);
    assert.match(dashboard.$results.value, /scope="col"/);

    // Selection must change row/column visibility and all derived totals together.
    const scoped = {
        doctypes: ["Purchase Order", "Purchase Invoice"],
        doctype_modules: {"Purchase Order": "Buying", "Purchase Invoice": "Accounts"},
        rows: [
            {user: "alice@example.com", employee_name: "Alice", counts: {"Purchase Order": 56, "Purchase Invoice": 30}, total: 86},
            {user: "bob@example.com", employee_name: "Bob", counts: {"Purchase Order": 4, "Purchase Invoice": 2}, total: 6},
            {user: "zero@example.com", employee_name: "Zero", counts: {"Purchase Order": 0, "Purchase Invoice": 0}, total: 0},
        ],
    };
    for (const row of scoped.rows) {
        row.monitored = true;
        row.can_create = ["Purchase Order", "Purchase Invoice"];
    }
    dashboard.data = scoped;
    let selectedUsers = ["alice@example.com"], selectedTypes = ["Purchase Order"], selectedModules = [];
    dashboard.users = {get_value: () => selectedUsers};
    dashboard.doctypes = {get_value: () => selectedTypes};
    dashboard.modules = {get_value: () => selectedModules};
    let filtered = dashboard.filter_data();
    assert.equal(filtered.rows.length, 1);
    assert.equal(filtered.rows[0].total, 56);
    assert.equal(filtered.totals.total, 56);
    assert.equal(filtered.summary.documents, 56);
    assert.equal(filtered.summary.active_doctypes, 1);
    assert.equal(scoped.rows[0].total, 86, "Filtering never modifies fetched totals");
    selectedUsers = []; selectedTypes = []; selectedModules = ["Accounts"];
    filtered = dashboard.filter_data();
    assert.equal(JSON.stringify(filtered.doctypes), '["Purchase Invoice"]');
    assert.equal(filtered.totals.total, 32);
    const usage = {
        doctypes: ["Purchase Order", "Purchase Invoice"],
        doctype_modules: scoped.doctype_modules,
        rows: [
            {user: "alice", employee_name: "Alice", monitored: true, can_create: ["Purchase Order", "Purchase Invoice"], counts: {"Purchase Order": 3, "Purchase Invoice": 0}},
            {user: "bob", employee_name: "Bob", monitored: true, can_create: ["Purchase Order"], counts: {}},
            {user: "charlie", employee_name: "Charlie", monitored: true, can_create: ["Purchase Invoice"], counts: {}},
            {user: "reader", employee_name: "Reader", monitored: true, can_create: [], counts: {}},
            {user: "disabled", employee_name: "Disabled", monitored: false, can_create: [], counts: {"Purchase Order": 2}},
        ],
    };
    dashboard.data = usage;
    selectedModules = [];
    let view = "With Activity";
    dashboard.activity_view = {get_value: () => view};
    filtered = dashboard.filter_data();
    assert.equal(filtered.rows.length, 2, "Default view keeps activity, including retained historical counts");
    assert.equal(JSON.stringify(filtered.doctypes), '["Purchase Order"]');
    assert.equal(filtered.summary.using, 1);
    assert.equal(filtered.summary.not_using, 2, "Hidden zero-only DocTypes remain part of the eligible population");
    assert.equal(filtered.summary.usage_rate, 33.3);
    assert.equal(filtered.summary.documents, 5);
    dashboard.render(filtered);
    assert.match(dashboard.$results.value, /Historical count; no current Create permission/);
    const savedUsage = dashboard.data;
    dashboard.data = {...usage, rows: usage.rows.map(row => ({...row, counts: {}}))};
    const emptyPeriod = dashboard.filter_data();
    assert.equal(emptyPeriod.rows.length, 0);
    assert.equal(emptyPeriod.doctypes.length, 0);
    assert.equal(emptyPeriod.summary.not_using, 3);
    assert.equal(emptyPeriod.summary.usage_rate, 0);
    dashboard.data = savedUsage;
    view = "Without Activity";
    filtered = dashboard.filter_data();
    assert.equal(filtered.rows.length, 2);
    assert.equal(filtered.summary.using, 1, "Activity View does not change scope cards");
    assert.equal(filtered.totals.total, 0);
    dashboard.render(filtered);
    assert.match(dashboard.$results.value, /No current Create permission/);
    assert.match(dashboard.$results.value, /—/);
    assert.match(dashboard.$results.value, />0<\/td>/, "Create access without activity renders zero");
    view = "All";
    assert.equal(dashboard.filter_data().rows.length, 4, "Read-only users with no transactions are not labeled Not Using");
    selectedTypes = ["Purchase Order"];
    filtered = dashboard.filter_data();
    assert.equal(filtered.summary.not_using, 1);
    assert.equal(filtered.summary.usage_rate, 50);
    view = "Without Activity";
    assert.equal(dashboard.filter_data().rows.length, 1);
    selectedUsers = ["alice"];
    view = "All";
    assert.equal(dashboard.filter_data().summary.usage_rate, 100);
    dashboard.data = {...usage, rows: []};
    assert.equal(dashboard.filter_data().summary.usage_rate, null, "No eligible users has no percentage denominator");
    dashboard.data = scoped;
    view = "With Activity";
    selectedModules = [];
    selectedUsers = []; selectedTypes = [];
    const userOptions = dashboard.filter_options("users", "ALICE");
    assert.equal(userOptions.length, 1);
    assert.equal(userOptions[0].value, "alice@example.com");
    dashboard.data = data;
    assert.ok(dashboard.filter_options("users")[0].label.startsWith("&lt;script&gt;"),
        "Native dropdown labels are escaped before its HTML renderer consumes them");
    dashboard.data = null;

    const first = dashboard.refresh();
    assert.equal(dashboard.$results.value, "", "Loading clears old counts");
    assert.equal(requests[0].options.args.date_to, "2026-10-30");
    to = "2026-10-31";
    const second = dashboard.refresh();
    requests[1].resolve({message: data});
    await second;
    const latest = dashboard.$results.value;
    requests[0].resolve({message: {...data, rows: []}});
    await first;
    assert.equal(dashboard.$results.value, latest, "Old success cannot overwrite new filters");

    const oldError = dashboard.refresh();
    const newSuccess = dashboard.refresh();
    requests[3].resolve({message: data});
    await newSuccess;
    requests[2].reject(new Error("old request failed"));
    await oldError;
    assert.equal(dashboard.$results.value, latest, "Old errors cannot clear a new result");

    const pending = dashboard.refresh();
    from = "2026-11-01";
    await dashboard.refresh();
    assert.match(dashboard.$status.value, /on or before/);
    requests[4].resolve({message: data});
    await pending;
    assert.equal(dashboard.$results.value, "", "Invalid filters invalidate pending data");
    from = "";
    await dashboard.refresh();
    assert.match(dashboard.$status.value, /Select/);
    assert.equal(requests.length, 5, "Invalid ranges do not call the server");

    from = "2026-10-01";
    const failed = dashboard.refresh();
    requests[5].reject(new Error("offline"));
    await failed;
    assert.match(dashboard.$status.value, /Unable/);
    assert.equal(dashboard.$results.value, "");
    assert.equal(dashboard.$root.attributes["aria-busy"], "false");

    const empty = dashboard.refresh();
    requests[6].resolve({message: {doctypes: [], rows: [], totals: {counts: {}, total: 0},
        summary: {documents: 0, active_users: 0, active_doctypes: 0}}});
    await empty;
    assert.match(dashboard.$status.value, /No users/);
    assert.ok(!dashboard.$results.value.includes("<table"));
    console.log("PASS: automatic current-month load, permission-aware activity views and scope cards, zero versus no access, historical counts, searched selectors, escaped rendering, stale responses and empty states");
}

main().catch(error => { console.error(error); process.exitCode = 1; });
