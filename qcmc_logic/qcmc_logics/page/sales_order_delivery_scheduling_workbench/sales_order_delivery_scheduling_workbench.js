frappe.pages["sales-order-delivery-scheduling-workbench"].on_page_load = function(wrapper) {
    const page = frappe.ui.make_app_page({parent: wrapper, title: __("Sales Order Delivery Scheduling Workbench"), single_column: true});
    wrapper.sales_planning = new SalesPlanningWorkbench(page);
};
frappe.pages["sales-order-delivery-scheduling-workbench"].on_page_show = function(wrapper) {
    if (wrapper.sales_planning && !wrapper.sales_planning.loaded) wrapper.sales_planning.refresh();
};

class SalesPlanningWorkbench {
    constructor(page) {
        this.page = page;
        this.rows = [];
        this.start = 0;
        this.has_more = false;
        this.loaded = false;
        this.busy = false;
        this.dirty = false;
        this.sequence = 0;
        this.column_filters = {};
        this.sort_column = null;
        this.sort_direction = 1;
        this.columns = [
            ["customer_name","Customer"], ["sales_order","SO"], ["item_code","Item"],
            ["warehouse","Warehouse"], ["original_promise_date","Original Promise"], ["delivery_date","Schedule Date"],
            ["ordered_qty","Ordered Qty","number"], ["delivered_qty","Delivered Qty","number"], ["available_qty","Open Schedule Qty","number"],
            ["deliver_on","Deliver On"], ["quantity","Qty to Deliver","number"], ["sales_remarks","Sales Remarks"], ["status","Status / Action"]
        ];
        this.page.set_primary_action(__("Refresh"), () => this.refresh(true), "refresh");
        this.page.add_inner_button(__("Save Schedule"), () => this.save(false));
        this.page.add_inner_button(__("Endorse Selected to Logistics"), () => this.save(true));
        this.page.add_inner_button(__("Delivery Schedule Workbench"), () => {
            if (this.dirty) return frappe.msgprint(__("Save or discard the selected changes first."));
            frappe.set_route("delivery-schedule-workbench");
        });
        this.page.main.html('<div class="sales-planning delivery-workbench"><div class="delivery-workbench-filters"></div><div class="delivery-workbench-kpis"></div><div class="delivery-workbench-summary text-muted small"></div><div class="delivery-workbench-table-wrapper"><table class="table planning-table"><colgroup><col style="width:36px"><col style="width:210px"><col style="width:108px"><col style="width:110px"><col style="width:125px"><col style="width:120px"><col style="width:120px"><col style="width:108px"><col style="width:108px"><col style="width:142px"><col style="width:136px"><col style="width:126px"><col style="width:180px"><col style="width:200px"></colgroup><thead></thead><tbody></tbody></table></div><div class="planning-pagination mt-3"></div></div>');
        this.root = this.page.main.find(".sales-planning");
        this.filtersEl = this.root.find(".delivery-workbench-filters");
        this.kpisEl = this.root.find(".delivery-workbench-kpis");
        this.summaryEl = this.root.find(".delivery-workbench-summary");
        this.tbodyEl = this.root.find("tbody");
        this.theadEl = this.root.find("thead");
        this.paginationEl = this.root.find(".planning-pagination");
        this.filters = {};
        this.setup_filters();
        this.add_styles();
        this.bind_events();
        window.addEventListener("beforeunload", e => { if (this.dirty || this.busy) {e.preventDefault(); e.returnValue = "";} });
        this.refresh();
    }

    setup_filters() {
        this.filtersEl.html('<div class="delivery-filter-row"></div>');
        const container = this.filtersEl.find(".delivery-filter-row");
        const fields = [
            {fieldname:"company", label:__("Company"), fieldtype:"Link", options:"Company", reqd:1, default:frappe.defaults.get_user_default("Company")},
            {fieldname:"delivery_date", label:__("Delivery Date / Through"), fieldtype:"Date", reqd:1, default:frappe.datetime.get_today()},
            {fieldname:"warehouse", label:__("Warehouse"), fieldtype:"Link", options:"Warehouse", get_query:() => ({filters:{company:this.filters.company.get_value(), is_group:0, custom_is_province:0}})},
            {fieldname:"customer", label:__("Customer"), fieldtype:"Link", options:"Customer"},
            {fieldname:"include_future", label:__("Include future schedules"), fieldtype:"Check", default:0}
        ];
        this.initializing = true;
        for (const df of fields) {
            const parent = jQuery('<div class="delivery-filter"></div>').appendTo(container);
            const control = frappe.ui.form.make_control({parent, df:{...df, change:() => {
                if (!this.initializing) this.refresh(true);
            }}, render_input:true});
            this.filters[df.fieldname] = control;
            if (df.default != null) control.set_value(df.default);
        }
        this.initializing = false;
    }

    add_styles() {
        frappe.dom.set_style([
            ".sales-planning .delivery-filter-row{display:flex;gap:12px;align-items:end;flex-wrap:wrap}",
            ".sales-planning .delivery-filter{min-width:160px;flex:1}",
            ".sales-planning .delivery-workbench-kpis{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}",
            ".sales-planning .delivery-workbench-kpi{min-width:150px;border:1px solid var(--border-color);border-radius:8px;padding:12px;display:flex;flex-direction:column}",
            ".sales-planning .delivery-workbench-kpi strong{font-size:20px}",
            ".sales-planning .delivery-workbench-table-wrapper{position:relative;overflow:auto;max-height:65vh;border:1px solid var(--border-color);border-radius:8px;margin-top:12px;background:var(--card-bg);scrollbar-width:thin}",
            ".sales-planning table.planning-table{table-layout:fixed;width:100%;min-width:1829px;margin:0;font-size:12px;line-height:1.4;border-collapse:separate;border-spacing:0;background:var(--card-bg);color:var(--text-color)}",
            ".sales-planning .planning-table thead{position:sticky;top:0;z-index:3;background:var(--card-bg)}",
            ".sales-planning .planning-table thead th{background:var(--card-bg);white-space:nowrap;border:0;border-bottom:1px solid var(--border-color);padding:10px 8px;vertical-align:middle;text-align:left;font-weight:500}",
            ".sales-planning .planning-sort{display:inline-flex;align-items:center;gap:4px;border:0;background:transparent;color:inherit;text-align:left;padding:0;cursor:pointer;max-width:100%;font:inherit;font-weight:500;white-space:nowrap}",
            ".sales-planning .planning-sort:hover{color:var(--text-color);text-decoration:underline}",
            ".sales-planning .planning-sort:focus-visible{outline:2px solid var(--primary);outline-offset:2px}",
            ".sales-planning .planning-sort-indicator{font-size:10px;font-weight:400;color:var(--text-muted);flex:none}",
            ".sales-planning .planning-table thead .planning-filter-row th{padding:6px 7px 8px;background:var(--subtle-fg);border-bottom:1px solid var(--border-color)}",
            ".sales-planning .planning-table thead input.planning-column-filter{display:block;box-sizing:border-box;min-width:0;width:100%;font-size:12px;height:30px;padding:5px 8px;border:1px solid var(--border-color);border-radius:7px;background:var(--card-bg);color:var(--text-color);box-shadow:none}",
            ".sales-planning .planning-column-filter::placeholder{color:var(--text-muted);opacity:1}",
            ".sales-planning .planning-table input:focus{outline:0;border-color:var(--primary);box-shadow:0 0 0 1px var(--primary)}",
            ".sales-planning .planning-table tbody tr.planning-filtered-out{display:none}",
            ".sales-planning .planning-table tbody td{height:38px;vertical-align:middle;padding:6px 8px;border:0;border-bottom:1px solid var(--border-color);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;background:transparent}",
            ".sales-planning .planning-table tbody tr:last-child td{border-bottom:0}",
            ".sales-planning .planning-table tbody tr:hover{background:var(--subtle-fg)}",
            ".sales-planning .planning-table tbody td.planning-status{white-space:normal;overflow-wrap:anywhere;line-height:1.4}",
            ".sales-planning .planning-status .text-muted{font-size:11px}",
            ".sales-planning .planning-status button{margin-top:4px}",
            ".sales-planning .planning-table tbody input:not([type=checkbox]){display:block;box-sizing:border-box;width:100%;min-width:0;height:30px;padding:4px 7px;border:1px solid var(--border-color);border-radius:6px;background:var(--card-bg);color:var(--text-color);font:inherit}",
            ".sales-planning .planning-table tbody input[type=number]{text-align:right}",
            ".sales-planning .planning-table input:disabled{opacity:.6;cursor:not-allowed;background:var(--subtle-fg)}",
            ".sales-planning .planning-table .number-cell{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}",
            ".sales-planning .planning-table .check-col{width:36px;text-align:center;padding-left:6px;padding-right:6px}",
            ".sales-planning .planning-table .check-col input{margin:0;vertical-align:middle}",
            ".sales-planning .planning-filter-row [data-action=clear-filters]{background:transparent;border:0;font-size:16px;line-height:1;padding:3px 6px;color:var(--text-muted)}",
            ".sales-planning .overdue-date{color:var(--text-on-red);background:var(--red-100);padding:2px 5px;border-radius:4px}"
        ].join(" "));
    }

    async refresh(reset=false, force=false) {
        if (this.busy) return;
        if (this.dirty && !force) {
            return frappe.confirm(__("Discard unsaved planning edits and refresh?"), () => { this.dirty = false; this.refresh(reset, true); });
        }
        if (reset) this.start = 0;
        const args = Object.fromEntries(Object.entries(this.filters).map(([key,control]) => [key,control.get_value()]));
        args.start = this.start;
        if (!args.company || !args.delivery_date) return;
        const sequence = ++this.sequence;
        this.busy = true;
        try {
            const r = await frappe.call({method:"qcmc_logic.api.delivery_sales_planning.get_rows", args, freeze:true});
            if (r.exc || sequence !== this.sequence) return;
            this.rows = r.message.rows || [];
            this.has_more = !!r.message.has_more;
            this.loaded = true;
            this.dirty = false;
            this.render();
        } finally { this.busy = false; }
    }

    esc(v) {return frappe.utils.escape_html(String(v == null ? "" : v));}
    qty(v) {return format_number(flt(v));}
    render() {
        const esc = v => this.esc(v);
        const today = frappe.datetime.get_today();
        const kpis = [
            [__("Pending Orders (page)"), new Set(this.rows.map(r=>r.sales_order)).size],
            [__("Overdue Lines"), this.rows.filter(r=>r.overdue).length],
            [__("For Planning"), this.rows.filter(r=>r.can_edit).length],
            [__("Endorsed"), this.rows.filter(r=>r.status==="Endorsed").length]
        ];
        this.kpisEl.html(kpis.map(pair => '<div class="delivery-workbench-kpi"><strong>'+esc(pair[1])+'</strong><span class="small text-muted">'+esc(pair[0])+'</span></div>').join(""));
        this.summaryEl.text(__("Showing open demand, including overdue schedules. Save Schedule keeps the row with Sales; Endorse Selected releases it to Logistics. Only explicit endorsement releases demand."));
        this.theadEl.html('<tr><th class="check-col"><input type="checkbox" data-action="select-all" title="'+esc(__("Select visible rows"))+'"></th>'+this.columns.map(([key,label])=>'<th aria-sort="none"><button type="button" class="planning-sort" data-sort="'+esc(key)+'">'+esc(__(label))+'<span class="planning-sort-indicator" aria-hidden="true"></span></button></th>').join("")+'</tr>'+
            '<tr class="planning-filter-row"><th class="check-col"><button type="button" class="btn btn-xs btn-default" data-action="clear-filters" title="'+esc(__("Clear column filters"))+'" aria-label="'+esc(__("Clear column filters"))+'">×</button></th>'+this.columns.map(([key,label])=>'<th><input class="planning-column-filter" type="text" data-filter="'+esc(key)+'" aria-label="'+esc(__("Filter {0}",[__(label)]))+'" placeholder="'+esc(__("Filter"))+'" value="'+esc(this.column_filters[key]||"")+'"></th>').join("")+'</tr>');
        this.tbodyEl.html(this.rows.map((r,i)=>{
            const editable = !!r.can_edit, disabled = editable ? "" : " disabled";
            const date = r.delivery_date && r.delivery_date > today ? r.delivery_date : today;
            const dateClass = r.overdue ? ' class="overdue-date"' : "";
            const soLink = '<a href="/desk/sales-order/'+encodeURIComponent(r.sales_order)+'">'+esc(r.sales_order)+'</a>';
            const itemLink = '<a href="/desk/item/'+encodeURIComponent(r.item_code)+'">'+esc(r.item_code)+'</a>';
            const scheduleLink = r.name.startsWith("unscheduled:") ? esc(r.delivery_date) :
                '<a href="/desk/so-delivery-schedule/'+encodeURIComponent(r.name)+'">'+esc(r.delivery_date)+'</a>';
            const action = r.status==="Endorsed" && !r.has_dn_history ?
                '<button class="btn btn-xs btn-default" data-action="withdraw">'+esc(__("Withdraw"))+'</button>' :
                r.can_replace ? '<button class="btn btn-xs btn-default" data-action="replace">'+esc(__("Authorize Replacement"))+'</button>' : "";
            return '<tr data-index="'+i+'"><td class="check-col"><input type="checkbox" data-field="selected"'+disabled+'></td>'+
                '<td title="'+esc(r.customer_name||r.customer)+'">'+esc(r.customer_name||r.customer)+'</td><td title="'+esc(r.sales_order)+'">'+soLink+'</td><td title="'+esc([r.item_code,r.item_name].filter(Boolean).join(" — "))+'">'+itemLink+'</td><td title="'+esc(r.warehouse)+'">'+esc(r.warehouse)+'</td>'+
                '<td>'+esc(r.original_promise_date||r.delivery_date)+'</td><td><span'+dateClass+'>'+scheduleLink+'</span></td>'+
                '<td class="number-cell">'+esc(this.qty(r.ordered_qty))+'</td><td class="number-cell">'+esc(this.qty(r.delivered_qty))+'</td>'+
                '<td class="number-cell">'+esc(this.qty(r.available_qty))+' '+esc(r.uom)+'</td>'+
                '<td><input type="date" data-field="delivery_date" value="'+esc(date)+'" min="'+esc(today)+'"'+disabled+'></td>'+
                '<td><input type="number" data-field="quantity" min="0" step="any" max="'+esc(r.available_qty)+'" value="'+esc(r.available_qty)+'"'+disabled+'></td>'+
                '<td><input type="text" maxlength="1000" data-field="remarks" value="'+esc(r.sales_remarks||"")+'"'+disabled+'></td>'+
                '<td class="planning-status">'+esc(__(r.status))+'<div class="small text-muted">'+esc(r.return_reason||r.blocked_reason||"")+'</div>'+action+'</td></tr>';
        }).join("") || '<tr><td colspan="14" class="text-muted text-center">'+esc(__("No matching open schedules on this page."))+'</td></tr>');
        this.apply_table_view();
        this.paginationEl.html('<button class="btn btn-sm btn-default" data-page="prev"'+(this.start===0?' disabled':'')+'>'+esc(__("Previous"))+'</button> <span class="text-muted small">'+esc(__("SO page {0}",[Math.floor(this.start/50)+1]))+'</span> <button class="btn btn-sm btn-default" data-page="next"'+(!this.has_more?' disabled':'')+'>'+esc(__("Next"))+'</button>');
    }

    column_value(key, row, element) {
        const input = field => element.querySelector('[data-field="'+field+'"]')?.value ?? "";
        if (key==="deliver_on") return input("delivery_date");
        if (key==="quantity") return input("quantity");
        if (key==="sales_remarks") return input("remarks");
        if (key==="customer_name") return row.customer_name||row.customer||"";
        if (key==="original_promise_date") return row.original_promise_date||row.delivery_date||"";
        if (key==="item_code") return [row.item_code,row.item_name].filter(Boolean).join(" ");
        if (key==="status") return [__(row.status),row.return_reason,row.blocked_reason].filter(Boolean).join(" ");
        return row[key] ?? "";
    }

    apply_table_view() {
        const body = this.tbodyEl[0];
        const entries = Array.from(body.querySelectorAll("tr[data-index]")).map(element=>{
            const index=Number(element.dataset.index), row=this.rows[index];
            const values=Object.fromEntries(this.columns.map(([key])=>[key,this.column_value(key,row,element)]));
            const match=this.columns.every(([key,,kind])=>{
                const query=String(this.column_filters[key]||"").trim().toLowerCase();
                if (!query) return true;
                const raw=String(values[key]).toLowerCase();
                if (kind==="number") return raw.includes(query.replace(/,/g,"")) || this.qty(values[key]).toLowerCase().includes(query);
                return raw.includes(query);
            });
            element.classList.toggle("planning-filtered-out",!match);
            return {element,index,values};
        });
        if(this.sort_column) {
            const key=this.sort_column, direction=this.sort_direction;
            const numeric=this.columns.some(([name,,kind])=>name===key&&kind==="number");
            entries.sort((a,b)=>{
                const av=a.values[key], bv=b.values[key];
                const result=numeric ? Number(av||0)-Number(bv||0) : String(av).localeCompare(String(bv),undefined,{numeric:true,sensitivity:"base"});
                return result ? direction*result : a.index-b.index;
            });
        } else entries.sort((a,b)=>a.index-b.index);
        // Move existing nodes rather than render inputs again: values and selection remain intact.
        const order=Array.from(body.querySelectorAll("tr[data-index]"));
        if(entries.some((entry,i)=>entry.element!==order[i])) entries.forEach(entry=>body.appendChild(entry.element));
        this.theadEl.find("[data-sort]").each((_,button)=>{
            const active=button.dataset.sort===this.sort_column;
            const indicator=button.querySelector(".planning-sort-indicator");
            indicator.textContent=active?(this.sort_direction===1?"▲":"▼"):"↕";
            button.closest("th").setAttribute("aria-sort",active?(this.sort_direction===1?"ascending":"descending"):"none");
        });
        this.update_selection_summary();
    }

    update_selection_summary() {
        const total=this.tbodyEl.find("tr[data-index]").length;
        const visible=this.tbodyEl.find("tr[data-index]:not(.planning-filtered-out)").length;
        const selectable=this.tbodyEl.find('tr[data-index]:not(.planning-filtered-out) [data-field="selected"]:enabled');
        const selected=selectable.filter(":checked").length;
        const hidden=this.tbodyEl.find('tr.planning-filtered-out [data-field="selected"]:checked').length;
        this.theadEl.find('[data-action="select-all"]').prop("checked",selectable.length>0&&selected===selectable.length).prop("indeterminate",selected>0&&selected<selectable.length).prop("disabled",!selectable.length);
        this.summaryEl.text(__("Showing {0} of {1} schedule rows on this page. Selected: {2}. Save Schedule keeps rows with Sales; Endorse Selected releases them to Logistics.",[visible,total,selected])+(hidden?" "+__("Hidden selected rows: {0}. Clear filters before saving or endorsing.",[hidden]):""));
    }

    bind_events() {
        this.theadEl.on("change", '[data-action="select-all"]',e=>{
            this.tbodyEl.find('tr[data-index]:not(.planning-filtered-out) [data-field="selected"]:enabled').prop("checked", e.currentTarget.checked);
            this.update_selection_summary();
        });
        this.theadEl.on("input", "[data-filter]", e=>{
            this.column_filters[e.currentTarget.dataset.filter] = e.currentTarget.value;
            this.apply_table_view();
        });
        this.theadEl.on("click", "[data-sort]", e=>{
            const key=e.currentTarget.dataset.sort;
            this.sort_direction=this.sort_column===key?-this.sort_direction:1;
            this.sort_column=key;
            this.apply_table_view();
        });
        this.theadEl.on("click", '[data-action="clear-filters"]',()=>{
            this.column_filters={};
            this.theadEl.find("[data-filter]").val("");
            this.apply_table_view();
        });
        this.tbodyEl.on("change", '[data-field="selected"]',()=>this.update_selection_summary());
        this.tbodyEl.on("input change", "input:not([type=checkbox])", e=>{
            const tr=jQuery(e.currentTarget).closest("tr");
            tr.find('[data-field="selected"]:enabled').prop("checked",true);
            this.dirty=true;
            this.update_selection_summary();
        });
        this.tbodyEl.on("change", "input:not([type=checkbox])", ()=>this.apply_table_view());
        this.tbodyEl.on("click", '[data-action="withdraw"],[data-action="replace"]',e=>{
            const r=this.rows[Number(jQuery(e.currentTarget).closest("tr").attr("data-index"))];
            if (!r || this.dirty || this.busy) return frappe.msgprint(__("Save or discard current edits first."));
            const replace=e.currentTarget.dataset.action==="replace";
            const fields=[{fieldname:"reason",label:__("Reason"),fieldtype:"Small Text",reqd:1}];
            if (replace) fields.unshift({fieldname:"delivery_date",label:__("New Delivery Date"),fieldtype:"Date",reqd:1,default:frappe.datetime.get_today()});
            const dialog=new frappe.ui.Dialog({title:replace?__("Authorize Replacement"):__("Withdraw Endorsement"), fields,
                primary_action_label:__("Confirm"), primary_action:async values=>{
                    const method=replace?"qcmc_logic.api.delivery_schedule_collaboration_v2.authorize_cancelled_schedule_replacement":"qcmc_logic.api.delivery_sales_planning.withdraw";
                    const args={schedule:r.name,expected_modified:r.modified,reason:values.reason};
                    if(replace) args.delivery_date=values.delivery_date;
                    const result=await frappe.call({method,args,freeze:true});
                    if (!result.exc) {dialog.hide(); await this.refresh(false,true);}
                }});
            dialog.show();
        });
        this.paginationEl.on("click", "button", e=>{
            const next=Math.max(0,this.start+(e.currentTarget.dataset.page==="next"?50:-50));
            const go=()=>{this.start=next;this.dirty=false;this.refresh(false,true);};
            if(this.dirty) frappe.confirm(__("Discard unsaved edits?"),go); else go();
        });
    }

    async save(endorse) {
        if (this.busy) return;
        const rows=[];
        if(this.tbodyEl.find('tr.planning-filtered-out [data-field="selected"]:checked').length) {
            return frappe.msgprint(__("Some selected rows are hidden by column filters. Clear the filters and review the selection before saving or endorsing."));
        }
        let invalid=false;
        this.tbodyEl.find("tr[data-index]").each((_,element)=>{
            const tr=jQuery(element), r=this.rows[Number(tr.attr("data-index"))];
            if(!r.can_edit||!tr.find('[data-field="selected"]').prop("checked"))return;
            const value=field=>tr.find('[data-field="'+field+'"]').val();
            const quantity=Number(value("quantity")), delivery_date=value("delivery_date");
            if(!Number.isFinite(quantity)||quantity<=0||quantity>Number(r.available_qty)||!delivery_date||delivery_date<frappe.datetime.get_today()){invalid=true;return;}
            rows.push({schedule:r.name,modified:r.modified,expected_planned_qty:r.expected_planned_qty,quantity,delivery_date,remarks:value("remarks")});
        });
        if(invalid)return frappe.msgprint(__("Enter a valid operational date and positive quantity within the open balance."));
        if(!rows.length)return frappe.msgprint(__("Select at least one editable row."));
        const run=async()=>{
            this.busy=true;
            try {
                const result=await frappe.call({method:"qcmc_logic.api.delivery_sales_planning.save_rows",args:{rows,endorse:endorse?1:0},freeze:true});
                if(result.exc)return;
                frappe.show_alert({message:endorse?__("Selected schedules endorsed to Logistics"):__("Selected schedules saved"),indicator:"green"});
                this.dirty=false;
            } finally {this.busy=false;}
            if(!this.dirty) await this.refresh(false,true);
        };
        if(endorse) frappe.confirm(__("Endorse {0} selected schedule(s) to Logistics?",[rows.length]),run);else await run();
    }
}