frappe.pages["user-transaction-dashboard"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("User Transaction Dashboard"),
        single_column: true,
    });
    wrapper.transaction_dashboard = new UserTransactionDashboard(page);
};

frappe.pages["user-transaction-dashboard"].on_page_show = function (wrapper) {
    wrapper.transaction_dashboard.refresh();
};

class UserTransactionDashboard {
    constructor(page) {
        this.page = page;
        this.sequence = 0;
        this.ready = false;
        this.data = null;
        this.page.main.append(`
            <div class="user-transaction-dashboard" aria-busy="false">
                <div class="utd-filters"></div>
                <p class="text-muted utd-description"></p>
                <p class="utd-status text-muted" role="status" aria-live="polite"></p>
                <div class="utd-results"></div>
            </div>
        `);
        this.$root = this.page.main.find(".user-transaction-dashboard");
        this.$status = this.$root.find(".utd-status");
        this.$results = this.$root.find(".utd-results");
        this.$root.find(".utd-description").text(__(
            "Documents created by each user, including drafts, submitted and cancelled transactions. Dates use creation time."
        ));
        const make_filter = df => {
            const parent = $("<div class='utd-filter'></div>").appendTo(this.$root.find(".utd-filters"));
            const control = frappe.ui.form.make_control({parent, df, render_input: true});
            control.refresh();
            if (df.default) control.set_input(df.default);
            if (df.fieldtype === "MultiSelectList") {
                // Native status rendering falls back to a raw identifier as HTML
                // when a selected item is absent from the current search options.
                control.update_status = () => {
                    const values = control.get_value() || [];
                    let text = control.get_placeholder_text();
                    if (values.length === 1) {
                        const option = this.filter_options(df.fieldname).find(item => item.value === values[0]);
                        text = option ? option.label : frappe.utils.escape_html(String(values[0]));
                    } else if (values.length > 1) {
                        text = frappe.utils.escape_html(__("{0} values selected", [values.length]));
                    }
                    control.set_status(text);
                };
            }
            return control;
        };
        this.date_from = make_filter({
            fieldname: "date_from", label: __("Date From"), fieldtype: "Date", reqd: 1,
            default: frappe.datetime.month_start(), change: () => this.ready && this.refresh(),
        });
        this.date_to = make_filter({
            fieldname: "date_to", label: __("Date To"), fieldtype: "Date", reqd: 1,
            default: frappe.datetime.get_today(), change: () => this.ready && this.refresh(),
        });
        this.modules = make_filter({
            fieldname: "modules", label: __("Modules"), fieldtype: "MultiSelectList",
            placeholder: __("All modules"), get_data: txt => this.filter_options("modules", txt),
            change: () => this.ready && this.apply_filters(),
        });
        this.doctypes = make_filter({
            fieldname: "doctypes", label: __("Displayed DocTypes"), fieldtype: "MultiSelectList",
            placeholder: __("All DocTypes"), get_data: txt => this.filter_options("doctypes", txt),
            change: () => this.ready && this.apply_filters(),
        });
        this.users = make_filter({
            fieldname: "users", label: __("Displayed Users"), fieldtype: "MultiSelectList",
            placeholder: __("All users"), get_data: txt => this.filter_options("users", txt),
            change: () => this.ready && this.apply_filters(),
        });
        page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
        this.add_styles();
        this.ready = true;
    }

    filter_options(kind, query = "") {
        if (!this.data) return [];
        const escape = value => frappe.utils.escape_html(String(value ?? ""));
        let options;
        if (kind === "users") {
            options = this.data.rows.map(row => ({value: row.user, label: row.employee_name, description: row.user}));
        } else if (kind === "modules") {
            options = [...new Set(Object.values(this.data.doctype_modules || {}))].filter(Boolean).sort()
                .map(module => ({value: module, label: __(module)}));
        } else {
            const modules = this.modules.get_value() || [];
            options = this.data.doctypes.filter(dt => !modules.length || modules.includes(this.data.doctype_modules?.[dt]))
                .map(dt => ({value: dt, label: __(dt), description: this.data.doctype_modules?.[dt] || ""}));
        }
        const search = String(query || "").toLocaleLowerCase();
        return options.filter(option => `${option.label} ${option.value} ${option.description || ""}`.toLocaleLowerCase().includes(search))
            .map(option => ({...option, label: escape(option.label), description: escape(option.description)}));
    }

    filter_data() {
        const modules = this.modules?.get_value() || [];
        const selected_types = this.doctypes?.get_value() || [];
        const users = this.users?.get_value() || [];
        const doctypes = this.data.doctypes.filter(dt =>
            (!selected_types.length || selected_types.includes(dt)) &&
            (!modules.length || modules.includes(this.data.doctype_modules?.[dt])));
        const rows = this.data.rows.filter(row => !users.length || users.includes(row.user))
            .map(row => ({...row, total: doctypes.reduce((sum, dt) => sum + Number(row.counts[dt] || 0), 0)}));
        const counts = Object.fromEntries(doctypes.map(dt => [dt, rows.reduce((sum, row) => sum + Number(row.counts[dt] || 0), 0)]));
        const total = rows.reduce((sum, row) => sum + row.total, 0);
        return {doctypes, rows, totals: {counts, total}, summary: {
            documents: total, active_users: rows.filter(row => row.total > 0).length,
            active_doctypes: Object.values(counts).filter(value => value > 0).length,
        }};
    }

    apply_filters() {
        if (!this.data) return;
        const filtered = this.filter_data();
        this.render(filtered);
        this.$status.text(!this.data.rows.length ? __("No users to display.") :
            !filtered.rows.length ? __("No users match the current filters.") :
            !filtered.summary.documents ? __("No transactions match the current filters. Zero counts are shown below.") : "");
    }

    async refresh() {
        const sequence = ++this.sequence;
        const date_from = this.date_from.get_value();
        const date_to = this.date_to.get_value();
        this.data = null;
        this.$results.empty();
        this.$root.attr("aria-busy", "false");
        if (!date_from || !date_to) {
            this.$status.text(__("Select Date From and Date To."));
            return;
        }
        if (date_from > date_to) {
            this.$status.text(__("Date From must be on or before Date To."));
            return;
        }
        this.$root.attr("aria-busy", "true");
        this.$status.text(__("Loading transaction counts…"));
        try {
            const response = await frappe.call({
                method: "qcmc_logic.qcmc_logics.page.user_transaction_dashboard.user_transaction_dashboard.get_data",
                args: {date_from, date_to},
            });
            if (sequence !== this.sequence) return;
            const data = response.message;
            if (!data || !Array.isArray(data.rows)) throw new Error("Missing dashboard data");
            this.data = data;
            this.apply_filters();
        } catch (error) {
            if (sequence !== this.sequence) return;
            this.$results.empty();
            this.$status.text(__("Unable to load transaction counts. Check your connection and access, then select Refresh."));
        } finally {
            if (sequence === this.sequence) this.$root.attr("aria-busy", "false");
        }
    }

    render(data) {
        const escape = value => frappe.utils.escape_html(String(value ?? ""));
        const number = value => escape(Number(value || 0).toLocaleString());
        const cards = [
            [__("Total Documents"), data.summary.documents],
            [__("Users with Activity"), data.summary.active_users],
            [__("DocTypes with Activity"), data.summary.active_doctypes],
        ].map(([label, value]) => `
            <div class="utd-card">
                <div class="utd-card-label text-muted">${escape(label)}</div>
                <div class="utd-card-value">${number(value)}</div>
            </div>
        `).join("");
        let table = "";
        if (data.rows.length || this.data?.rows.length) {
            const headers = data.doctypes.map(dt => `<th scope="col" class="utd-number">${escape(__(dt))}</th>`).join("");
            const rows = data.rows.map(row => `
                <tr>
                    <th scope="row" class="utd-name">
                        <div>${escape(row.employee_name)}</div>
                        <div class="utd-user text-muted">${escape(row.user)}</div>
                    </th>
                    ${data.doctypes.map(dt => `<td class="utd-number${row.counts[dt] ? "" : " text-muted"}">${number(row.counts[dt])}</td>`).join("")}
                    <td class="utd-number utd-total">${number(row.total)}</td>
                </tr>
            `).join("") || `<tr><td colspan="${data.doctypes.length + 2}" class="text-muted">${escape(__("No users match the current filters."))}</td></tr>`;
            const footer = `<tr><th scope="row" class="utd-name">${escape(__("Total"))}</th>
                ${data.doctypes.map(dt => `<td class="utd-number">${number(data.totals.counts[dt])}</td>`).join("")}
                <td class="utd-number utd-total">${number(data.totals.total)}</td></tr>`;
            table = `
                <div class="utd-table-scroll" tabindex="0" role="region" aria-label="${escape(__("Transaction counts by user and DocType"))}">
                    <table class="table table-bordered utd-table">
                        <caption class="sr-only">${escape(__("Documents created by user and DocType in the selected date range"))}</caption>
                        <thead><tr><th scope="col" class="utd-name">${escape(__("Employee / User"))}</th>${headers}<th scope="col" class="utd-number utd-total">${escape(__("Total"))}</th></tr>
                        </thead>
                        <tbody>${rows}</tbody>
                        <tfoot>${footer}</tfoot>
                    </table>
                </div>
            `;
        }
        this.$results.html(`<div class="utd-cards">${cards}</div>${table}`);
    }

    add_styles() {
        if (document.getElementById("user-transaction-dashboard-style")) return;
        const style = document.createElement("style");
        style.id = "user-transaction-dashboard-style";
        style.textContent = `
            .user-transaction-dashboard { padding: 20px 0; }
            .user-transaction-dashboard .utd-filters { display: grid; grid-template-columns: repeat(2, minmax(140px, .8fr)) repeat(3, minmax(180px, 1.2fr)); gap: 16px; padding: 16px; margin-bottom: 16px; border: 1px solid var(--border-color, #d1d8dd); border-radius: var(--border-radius-md, 8px); background: var(--card-bg, #fff); }
            .user-transaction-dashboard .utd-filter .frappe-control { margin-bottom: 0; }
            .user-transaction-dashboard .utd-filter .dropdown-menu { min-width: 280px; max-width: 85vw; }
            .user-transaction-dashboard .utd-description { margin-bottom: 16px; }
            .user-transaction-dashboard .utd-status:empty { display: none; }
            .user-transaction-dashboard .utd-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-bottom: 24px; }
            .user-transaction-dashboard .utd-card { background: var(--card-bg, #fff); border: 1px solid var(--border-color, #d1d8dd); border-radius: var(--border-radius-md, 8px); padding: 20px; }
            .user-transaction-dashboard .utd-card-label { font-size: 13px; margin-bottom: 8px; }
            .user-transaction-dashboard .utd-card-value { font-size: 28px; font-weight: 600; color: var(--text-color); }
            .user-transaction-dashboard .utd-table-scroll { overflow: auto; max-height: 65vh; border: 1px solid var(--border-color, #d1d8dd); border-radius: var(--border-radius-md, 8px); }
            .user-transaction-dashboard .utd-table { margin: 0; border: 0; border-collapse: separate; border-spacing: 0; width: 100%; }
            .user-transaction-dashboard .utd-table th, .user-transaction-dashboard .utd-table td { padding: 12px 16px; border-width: 0 1px 1px 0; vertical-align: middle; background: var(--card-bg, #fff); }
            .user-transaction-dashboard .utd-table thead { position: sticky; top: 0; z-index: 2; }
            .user-transaction-dashboard .utd-table thead th { background: var(--subtle-fg, #f5f7fa); }
            .user-transaction-dashboard .utd-name { position: sticky; left: 0; z-index: 1; min-width: 240px; max-width: 300px; overflow-wrap: anywhere; }
            .user-transaction-dashboard .utd-table thead .utd-name { z-index: 3; }
            .user-transaction-dashboard .utd-user { font-size: 11px; font-weight: 400; margin-top: 4px; }
            .user-transaction-dashboard .utd-number { text-align: right; min-width: 130px; font-variant-numeric: tabular-nums; }
            .user-transaction-dashboard .utd-table thead .utd-number { max-width: 200px; }
            .user-transaction-dashboard .utd-total, .user-transaction-dashboard tfoot th, .user-transaction-dashboard tfoot td { font-weight: 600; background: var(--subtle-fg, #f5f7fa); }
            @media (max-width: 1100px) {
                .user-transaction-dashboard .utd-filters { grid-template-columns: repeat(3, minmax(0, 1fr)); }
            }
            @media (max-width: 767px) {
                .user-transaction-dashboard .utd-filters { grid-template-columns: 1fr; }
                .user-transaction-dashboard .utd-cards { grid-template-columns: 1fr; gap: 10px; }
                .user-transaction-dashboard .utd-card { padding: 14px; }
                .user-transaction-dashboard .utd-name { min-width: 170px; max-width: 200px; }
            }
        `;
        document.head.appendChild(style);
    }
}
