frappe.pages["user-transaction-dashboard"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("User Transaction Dashboard"),
        single_column: true,
    });
    wrapper.transaction_dashboard = new UserTransactionDashboard(page);
};

frappe.pages["user-transaction-dashboard"].on_page_show = function (wrapper) {
    const dashboard = wrapper.transaction_dashboard;
    if (!dashboard.data && !dashboard.loading) dashboard.refresh();
};

class UserTransactionDashboard {
    constructor(page) {
        this.page = page;
        this.sequence = 0;
        this.ready = false;
        this.data = null;
        this.loading = false;
        this.page.main.append(`
            <div class="user-transaction-dashboard" aria-busy="false">
                <div class="utd-report-heading"><div><div class="utd-eyebrow">MANAGEMENT INTELLIGENCE / ERP ACTIVITY</div><h2>Transaction Activity &amp; Adoption</h2><p>Understand who is using transaction workflows, where activity is concentrated, and where follow-up may be needed.</p></div><div class="utd-report-tag">INTERNAL MANAGEMENT REPORT</div></div><div class="utd-filters"></div>
                <p class="text-muted utd-description"></p>
                <p class="utd-status text-muted" role="status" aria-live="polite"></p>
                <div class="utd-scope-host"></div><div class="utd-cards-host"></div><div class="utd-insights-host"></div>
                <div class="utd-chart-host"></div>
                <div class="utd-results"></div>
                <div class="utd-print-report" aria-hidden="true"></div>
            </div>
        `);
        this.$root = this.page.main.find(".user-transaction-dashboard");
        this.$status = this.$root.find(".utd-status");
        this.$results = this.$root.find(".utd-results");
        this.$root.find(".utd-description").text(__(
            "Monitor documents created against current Create permissions. Includes drafts, submitted and cancelled transactions."
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
        this.activity_view = make_filter({
            fieldname: "activity_view", label: __("Activity View"), fieldtype: "Select",
            options: "With Activity\nWithout Activity\nAll", default: "With Activity",
            change: () => this.ready && this.apply_filters(),
        });
        page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
        page.add_menu_item?.(__("Export displayed table (CSV)"), () => this.export_csv());
        page.add_menu_item?.(__("Print management report"), () => this.print_report());
        page.add_inner_button?.(__("Print Report"), () => this.print_report());
        this.add_styles();
        this.ready = true;
        this.setup_management_charts();
        this.refresh();
    }

    async setup_management_charts() {
        try {
            await frappe.require("/assets/qcmc_logic/js/user_transaction_charts.js");
            this.chart_builder = new frappe.UserTransactionCharts(this);
            if (this.data) this.chart_builder.update(this.chart_scope(this.filter_data()));
        } catch (error) {
            this.$root.find(".utd-chart-host").text(__("Management charts could not be loaded. Reload the page to retry."));
        }
    }

    chart_scope(filtered) {
        return {
            date_from:this.date_from.get_value(), date_to:this.date_to.get_value(),
            doctypes:filtered.scope_doctypes, rows:filtered.scope_rows,
            modules:this.data.doctype_modules || {}, summary:filtered.summary, data_version:this.sequence,
            selections:{modules:[...(this.modules?.get_value() || [])],
                doctypes:[...(this.doctypes?.get_value() || [])],users:[...(this.users?.get_value() || [])]},
        };
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
        const scope_types = this.data.doctypes.filter(dt =>
            (!selected_types.length || selected_types.includes(dt)) &&
            (!modules.length || modules.includes(this.data.doctype_modules?.[dt])));
        // Determine eligibility over the full selected scope before hiding empty
        // columns or inactive rows. Otherwise the default view inflates usage.
        const scope_rows = this.data.rows.filter(row => !users.length || users.includes(row.user))
            .map(row => {
                const total = scope_types.reduce((sum, dt) => sum + Number(row.counts[dt] || 0), 0);
                const eligible = Boolean(row.monitored && scope_types.some(dt => (row.can_create || []).includes(dt)));
                return {...row, total, eligible,
                    usage_status: !eligible ? "Historical activity" : total > 0 ? "Using" : "Not Using"};
            }).filter(row => row.eligible || row.total > 0);
        const eligible_users = scope_rows.filter(row => row.eligible).length;
        const using = scope_rows.filter(row => row.eligible && row.total > 0).length;
        const view = this.activity_view?.get_value() || "With Activity";
        const rows = scope_rows.filter(row => view === "All" ||
            (view === "Without Activity" ? row.eligible && row.total === 0 : row.total > 0));
        const scope_counts = Object.fromEntries(scope_types.map(dt => [dt,
            scope_rows.reduce((sum, row) => sum + Number(row.counts[dt] || 0), 0)]));
        const doctypes = scope_types.filter(dt => {
            if (view === "With Activity" && !selected_types.length) return scope_counts[dt] > 0;
            return selected_types.length || scope_counts[dt] > 0 || scope_rows.some(row => row.eligible && row.can_create.includes(dt));
        });
        const counts = Object.fromEntries(doctypes.map(dt => [dt, rows.reduce((sum, row) => sum + Number(row.counts[dt] || 0), 0)]));
        const total = rows.reduce((sum, row) => sum + row.total, 0);
        return {doctypes, rows, totals: {counts, total}, summary: {
            documents: scope_rows.reduce((sum, row) => sum + row.total, 0),
            using, not_using: eligible_users - using, eligible_users,
            usage_rate: eligible_users ? Math.round(using / eligible_users * 1000) / 10 : null,
            active_users: scope_rows.filter(row => row.total > 0).length,
            active_doctypes: Object.values(scope_counts).filter(value => value > 0).length,
            historical_users: scope_rows.filter(row => !row.eligible && row.total > 0).length,
        }, view, scope_users: scope_rows.length, scope_rows, scope_doctypes:scope_types};
    }

    apply_filters() {
        if (!this.data) return;
        const filtered = this.filter_data();
        this.render(filtered);
        this.chart_builder?.update(this.chart_scope(filtered));
        this.render_print_report(filtered);
        this.$status.text(!this.data.rows.length ? __("No users to display.") :
            !filtered.rows.length ? (filtered.view === "With Activity" ?
                __("No documents were created in this scope and date range. Select Without Activity or All to see eligible users.") :
                __("No users match this Activity View. Try All or adjust your filters.")) :
            !filtered.summary.documents ? __("No transactions match the current filters. Zero counts are shown below.") : "");
    }

    async refresh() {
        const sequence = ++this.sequence;
        const date_from = this.date_from.get_value();
        const date_to = this.date_to.get_value();
        this.data = null;
        this.loading = false;
        this.chart_builder?.clear();
        this.$root.find(".utd-cards-host").empty();
        this.$root.find(".utd-scope-host").empty();
        this.$root.find(".utd-insights-host").empty();
        this.$root.find(".utd-print-report").empty();
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
        this.loading = true;
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
            if (sequence === this.sequence) {
                this.loading = false;
                this.$root.attr("aria-busy", "false");
            }
        }
    }

    print_report() {
        if (!this.data || this.loading) {
            frappe.msgprint?.(__("Load the dashboard before printing the management report."));
            return;
        }
        this.render_print_report(this.filter_data());
        window.print();
    }

    render_print_report(data) {
        const escape = value => frappe.utils.escape_html(String(value ?? ""));
        const number = value => escape(Number(value || 0).toLocaleString());
        const date_from = this.date_from.get_value();
        const date_to = this.date_to.get_value();
        const eligible = Number(data.summary.using || 0) + Number(data.summary.not_using || 0);
        const by_count = [...(data.scope_rows || data.rows)].filter(row => row.total > 0)
            .sort((a, b) => b.total - a.total || String(a.employee_name).localeCompare(String(b.employee_name)));
        const doc_counts = (data.scope_doctypes || data.doctypes).map(dt => ({
            name: dt, count: (data.scope_rows || data.rows).reduce((sum, row) => sum + Number(row.counts?.[dt] || 0), 0),
        })).filter(entry => entry.count).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
        const top_types = doc_counts.slice(0, 12);
        const top_users = by_count.slice(0, 15);
        const using = number(data.summary.using);
        const not_using = number(data.summary.not_using);
        const rate = data.summary.usage_rate == null ? "N/A" : `${number(data.summary.usage_rate)}%`;
        const tables = (items, label, make_name) => items.length ? items.map((item, i) =>
            `<tr><td class="utd-print-rank">${i + 1}</td><td>${escape(make_name(item))}</td><td class="utd-print-numeric">${number(item.count ?? item.total)}</td></tr>`).join("") :
            `<tr><td colspan="3">${escape(__("No recorded activity in this period."))}</td></tr>`;
        const selected = [
            ["Modules", this.modules?.get_value() || []],
            ["DocTypes", this.doctypes?.get_value() || []],
            ["Users", this.users?.get_value() || []],
        ].filter(([, values]) => values.length).map(([name, values]) => `${name}: ${values.join(", ")}`);
        const view = this.activity_view?.get_value() || "With Activity";
        const full_matrix = data.doctypes.length <= 6;
        const matrix = full_matrix && data.rows.length ? `<table class="utd-print-matrix"><thead><tr><th>${escape(__("Employee / User"))}</th>${data.doctypes.map(dt => `<th>${escape(dt)}</th>`).join("")}<th>${escape(__("Total"))}</th></tr></thead><tbody>${data.rows.map(row =>
            `<tr><td>${escape(row.employee_name)}<small>${escape(row.user)}</small></td>${data.doctypes.map(dt => `<td class="utd-print-numeric">${number(row.counts?.[dt])}</td>`).join("")}<td class="utd-print-numeric">${number(row.total)}</td></tr>`).join("")}</tbody></table>` :
            `<p class="utd-print-note">${escape(__("Detailed transaction matrix is available on screen and through Export displayed table (CSV). Select up to six DocTypes to include a detailed matrix in the printout."))}</p>`;
        const html = `<header class="utd-print-header"><div><p class="utd-print-kicker">QCMC · ERP MANAGEMENT REPORT</p><h1>${escape(__("User Transaction Activity & Adoption"))}</h1><p>${escape(__("Administrative report of ERPNext document creation and current user eligibility"))}</p></div><span>${escape(__("INTERNAL · MANAGEMENT"))}</span></header>
            <div class="utd-print-meta"><div><strong>${escape(__("Reporting period"))}</strong><span>${escape(date_from)} — ${escape(date_to)}</span></div><div><strong>${escape(__("Activity view"))}</strong><span>${escape(view)}</span></div><div><strong>${escape(__("Eligible users"))}</strong><span>${number(eligible)}</span></div><div><strong>${escape(__("Transaction types"))}</strong><span>${number((data.scope_doctypes || data.doctypes).length)}</span></div></div>
            ${selected.length ? `<p class="utd-print-selection">${escape(selected.join(" · "))}</p>` : ""}
            <h2>${escape(__("Executive overview"))}</h2><div class="utd-print-kpis"><div><strong>${using}</strong><span>${escape(__("Using"))}</span></div><div><strong>${not_using}</strong><span>${escape(__("Not Using"))}</span></div><div><strong>${rate}</strong><span>${escape(__("Adoption Rate"))}</span></div><div><strong>${number(data.summary.documents)}</strong><span>${escape(__("Documents Created"))}</span></div></div>
            <p class="utd-print-analysis">${escape(eligible ? `${data.summary.using} of ${eligible} currently eligible users created a document during the selected period.` : "No currently eligible users in the selected scope.")} ${escape(by_count.length ? `Highest recorded creation volume: ${by_count[0].employee_name} (${Number(by_count[0].total).toLocaleString()} documents).` : "No document creation activity recorded.")}</p>
            <div class="utd-print-two-col"><section><h2>${escape(__("Top transaction types"))}</h2><table><thead><tr><th>#</th><th>${escape(__("DocType"))}</th><th>${escape(__("Count"))}</th></tr></thead><tbody>${tables(top_types, "doctype", item => item.name)}</tbody></table></section><section><h2>${escape(__("Most active document creators"))}</h2><table><thead><tr><th>#</th><th>${escape(__("Employee"))}</th><th>${escape(__("Count"))}</th></tr></thead><tbody>${tables(top_users, "employee", item => item.employee_name)}</tbody></table></section></div>
            <section class="utd-print-detail"><h2>${escape(__("Detailed employee breakdown"))}</h2>${matrix}</section>
            <footer class="utd-print-footer"><strong>${escape(__("Measurement notes"))}</strong> ${escape(__("Counts use document creation time and creator. Drafts, submitted and cancelled documents are included. Using / Not Using reflects enabled System Users with current Create permissions. These metrics do not measure approvals, edits, quality or individual productivity. Totals in the executive overview include the entire selected scope, independent of the Activity View."))}<div>${escape(__("QCMC ERPNext · Confidential internal management use"))}</div></footer>`;
        this.$root.find(".utd-print-report").html(html);
    }

    export_csv() {
        if (!this.data) return;
        const data = this.filter_data();
        // Escape spreadsheet formulas as well as CSV quoting so user names
        // and DocType labels cannot be executed in Excel or other viewers.
        const cell = value => {
            let text = String(value ?? "");
            if (/^[\\s\\u0000-\\u001f]*[=+@-]/.test(text)) text = "'" + text;
            return '"' + text.replace(/"/g, '""') + '"';
        };
        const columns = ["Employee / User", "User ID", "Usage Status", ...data.doctypes, "Total"];
        const records = data.rows.map(row => [row.employee_name, row.user, row.usage_status,
            ...data.doctypes.map(dt => (row.monitored && (row.can_create || []).includes(dt)) || row.counts[dt] ? Number(row.counts[dt] || 0) : ""), row.total]);
        records.push(["Total", "", "", ...data.doctypes.map(dt => data.totals.counts[dt]), data.totals.total]);
        const csv = "\uFEFF" + [columns, ...records].map(row => row.map(cell).join(",")).join("\r\n");
        const blob = new Blob([csv], {type: "text/csv;charset=utf-8"});
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `transaction-management-${this.date_from.get_value()}-to-${this.date_to.get_value()}.csv`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    }

    render(data) {
        const escape = value => frappe.utils.escape_html(String(value ?? ""));
        const number = value => escape(Number(value || 0).toLocaleString());
        const cards = [
            [__("Using"), number(data.summary.using), "using"],
            [__("Not Using"), number(data.summary.not_using), "not-using"],
            [__("Usage Rate"), data.summary.usage_rate == null ? "—" : `${number(data.summary.usage_rate)}%`, "rate"],
            [__("Total Transactions"), number(data.summary.documents), "transactions"],
        ].map(([label, value, kind]) => `
            <div class="utd-card utd-card-${kind}">
                <div class="utd-card-label text-muted">${escape(label)}</div>
                <div class="utd-card-value">${value}</div>
            </div>
        `).join("");
        const eligible = Number(data.summary.using || 0) + Number(data.summary.not_using || 0);
        const activity = [...data.scope_rows || data.rows].filter(row => row.total > 0)
            .sort((a, b) => b.total - a.total || String(a.employee_name).localeCompare(String(b.employee_name)));
        const leader = activity[0];
        const share = leader && data.summary.documents ? (leader.total / data.summary.documents * 100).toFixed(1) : null;
        const adoption = data.summary.usage_rate == null ? "No eligible users in the selected scope." :
            `${data.summary.using} of ${eligible} eligible users created at least one transaction (${data.summary.usage_rate}% adoption).`;
        const activityNote = leader ? `${leader.employee_name} has the highest recorded creation volume (${leader.total.toLocaleString()} documents, ${share}% of this scope).` :
            "No transaction creations were recorded in the selected period.";
        this.$root.find(".utd-scope-host").html(`<div class="utd-report-meta"><span><strong>${escape(__("Reporting period"))}</strong> ${escape(this.date_from.get_value())} — ${escape(this.date_to.get_value())}</span><span><strong>${escape(__("Coverage"))}</strong> ${number(data.scope_doctypes?.length ?? data.doctypes.length)} ${escape(__("transaction types"))} · ${number(eligible)} ${escape(__("eligible users"))}</span></div>`);
        this.$root.find(".utd-insights-host").html(`<section class="utd-executive-brief" aria-label="${escape(__("Executive observations"))}"><div class="utd-section-kicker">EXECUTIVE SNAPSHOT</div><h3>${escape(__("Key observations"))}</h3><div class="utd-insights-grid"><p>${escape(adoption)}</p><p>${escape(activityNote)}</p></div><small>${escape(__("Activity means documents created, not approvals, edits, or completed work. Eligibility reflects current Create permissions, not historical access."))}</small></section>`);
        let table = "";
        if (data.rows.length || this.data?.rows.length) {
            const headers = data.doctypes.map(dt => `<th scope="col" class="utd-number">${escape(__(dt))}</th>`).join("");
            const rows = data.rows.map(row => `
                <tr>
                    <th scope="row" class="utd-name">
                        <div>${escape(row.employee_name)}</div>
                        <div class="utd-user text-muted">${escape(row.user)}</div>
                        <span class="utd-usage-status ${row.eligible ? (row.total > 0 ? "utd-using" : "utd-not-using") : "text-muted"}">${escape(__(row.usage_status || ""))}</span>
                    </th>
                    ${data.doctypes.map(dt => {
                        const count = Number(row.counts[dt] || 0);
                        const allowed = row.monitored && (row.can_create || []).includes(dt);
                        const title = !allowed ? (count > 0 ?
                            __("Historical count; no current Create permission") : __("No current Create permission")) :
                            count ? __("Documents created in the selected period") : __("Has Create permission; no documents created");
                        return `<td class="utd-number${count ? "" : " text-muted"}" title="${escape(title)}">${count || allowed ? number(count) : "—"}</td>`;
                    }).join("")}
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
        this.$root.find(".utd-cards-host").html(`<div class="utd-cards">${cards}</div>`);
        this.$results.html(`<div class="utd-section-heading"><div><div class="utd-section-kicker">DETAILED BREAKDOWN</div><h3>${escape(__("Employee transaction matrix"))}</h3></div><span>${number(data.rows.length)} ${escape(__("displayed users"))}</span></div><p class="utd-legend text-muted small">${escape(__("Using / Not Using: enabled System Users with current Create access in the selected scope. Cards include both groups regardless of Activity View."))}
                <br>${escape(__("0 = has Create access, no activity; — = no current Create access. Historical counts are retained. Table totals follow the displayed rows."))}</p>${table}`);
    }

    add_styles() {
        if (document.getElementById("user-transaction-dashboard-style")) return;
        const style = document.createElement("style");
        style.id = "user-transaction-dashboard-style";
        style.textContent = `
            html:has(> body[data-route="user-transaction-dashboard"]) { height: 100%; overflow: hidden; }
            body[data-route="user-transaction-dashboard"] { height: 100vh; height: 100dvh; overflow: hidden; }
            body[data-route="user-transaction-dashboard"] > .main-section { height: 100vh; height: 100dvh; min-height: 0; overflow-y: auto; }
            .user-transaction-dashboard { padding: 18px 0 48px; --utd-ink: #17324d; --utd-accent: #245b93; }
            .user-transaction-dashboard .utd-report-heading { display:flex; align-items:center; justify-content:space-between; gap:20px; padding:26px 30px; margin-bottom:20px; border-radius:14px; background:linear-gradient(115deg,#102f4d,#245b93); color:#fff; }
            .user-transaction-dashboard .utd-report-heading h2 {font-size:25px;line-height:1.25;font-weight:700;margin:8px 0;color:#fff;}
            .user-transaction-dashboard .utd-report-heading p {margin:0;color:#dbe8f4;max-width:690px;font-size:13px;}
            .user-transaction-dashboard .utd-eyebrow,.user-transaction-dashboard .utd-section-kicker {font-size:10px;letter-spacing:1.5px;font-weight:750;}
            .user-transaction-dashboard .utd-eyebrow {color:#afd5f5;}
            .user-transaction-dashboard .utd-report-tag {font-size:10px;letter-spacing:1px;font-weight:700;color:#dceaf9;border:1px solid #7199bc;padding:9px 12px;border-radius:99px;white-space:nowrap;}
            .user-transaction-dashboard .utd-report-meta {display:flex;flex-wrap:wrap;gap:12px 28px;padding:12px 18px;margin-bottom:16px;background:var(--subtle-fg,#f3f6fa);border-radius:9px;font-size:12px;}
            .user-transaction-dashboard .utd-report-meta strong {margin-right:8px;color:var(--utd-ink);}
            .user-transaction-dashboard .utd-executive-brief {padding:22px 24px;margin:0 0 24px;border:1px solid var(--border-color,#dce3ea);border-radius:12px;background:var(--card-bg,#fff);}
            .user-transaction-dashboard .utd-section-kicker {color:var(--utd-accent);margin-bottom:5px;}
            .user-transaction-dashboard .utd-executive-brief h3,.user-transaction-dashboard .utd-section-heading h3 {margin:0;font-size:17px;font-weight:700;}
            .user-transaction-dashboard .utd-insights-grid {display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:14px 0 12px;}
            .user-transaction-dashboard .utd-insights-grid p {margin:0;padding:13px 16px;background:var(--subtle-fg,#f3f6fa);border-radius:8px;font-size:13px;line-height:1.6;}
            .user-transaction-dashboard .utd-executive-brief small {font-size:11px;color:var(--text-muted,#75808c);}
            .user-transaction-dashboard .utd-section-heading {display:flex;align-items:end;justify-content:space-between;gap:12px;margin:26px 0 12px;}
            .user-transaction-dashboard .utd-section-heading span {font-size:12px;color:var(--text-muted,#75808c);}
            .user-transaction-dashboard .utd-table tbody tr:hover td,.user-transaction-dashboard .utd-table tbody tr:hover th {background:var(--subtle-fg,#f3f6fa);}
            .user-transaction-dashboard .utd-table thead th {color:var(--utd-ink);font-size:12px;font-weight:700;}
            .user-transaction-dashboard .utd-card {box-shadow:0 3px 12px rgba(20,44,67,.04);}
            @media (max-width: 767px) {.user-transaction-dashboard .utd-report-heading{padding:20px;align-items:flex-start;flex-direction:column}.user-transaction-dashboard .utd-insights-grid{grid-template-columns:1fr}.user-transaction-dashboard .utd-report-tag{white-space:normal}}
            @media print {body[data-route="user-transaction-dashboard"]{height:auto;overflow:visible}.user-transaction-dashboard .utd-report-heading{-webkit-print-color-adjust:exact;print-color-adjust:exact}.user-transaction-dashboard .utd-table-scroll{max-height:none;overflow:visible}.user-transaction-dashboard .utd-filters{display:none}}
            .user-transaction-dashboard .utd-print-report { display: none; }
            @page { size: A4 landscape; margin: 13mm 13mm 15mm; }
            @media print {
                html, body, body[data-route="user-transaction-dashboard"], body[data-route="user-transaction-dashboard"] > .main-section {
                    width: 100% !important; height: auto !important; min-height: 0 !important;
                    overflow: visible !important; background: #fff !important;
                }
                body[data-route="user-transaction-dashboard"] .navbar,
                body[data-route="user-transaction-dashboard"] .page-head,
                body[data-route="user-transaction-dashboard"] .layout-side-section,
                body[data-route="user-transaction-dashboard"] .desk-sidebar,
                body[data-route="user-transaction-dashboard"] .sidebar-column,
                body[data-route="user-transaction-dashboard"] .page-footer,
                body[data-route="user-transaction-dashboard"] .footer-powered,
                body[data-route="user-transaction-dashboard"] .page-actions,
                body[data-route="user-transaction-dashboard"] .standard-actions { display: none !important; }
                body[data-route="user-transaction-dashboard"] .layout-main,
                body[data-route="user-transaction-dashboard"] .layout-main-section,
                body[data-route="user-transaction-dashboard"] .page-content,
                body[data-route="user-transaction-dashboard"] .page-body,
                body[data-route="user-transaction-dashboard"] .page-container,
                body[data-route="user-transaction-dashboard"] .page-wrapper,
                body[data-route="user-transaction-dashboard"] .main-section { width:100% !important; max-width:none !important; margin:0 !important; padding:0 !important; border:0 !important; box-shadow:none !important; }
                .user-transaction-dashboard { padding:0 !important; margin:0 !important; width:100% !important; color:#182d40 !important; font-family:Arial,Helvetica,sans-serif !important; }
                .user-transaction-dashboard > :not(.utd-print-report) { display:none !important; }
                .user-transaction-dashboard .utd-print-report { display:block !important; font-size:9pt; line-height:1.45; color:#182d40; }
                .utd-print-report .utd-print-header { display:flex; justify-content:space-between; align-items:flex-start; gap:20mm; border-bottom:2px solid #183d60; padding:0 0 12px; margin-bottom:14px; }
                .utd-print-report .utd-print-kicker {font-size:8pt;color:#426a8c;letter-spacing:1.5px;font-weight:700;margin:0 0 5px;}
                .utd-print-report h1 {font-size:20pt;line-height:1.2;color:#173b5e;margin:0 0 6px;font-weight:700;}
                .utd-print-report .utd-print-header p:last-child {margin:0;color:#546779;font-size:9pt;}
                .utd-print-report .utd-print-header > span {border:1px solid #a6b6c7;padding:6px 9px;border-radius:4px;font-size:7pt;letter-spacing:0.7px;white-space:nowrap;}
                .utd-print-report .utd-print-meta {display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:8px;}
                .utd-print-report .utd-print-meta > div {background:#edf3f7;padding:10px;break-inside:avoid;}
                .utd-print-report .utd-print-meta strong {display:block;font-size:7pt;text-transform:uppercase;letter-spacing:.6px;color:#53687b;}
                .utd-print-report .utd-print-meta span {display:block;font-size:10pt;font-weight:700;margin-top:3px;}
                .utd-print-report .utd-print-selection {font-size:7.5pt;color:#53687b;overflow-wrap:anywhere;padding:6px 0;margin:0 0 8px;}
                .utd-print-report h2 {font-size:11pt;color:#173b5e;font-weight:700;margin:15px 0 8px;padding-bottom:5px;border-bottom:1px solid #b9c9d8;}
                .utd-print-report .utd-print-kpis {display:grid;grid-template-columns:repeat(4,1fr);gap:9px;}
                .utd-print-report .utd-print-kpis > div {border:1px solid #cbd6e1;border-top:3px solid #245b93;padding:10px 12px;break-inside:avoid;}
                .utd-print-report .utd-print-kpis strong {font-size:17pt;line-height:1.2;display:block;color:#173b5e;}
                .utd-print-report .utd-print-kpis span {font-size:8pt;color:#52677a;display:block;margin-top:4px;}
                .utd-print-report .utd-print-analysis {margin:10px 0 14px;padding:10px 12px;border-left:3px solid #245b93;background:#f4f7fa;break-inside:avoid;}
                .utd-print-report .utd-print-two-col {display:grid;grid-template-columns:1fr 1fr;gap:14mm;align-items:start;}
                .utd-print-report section {min-width:0;}
                .utd-print-report table {width:100%;border-collapse:collapse;table-layout:fixed;margin:0 0 12px;font-size:8pt;}
                .utd-print-report th {text-align:left;background:#e9f0f6;color:#183b59;font-weight:700;}
                .utd-print-report td,.utd-print-report th {padding:5px 7px;border-bottom:1px solid #d5dfe8;overflow-wrap:anywhere;vertical-align:top;}
                .utd-print-report tbody tr:nth-child(even) td {background:#f8fafc;}
                .utd-print-report thead {display:table-header-group;}
                .utd-print-report tr {break-inside:avoid;page-break-inside:avoid;}
                .utd-print-report .utd-print-rank {width:26px;color:#60758a;}
                .utd-print-report .utd-print-numeric {text-align:right;font-variant-numeric:tabular-nums;width:70px;}
                .utd-print-report .utd-print-detail {break-before:auto;page-break-before:auto;}
                .utd-print-report .utd-print-matrix th,.utd-print-report .utd-print-matrix td {font-size:7pt;padding:5px 6px;}
                .utd-print-report .utd-print-matrix small {display:block;color:#667788;font-size:6.5pt;}
                .utd-print-report .utd-print-note {border:1px dashed #b9c9d8;padding:10px;color:#546779;}
                .utd-print-report .utd-print-footer {border-top:1px solid #b9c9d8;margin-top:14px;padding-top:8px;font-size:7pt;line-height:1.5;color:#506276;break-inside:avoid;}
                .utd-print-report .utd-print-footer div {margin-top:5px;font-weight:700;}
                .utd-print-report .utd-print-two-col,.utd-print-report .utd-print-kpis,.utd-print-report .utd-print-header {-webkit-print-color-adjust:exact;print-color-adjust:exact;}
            }
            .user-transaction-dashboard .utd-filters { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; padding: 16px; margin-bottom: 16px; border: 1px solid var(--border-color, #d1d8dd); border-radius: var(--border-radius-md, 8px); background: var(--card-bg, #fff); }
            .user-transaction-dashboard .utd-filter .frappe-control { margin-bottom: 0; }
            .user-transaction-dashboard .utd-filter .dropdown-menu { min-width: 280px; max-width: 85vw; }
            .user-transaction-dashboard .utd-description { margin-bottom: 16px; }
            .user-transaction-dashboard .utd-status:empty { display: none; }
            .user-transaction-dashboard .utd-cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-bottom: 16px; }
            .user-transaction-dashboard .utd-card { background: var(--card-bg, #fff); border: 1px solid var(--border-color, #d1d8dd); border-radius: var(--border-radius-md, 8px); padding: 20px; }
            .user-transaction-dashboard .utd-card-label { font-size: 13px; margin-bottom: 8px; }
            .user-transaction-dashboard .utd-card-value { font-size: 28px; font-weight: 600; color: var(--text-color); }
            .user-transaction-dashboard .utd-card-using { border-top: 3px solid var(--green-500, #28a745); }
            .user-transaction-dashboard .utd-card-not-using { border-top: 3px solid var(--orange-500, #f59e0b); }
            .user-transaction-dashboard .utd-usage-status { display: inline-block; font-size: 11px; font-weight: 500; margin-top: 6px; }
            .user-transaction-dashboard .utd-using { color: var(--green-600, #198754); }
            .user-transaction-dashboard .utd-not-using { color: var(--orange-600, #b86e00); }
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
