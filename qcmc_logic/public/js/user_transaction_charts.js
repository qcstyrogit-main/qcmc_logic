/* Management charts for the User Transaction Dashboard. No transaction data is saved. */
(() => {
    const API = "qcmc_logic.qcmc_logics.page.user_transaction_dashboard.user_transaction_dashboard.";
    const escape = value => frappe.utils.escape_html(String(value ?? ""));
    const metricLabels = {documents:"Documents Created", using:"Using", not_using:"Not Using", usage_rate:"Usage Rate", adoption:"Using vs Not Using"};
    const groupLabels = {module:"Module", doctype:"DocType", user:"User", overall:"Overall", day:"Day", month:"Month"};
    const typeLabels = {bar:"Bar", stacked_bar:"Stacked Bar", line:"Line", pie:"Pie", donut:"Donut"};

    function validate(config) {
        if (!config || !/^[A-Za-z0-9_-]{1,64}$/.test(config.id) || typeof config.title !== "string" ||
            !config.title.trim() || config.title.length > 120 || !Object.hasOwn(typeLabels, config.type) ||
            !Object.hasOwn(metricLabels, config.metric) || !Object.hasOwn(groupLabels, config.group_by) || ![0,5,10].includes(config.top_n)) {
            throw new Error("Choose a title, chart type, measure, grouping and Top N.");
        }
        if ((["day","month"].includes(config.group_by) && (config.metric !== "documents" || !["line","bar"].includes(config.type))) ||
            (config.type === "line" && !["day","month"].includes(config.group_by)) ||
            (config.type === "stacked_bar" && config.metric !== "adoption") ||
            (["pie","donut"].includes(config.type) && !(config.metric === "documents" || (config.metric === "adoption" && config.group_by === "overall")))) {
            throw new Error("Use line charts for creation trends, stacked bars for Using vs Not Using, and pie/donut for transaction shares or overall adoption.");
        }
        return {...config, title:config.title.trim()};
    }

    function metrics(rows, types) {
        let documents = 0, eligible = 0, using = 0;
        for (const row of rows) {
            const count = types.reduce((sum, dt) => sum + Number(row.counts[dt] || 0), 0);
            documents += count;
            if (row.monitored && types.some(dt => (row.can_create || []).includes(dt))) {
                eligible++;
                if (count > 0) using++;
            }
        }
        return {documents, using, not_using:eligible-using, eligible, usage_rate:eligible ? Math.round(using/eligible*1000)/10 : null};
    }

    function aggregate(config, scope) {
        validate(config);
        if (["day","month"].includes(config.group_by)) {
            const trend = scope.trend || {labels:[],values:[]};
            return {labels:trend.labels, datasets:[{name:__("Documents Created"),values:trend.values}], empty:!trend.values.some(value=>value>0), categories:trend.labels.length};
        }
        const groups = new Map();
        if (config.group_by === "overall") groups.set("overall", {label:__("Selected scope"), types:scope.doctypes, rows:scope.rows});
        else if (config.group_by === "user") {
            for (const row of scope.rows) groups.set(row.user, {label:`${row.employee_name} (${row.user})`, types:scope.doctypes, rows:[row]});
        } else {
            for (const dt of scope.doctypes) {
                const key = config.group_by === "module" ? (scope.modules[dt] || __("Other Module")) : dt;
                if (!groups.has(key)) groups.set(key, {label:__(key), types:[], rows:scope.rows});
                groups.get(key).types.push(dt);
            }
        }
        let points = [...groups.values()].map(group=>({label:group.label, ...metrics(group.rows,group.types)}))
            .filter(point=>config.metric === "documents" ? (point.documents > 0 || point.eligible > 0) : point.eligible > 0);
        const rank = point => config.metric === "adoption" ? point.eligible : point[config.metric];
        points.sort((a,b)=>rank(b)-rank(a) || a.label.localeCompare(b.label));
        const categories = points.length;
        if (config.top_n && points.length > config.top_n) {
            const remainder = points.slice(config.top_n);
            points = points.slice(0,config.top_n);
            if (["pie","donut"].includes(config.type) && config.metric === "documents") {
                points.push({label:__("Other"),documents:remainder.reduce((sum,point)=>sum+point.documents,0)});
            }
        }
        let labels = points.map(point=>point.label), datasets;
        if (config.metric === "adoption" && ["pie","donut"].includes(config.type)) {
            labels = [__("Using"),__("Not Using")];
            const totals = metrics(scope.rows, scope.doctypes);
            datasets = [{name:__("Users"),values:[totals.using,totals.not_using]}];
        } else if (config.metric === "adoption") {
            datasets = ["using","not_using"].map(key=>({name:__(metricLabels[key]),values:points.map(point=>point[key])}));
        } else datasets = [{name:__(metricLabels[config.metric]),values:points.map(point=>point[config.metric])}];
        return {labels,datasets,categories,empty:!datasets.some(dataset=>dataset.values.some(value=>value>0))};
    }

    function chart_options(config, model) {
        const palette = ["#4263eb","#12b886","#f59f00","#e64980","#7950f2","#15aabf","#82c91e","#fd7e14"];
        return {title:config.title, type:config.type === "stacked_bar" ? "bar" : config.type,
            height:300, animate:false, disableEntryAnimation:true, isNavigable:false,
            maxSlices:Math.max(20,model.labels.length), maxLegendPoints:Math.max(20,model.labels.length),
            colors:config.metric === "adoption" ? ["#2f9e44","#f59f00"] : model.labels.map((_,i)=>palette[i % palette.length]),
            data:{labels:model.labels, datasets:model.datasets},
            barOptions:{stacked:config.type === "stacked_bar"},
            tooltipOptions:{formatTooltipY:value=>`${value}${config.metric === "usage_rate" ? "%" : ""}`}};
    }

    function render_native(chart) {
        // Installed Frappe Charts writes SVG labels with textContent, but uses
        // HTML for hover tooltips. Escape only at that HTML boundary.
        if (chart.tip?.setValues) {
            const setValues = chart.tip.setValues.bind(chart.tip);
            chart.tip.setValues = (x,y,title={},rows=[],index=-1) => setValues(x,y,
                {...title,name:escape(title.name),value:escape(title.value)},
                rows.map(row=>({...row,title:escape(row.title),
                    value:typeof row.value === "string" ? escape(row.value) : row.value,
                    formatted:typeof row.formatted === "string" ? escape(row.formatted) : row.formatted})),index);
        }
        // Axis charts initially draw zero/partial data and schedule a delayed
        // update. Render the real values without animation before export/print.
        chart.update(chart.realData);
    }

    function data_table(model) {
        return `<table><thead><tr><th>${escape(__("Category"))}</th>${model.datasets.map(d=>`<th>${escape(d.name)}</th>`).join("")}</tr></thead><tbody>${model.labels.map((label,i)=>`<tr><th scope="row">${escape(label)}</th>${model.datasets.map(d=>`<td>${escape(d.values[i])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    }

    function scope_description(scope) {
        const selected = scope.selections || {};
        return `${__("Modules")}: ${(selected.modules || []).join(", ") || __("All")} · ${__("DocTypes")}: ${(selected.doctypes || []).join(", ") || __("All")} · ${__("Users")}: ${(selected.users || []).join(", ") || __("All")}`;
    }

    function report_html(scope, charts, summary, generated) {
        const cards = [[__("Using"),summary.using],[__("Not Using"),summary.not_using],[__("Usage Rate"),summary.usage_rate == null ? "—" : `${summary.usage_rate}%`],[__("Total Transactions"),summary.documents]];
        return `<!doctype html><html><head><meta charset="utf-8"><title>${escape(__("User Transaction Management Report"))}</title><style>
            *{box-sizing:border-box}body{font:10px/1.35 Arial,sans-serif;color:#243448;margin:18px}
            .report-header{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;padding:0 0 9px;border-bottom:2px solid #254b72;margin-bottom:10px}
            h1{font-size:19px;line-height:1.2;color:#193d60;margin:0 0 4px}h2{font-size:12px;line-height:1.3;color:#193d60;margin:0 0 3px}
            p{overflow-wrap:anywhere;color:#526275;margin:0 0 8px}
            .report-header p{font-size:9px}.report-label{font-size:8px;letter-spacing:1px;color:#315e89;font-weight:700;text-align:right;white-space:nowrap}
            .cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:9px 0}
            .card{padding:8px 10px;border:1px solid #cbd6e1;border-top:2px solid #315e89;min-width:0;background:#f8fafc}
            .card strong{display:block;font-size:19px;margin-top:3px;color:#193d60}
            .report-note{font-size:8px;line-height:1.35;margin:8px 0 11px}
            .report-sheet{width:281mm;max-width:none;transform-origin:top left}
            .report-charts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px 9px;align-items:start}
            .report-chart{min-width:0;border:1px solid #d4dde6;padding:6px 7px;margin:0;break-inside:avoid;page-break-inside:avoid}
            .report-chart p{font-size:8px;margin:0 0 5px}
            .report-chart svg{display:block;width:100%;max-width:100%;height:124px;max-height:none;margin:1px auto 3px;overflow:hidden}
            .report-chart svg text{font-family:Arial,sans-serif;fill:#223346}
            table{border-collapse:collapse;width:100%;table-layout:fixed;margin-top:3px;font-size:8px;line-height:1.2}
            th,td{border:1px solid #d7e0e8;padding:2px 3px;text-align:left;overflow-wrap:anywhere}
            th{background:#ebf1f6;color:#254b72}td{text-align:right}td:first-child{text-align:left}
            thead{display:table-header-group}tr{break-inside:avoid;page-break-inside:avoid}
            @page{size:A4 landscape;margin:8mm}
            @media print{body{margin:0;-webkit-print-color-adjust:exact;print-color-adjust:exact}
            .report-charts{gap:6px 8px}.report-chart{padding:5px 6px}
            .report-chart svg{height:124px;max-height:none}
            .report-chart:has(table tbody tr:nth-child(12)){break-inside:auto;page-break-inside:auto}
            .report-chart table{break-inside:auto}}
            </style></head><body><main class="report-sheet" id="report-sheet"><header class="report-header"><div><h1>${escape(__("User Transaction Management Report"))}</h1>
            <p>${escape(__("Creation period"))}: ${escape(scope.date_from)} — ${escape(scope.date_to)} · ${escape(scope_description(scope))}<br>${escape(__("Generated"))}: ${escape(generated)}</p></div><div class="report-label">QCMC ERPNext<br>INTERNAL MANAGEMENT REPORT</div></header>
            <div class="cards">${cards.map(([label,value])=>`<div class="card">${escape(label)}<strong>${escape(value ?? 0)}</strong></div>`).join("")}</div>
            <p class="report-note">${escape(__("All document statuses are included. Usage compares enabled System Users with current Create permission. Charts use the full selected scope, independently of the grid Activity View. Historical counts are retained; permissions are current, not historical snapshots."))}</p>
            <div class="report-charts">${charts.map(chart=>`<section class="report-chart"><h2>${escape(chart.title)}</h2><p>${escape(__(metricLabels[chart.metric]))} · ${escape(__(groupLabels[chart.group_by]))}${chart.top_n && !["day","month"].includes(chart.group_by) ? ` · ${escape(__("Top"))} ${chart.top_n}` : ""}</p>${chart.svg || ""}${chart.model.empty ? `<p>${escape(__("No values for this selection."))}</p>` : ""}${data_table(chart.model)}</section>`).join("")}</div></main>
            </body></html>`;
    }

    frappe.user_transaction_chart_data = {validate, aggregate, chart_options, render_native, report_html, data_table};

    frappe.UserTransactionCharts = class UserTransactionCharts {
        constructor(dashboard) {
            this.dashboard = dashboard;
            this.$host = dashboard.$root.find(".utd-chart-host");
            this.definitions = this.defaults();
            this.instances = new Map();
            this.models = new Map();
            this.trends = new Map();
            this.generation = 0;
            this.edit_revision = 0;
            this.loaded = false;
            this.scope = null;
            this.$host.html(`<section class="utd-management-charts"><div class="utd-chart-toolbar"><h3>${escape(__("Management Charts"))}</h3><div>
                <button class="btn btn-default btn-sm" data-action="add">${escape(__("Add Chart"))}</button>
                <button class="btn btn-default btn-sm" data-action="save">${escape(__("Save Layout"))}</button>
                <button class="btn btn-default btn-sm" data-action="reset">${escape(__("Reset Defaults"))}</button>
                <button class="btn btn-primary btn-sm" data-action="print" disabled>${escape(__("Print Management Report"))}</button>
                </div></div><p class="text-muted small utd-chart-context"></p><p class="text-muted small utd-layout-status" role="status"></p><div class="utd-chart-grid"></div></section>`);
            this.$grid = this.$host.find(".utd-chart-grid");
            this.$host.on("click","button[data-action]",event=>{
                const action = event.currentTarget.dataset.action;
                const id = event.currentTarget.dataset.id;
                if (action === "add") this.edit();
                if (action === "edit") this.edit(id);
                if (action === "remove") { this.definitions = this.definitions.filter(chart=>chart.id !== id); this.changed(); }
                if (action === "save") this.save();
                if (action === "reset" && this.loaded) { this.definitions = this.defaults(); this.changed(); }
                if (action === "print") this.print();
                if (action === "export") this.instances.get(id)?.export();
            });
            this.install_styles();
            this.ready = this.load();
        }

        defaults() {
            return [
                {id:"adoption",title:__("Using vs Not Using"),type:"donut",metric:"adoption",group_by:"overall",top_n:0},
                {id:"modules",title:__("Transactions by Module"),type:"bar",metric:"documents",group_by:"module",top_n:10},
                {id:"doctypes",title:__("Most-used DocTypes"),type:"bar",metric:"documents",group_by:"doctype",top_n:10},
                {id:"users",title:__("Top Users by Documents Created"),type:"bar",metric:"documents",group_by:"user",top_n:10},
                {id:"trend",title:__("Monthly Creation Trend"),type:"line",metric:"documents",group_by:"month",top_n:0},
            ];
        }

        async load() {
            try {
                const response = await frappe.call({method:API+"get_chart_layout"});
                if (response.message?.charts !== null && response.message?.charts !== undefined) {
                    this.definitions = response.message.charts.map(validate);
                }
                this.status(__("Personal chart layout loaded. Changes apply when you select Save Layout."));
            } catch (error) {
                this.status(__("Saved layout could not be loaded. Default charts are shown; saving will replace your personal layout."));
            }
            this.loaded = true;
            if (this.scope) await this.render();
        }

        status(text) { this.$host.find(".utd-layout-status").text(text); }

        changed() {
            this.edit_revision++;
            this.status(__("Unsaved chart layout. Select Save Layout to keep these charts."));
            this.render();
        }

        async save() {
            if (!this.loaded || this.saving) return;
            this.saving = true;
            const revision = this.edit_revision;
            const definitions = JSON.stringify(this.definitions);
            this.status(__("Saving personal layout…"));
            try {
                await frappe.call({method:API+"save_chart_layout",args:{charts:definitions}});
                this.status(revision === this.edit_revision ? __("Personal chart layout saved.") : __("Earlier layout saved. Newer chart changes are still unsaved."));
            } catch (error) { this.status(__("Layout could not be saved. Your current charts are still available; try Save Layout again.")); }
            finally { this.saving = false; }
        }

        edit(id) {
            if (!this.loaded) return;
            if (!id && this.definitions.length >= 12) { frappe.msgprint(__("A layout can contain up to 12 charts.")); return; }
            const original = this.definitions.find(chart=>chart.id === id);
            const initial = original || {type:"bar",metric:"documents",group_by:"module",top_n:10,title:""};
            const dialog = new frappe.ui.Dialog({title:original ? __("Edit Chart") : __("Add Chart"),fields:[
                {fieldname:"title",label:__("Chart Title"),fieldtype:"Data",reqd:1,default:initial.title},
                {fieldname:"type",label:__("Chart Type"),fieldtype:"Select",reqd:1,options:Object.values(typeLabels).map(label=>__(label)),default:__(typeLabels[initial.type])},
                {fieldname:"metric",label:__("Measure"),fieldtype:"Select",reqd:1,options:Object.values(metricLabels).map(label=>__(label)),default:__(metricLabels[initial.metric])},
                {fieldname:"group_by",label:__("Group By"),fieldtype:"Select",reqd:1,options:Object.values(groupLabels).map(label=>__(label)),default:__(groupLabels[initial.group_by]),description:__("Line charts: Documents Created by Day or Month. Stacked bars: Using vs Not Using. Pie/donut: transaction shares or overall adoption.")},
                {fieldname:"top_n",label:__("Display"),fieldtype:"Select",options:[__("Top 5"),__("Top 10"),__("All")],default:initial.top_n ? __(`Top ${initial.top_n}`) : __("All")},
            ],primary_action_label:__("Apply Chart"),primary_action:values=>{
                const key = (map,value)=>Object.keys(map).find(key=>__(map[key]) === value);
                try {
                    const config = validate({id:original?.id || `c_${Date.now()}_${Math.random().toString(36).slice(2,8)}`,
                        title:values.title,type:key(typeLabels,values.type),metric:key(metricLabels,values.metric),group_by:key(groupLabels,values.group_by),
                        top_n:values.top_n === __("All") ? 0 : values.top_n === __("Top 5") ? 5 : 10});
                    this.definitions = original ? this.definitions.map(chart=>chart.id === id ? config : chart) : [...this.definitions,config];
                    dialog.hide(); this.changed();
                } catch (error) { frappe.msgprint(__(error.message)); }
            }});
            dialog.show();
        }

        destroy_instances() {
            for (const chart of this.instances.values()) chart.destroy();
            this.instances.clear();
        }

        clear() {
            this.generation++;
            this.scope = null;
            this.scope_key = null;
            this.destroy_instances();
            this.models.clear();
            this.$grid.empty();
            this.$host.find('[data-action="print"]').prop("disabled",true);
            this.$host.find(".utd-chart-context").text(__("Charts will follow the selected dates and filters once data loads."));
        }

        update(scope) {
            const key = JSON.stringify([scope.data_version,scope.date_from,scope.date_to,scope.selections]);
            if (key === this.scope_key) return;
            this.scope_key = key;
            this.scope = scope;
            this.trends.clear();
            if (this.loaded) this.render();
        }

        async render() {
            const generation = ++this.generation;
            this.destroy_instances();
            this.models.clear();
            this.$grid.empty();
            this.$host.find('[data-action="print"]').prop("disabled",true);
            if (!this.scope) return;
            const scope = this.scope;
            this.$host.find(".utd-chart-context").text(`${scope.date_from} — ${scope.date_to} · ${scope_description(scope)} · ${__("Charts summarize the full selected scope; Activity View changes only the grid.")}`);
            let failed = false;
            await Promise.all(this.definitions.map(async config=>{
                const $card = $(`<article class="utd-chart-card"><div class="utd-chart-actions"><button class="btn btn-default btn-xs" data-action="edit" data-id="${escape(config.id)}">${escape(__("Edit"))}</button> <button class="btn btn-default btn-xs" data-action="export" data-id="${escape(config.id)}" disabled>${escape(__("Export SVG"))}</button> <button class="btn btn-default btn-xs" data-action="remove" data-id="${escape(config.id)}">${escape(__("Remove"))}</button></div><p class="utd-chart-caption text-muted small"></p><div class="utd-chart-canvas"></div><div class="utd-chart-values"></div></article>`).appendTo(this.$grid);
                $card.find(".utd-chart-caption").text(`${__(metricLabels[config.metric])} · ${__(groupLabels[config.group_by])}${config.top_n && !["day","month"].includes(config.group_by) ? ` · ${__("Top")} ${config.top_n}` : ""}`);
                const $canvas = $card.find(".utd-chart-canvas");
                $canvas.text(__("Loading chart…"));
                try {
                    let input = scope;
                    if (["day","month"].includes(config.group_by)) {
                        const interval = config.group_by;
                        if (!this.trends.has(interval)) {
                            const request = frappe.call({method:API+"get_creation_trend",args:{date_from:scope.date_from,date_to:scope.date_to,
                                doctypes:JSON.stringify(scope.doctypes),users:JSON.stringify(scope.selections.users),interval}}).then(response=>response.message);
                            this.trends.set(interval,request);
                            request.catch(()=>{ if (this.trends.get(interval) === request) this.trends.delete(interval); });
                        }
                        input = {...scope,trend:await this.trends.get(interval)};
                    }
                    if (generation !== this.generation) return;
                    const model = aggregate(config,input);
                    this.models.set(config.id,{...config,model});
                    $canvas.empty();
                    if (model.empty) $canvas.html(`<h4>${escape(config.title)}</h4><p class="text-muted">${escape(__("No values for this selection."))}</p>`);
                    else {
                        const chart = new frappe.Chart($canvas[0],chart_options(config,model));
                        this.instances.set(config.id,chart);
                        render_native(chart);
                        $card.find('[data-action="export"]').prop("disabled",false);
                    }
                    $card.find(".utd-chart-values").html(`<details><summary>${escape(__("View Chart Data"))}</summary>${data_table(model)}</details>`);
                } catch (error) {
                    if (generation !== this.generation) return;
                    failed = true;
                    $canvas.html(`<h4>${escape(config.title)}</h4><p class="text-muted">${escape(__("Chart could not be loaded. Daily trends support up to 366 days; monthly trends support 120 months. Check the date range and select Refresh."))}</p>`);
                }
            }));
            if (generation !== this.generation) return;
            this.failed = failed;
            this.$host.find('[data-action="print"]').prop("disabled",failed);
            if (!this.definitions.length) this.$grid.text(__("No charts yet. Select Add Chart or Reset Defaults."));
        }

        print() {
            if (!this.scope || this.failed || this.models.size !== this.definitions.length) {
                frappe.msgprint(__("Wait for every chart to load successfully before printing.")); return;
            }
            const report = window.open("","_blank");
            if (!report) { frappe.msgprint(__("Allow the report window to open, then select Print Management Report again.")); return; }
            const charts = this.definitions.map(config=>{
                const chart = this.instances.get(config.id);
                return {...this.models.get(config.id),svg:chart?.svg?.outerHTML || ""};
            });
            report.document.open();
            report.document.write(report_html(this.scope,charts,this.scope.summary,frappe.datetime.now_datetime()));
            report.document.close();
            // Frappe chart SVGs are drawn in their original pixel coordinate
            // system. Capping SVG height without a matching viewBox clips the
            // lower halves of donuts, bars, axes and legends in print.
            for (const svg of report.document.querySelectorAll?.(".report-chart svg") || []) {
                if (!svg.getAttribute("viewBox")) {
                    const width = Number.parseFloat(svg.getAttribute("width"));
                    const height = Number.parseFloat(svg.getAttribute("height"));
                    if (Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0) {
                        svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
                    }
                }
                svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
            }
            // Measure the report at the fixed A4-landscape content width, then
            // scale the entire sheet when a modest reduction can fit one page.
            // This avoids Chrome moving a complete grid row to an empty sheet.
            const sheet = report.document.querySelector?.("#report-sheet");
            if (sheet) {
                const ruler = report.document.createElement("div");
                ruler.style.cssText = "position:absolute;visibility:hidden;height:194mm;width:1px";
                report.document.body.appendChild(ruler);
                const pageHeight = ruler.getBoundingClientRect().height;
                ruler.remove();
                const contentHeight = Math.max(sheet.scrollHeight, sheet.getBoundingClientRect().height);
                const zoom = Math.min(1, (pageHeight - 12) / Math.max(contentHeight, 1));
                // For much longer reports, retain readable multipage output.
                if (zoom >= 0.65 && zoom < 1) {
                    sheet.style.zoom = String(Math.floor(zoom * 100) / 100);
                }
            }
            report.focus();
            report.print();
        }

        install_styles() {
            if (document.getElementById("utd-management-chart-style")) return;
            const style = document.createElement("style");
            style.id = "utd-management-chart-style";
            style.textContent = `.user-transaction-dashboard .utd-management-charts{margin:20px 0 28px}.user-transaction-dashboard .utd-chart-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.user-transaction-dashboard .utd-chart-toolbar h3{font-size:18px;margin:0}.user-transaction-dashboard .utd-chart-toolbar button{margin:3px}.user-transaction-dashboard .utd-chart-context{margin-top:12px;overflow-wrap:anywhere}.user-transaction-dashboard .utd-chart-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.user-transaction-dashboard .utd-chart-card{min-width:0;padding:14px;border:1px solid var(--border-color,#ddd);border-radius:8px;background:var(--card-bg,#fff)}.user-transaction-dashboard .utd-chart-actions{text-align:right;margin-bottom:10px}.user-transaction-dashboard .utd-chart-canvas{min-height:300px;overflow-x:auto}.user-transaction-dashboard .utd-chart-values{overflow-x:auto}.user-transaction-dashboard .utd-chart-values table{width:100%;border-collapse:collapse;font-size:12px;margin-top:10px}.user-transaction-dashboard .utd-chart-values th,.user-transaction-dashboard .utd-chart-values td{padding:5px;border:1px solid var(--border-color,#ddd)}.user-transaction-dashboard .utd-chart-values td{text-align:right}@media(max-width:900px){.user-transaction-dashboard .utd-chart-grid{grid-template-columns:1fr}}`;
            document.head.appendChild(style);
        }
    };
})();
