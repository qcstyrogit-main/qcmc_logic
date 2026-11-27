// Paginated calculation result viewer. No editable child grid or client-side approval bypass.
frappe.ui.form.on("Reorder Calculation Batch",{
    refresh(frm) {
        frm.disable_save();
        if(frm.is_new() || frappe.session.user!=="Administrator") return;
        const field=frm.fields_dict.results_table;
        if(!field) return;
        const root=field.$wrapper.empty().addClass("qrb-view");
        $("<style>").text(`
            .qrb-view {font-size:13px}
            .qrb-view .qrb-toolbar {display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:12px}
            .qrb-view .qrb-toolbar > * {margin-right:0!important}
            .qrb-view .qrb-toolbar input,.qrb-view .qrb-toolbar select {height:34px}
            .qrb-view .qrb-shell {border:1px solid var(--border-color);border-radius:10px;overflow-x:auto}
            .qrb-view .qrb-table {width:100%;min-width:920px;border-collapse:separate;border-spacing:0;table-layout:auto;margin:0}
            .qrb-view .qrb-table th {background:var(--subtle-fg);font-size:12px;font-weight:600;color:var(--text-muted);text-align:left;padding:12px 14px;white-space:nowrap;border-bottom:1px solid var(--border-color)}
            .qrb-view .qrb-table td {padding:15px 14px;vertical-align:middle;border-bottom:1px solid var(--border-color);background:var(--card-bg,var(--fg-color))}
            .qrb-view .qrb-table tr:last-child td {border-bottom:0}
            .qrb-view .qrb-table tr:hover td,.qrb-view .qrb-table tr.qrb-selected td {background:var(--control-bg)}
            .qrb-view .qrb-check {width:36px;text-align:center!important;padding-left:12px!important;padding-right:4px!important}
            .qrb-view .qrb-check input {width:16px;height:16px;accent-color:var(--primary-color,#2563eb);cursor:pointer;vertical-align:middle}
            .qrb-view .qrb-item {white-space:nowrap;font-weight:600}
            .qrb-view .qrb-status-cell {min-width:152px}
            .qrb-view .qrb-status {display:inline-flex;align-items:center;gap:6px;white-space:nowrap;font-size:11px;font-weight:600;padding:5px 9px;border-radius:20px;line-height:1.4}
            .qrb-view .qrb-status:before {content:"";width:6px;height:6px;border-radius:50%;background:currentColor;flex-shrink:0}
            .qrb-view .qrb-pending {background:var(--orange-100,#fff1dd);color:var(--orange-800,#9a4700)}
            .qrb-view .qrb-approved {background:var(--green-100,#e1f5e8);color:var(--green-800,#166534)}
            .qrb-view .qrb-failed {background:var(--red-100,#fee2e2);color:var(--red-800,#991b1b)}
            .qrb-view .qrb-neutral {background:var(--control-bg);color:var(--text-muted)}
            .qrb-view .qrb-number {min-width:156px;font-variant-numeric:tabular-nums}
            .qrb-view .qrb-old {font-size:11px;color:var(--text-muted);white-space:nowrap}
            .qrb-view .qrb-new {font-size:15px;font-weight:650;line-height:1.6;color:var(--text-color);white-space:nowrap}
            .qrb-view .qrb-delta {font-size:11px;font-weight:500;white-space:nowrap}
            .qrb-view .qrb-up {color:var(--orange-600,#b45309)}
            .qrb-view .qrb-down {color:var(--red-600,#b91c1c)}
            .qrb-view .qrb-stock {min-width:118px;font-variant-numeric:tabular-nums}
            .qrb-view .qrb-reason {min-width:200px;max-width:340px;font-size:12px;line-height:1.6;color:var(--text-muted)}
            .qrb-view .qrb-footer {display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;padding:12px 0}
            .qrb-view .qrb-actions,.qrb-view .qrb-pages {display:flex;align-items:center;gap:8px;flex-wrap:wrap}
            .qrb-view .qrb-actions .btn,.qrb-view .qrb-pages .btn {margin-right:0!important}
            .qrb-view .qrb-note {font-size:12px;color:var(--text-muted);line-height:1.6;margin-bottom:12px}
        `).appendTo(root);
        let offset=0, limit=50, serial=0, busy=false;
        const selected=new Set();
        const tools=$("<div>").addClass("qrb-toolbar").appendTo(root);
        const search=$("<input>").attr({type:"search",placeholder:__("Search item code"),"aria-label":__("Search item code")}).addClass("form-control input-sm mr-2").css({width:"180px"}).appendTo(tools);
        const filter=$("<select>").attr("aria-label",__("Status filter")).addClass("form-control input-sm mr-2").css({width:"180px"}).appendTo(tools);
        for(const s of ["","Pending Approval","New Configuration","Unchanged","Approved","Reverted","Review Required","Failed","Skipped","Make to Order"]) $("<option>").val(s).text(s||__("All statuses")).appendTo(filter);
        const size=$("<select>").attr("aria-label",__("Rows per page")).addClass("form-control input-sm mr-2").css({width:"75px"}).appendTo(tools);
        for(const n of [25,50,100]) $("<option>").val(n).text(n).appendTo(size);
        size.val(50);
        const button=(parent,label,action,primary=false)=>$("<button>").attr("type","button").addClass("btn btn-sm "+(primary?"btn-primary":"btn-default")+" mr-2").text(label).appendTo(parent).on("click",action);
        const refresh=button(tools,__("Refresh"),()=>frm.reload_doc());
        const note=$("<p>").addClass("qrb-note").text(__("Review proposed values before applying them. Approval checks current stock, demand and policy; no Material Requests are created.")).appendTo(root);
        const body=$("<div>").addClass("qrb-shell").appendTo(root);
        const footer=$("<div>").addClass("qrb-footer").appendTo(root);
        const pages=$("<div>").addClass("qrb-pages").appendTo(footer);
        const prev=button(pages,__("Previous"),()=>{offset=Math.max(0,offset-limit);load();});
        const pageLabel=$("<span>").addClass("text-muted").appendTo(pages);
        const next=button(pages,__("Next"),()=>{offset+=limit;load();});
        const actions=$("<div>").addClass("qrb-actions").appendTo(footer);
        const summary=$("<span>").addClass("text-muted").attr("aria-live","polite").appendTo(actions);
        const approve=button(actions,__("Approve Selected"),()=>{
            if(!selected.size||busy) return;
            const ids=[...selected];
            frappe.confirm(__("Approve {0} selected recommendations and update Item Reorder? Each item is checked separately.",[ids.length]),async()=>{
                if(busy) return;
                busy=true; approve.prop("disabled",true);
                try {
                    const res=await frappe.call({method:"qcmc_logic.dynamic_reorder_batch.approve",type:"POST",args:{batch:frm.doc.name,items:JSON.stringify(ids)},freeze:true});
                    const results=res.message||[];
                    const report=$("<div>");
                    $("<p>").text(__("Approved: {0} / Selected: {1}",[results.filter(x=>x.status==="Approved").length,ids.length])).appendTo(report);
                    for(const r of results.filter(x=>x.status!=="Approved")) $("<p>").text(r.item+": "+r.reason).appendTo(report);
                    frappe.msgprint({title:__("Approval results"),message:report.html()});
                    selected.clear();
                    await frm.reload_doc();
                } finally {busy=false;updateSelection();}
            });
        },true);
        function updateSelection(){
            summary.text(__("{0} selected (maximum 50)",[selected.size]));
            approve.prop("disabled",busy||!selected.size);
        }
        async function load(){
            const request=++serial;
            selected.clear();updateSelection();
            prev.prop("disabled",true);next.prop("disabled",true);
            body.empty().append($("<p>").text(__("Loading results...")));
            try{
                const res=await frappe.call({method:"qcmc_logic.dynamic_reorder_batch.page",type:"GET",args:{batch:frm.doc.name,offset,limit,status:filter.val(),search:search.val()}});
                if(request!==serial) return;
                const d=res.message;
                body.empty();
                if(!d.rows.length){
                    $("<p>").addClass("text-muted").text(["Queued","Running"].includes(d.status)?__("Calculation is queued or processing. Use Refresh to check progress."):__("No results match the filters.")).appendTo(body);
                } else {
                    const table=$("<table>").addClass("qrb-table").appendTo(body);
                    const head=$("<thead>").appendTo(table);
                    const tr=$("<tr>").appendTo(head);
                    const selectAll=$("<input>").attr({type:"checkbox","aria-label":__("Select eligible rows on this page")}).appendTo($("<th>").addClass("qrb-check").appendTo(tr));
                    for(const label of ["Item Code","Status","Reorder Level (ROL)","Reorder Qty (ROQ)","Projected Stock","Reason / Audit"]) $("<th>").text(__(label)).appendTo(tr);
                    const tbody=$("<tbody>").appendTo(table);
                    const choices=[];
                    const fmt=v=>v==null?"—":Number(v).toLocaleString("en-US",{maximumFractionDigits:3});
                    function comparison(line,oldValue,newValue,status){
                        const cell=$("<td>").addClass("qrb-number").appendTo(line);
                        if(["Failed","Skipped","Make to Order","Review Required"].includes(status)){
                            $("<div>").addClass("qrb-old").text(__("Previous")+": "+fmt(oldValue)).appendTo(cell);
                            $("<div>").addClass("qrb-new").text("—").appendTo(cell);
                            return;
                        }
                        const old=Number(oldValue), next=Number(newValue);
                        $("<div>").addClass("qrb-old").text(__("Previous")+": "+fmt(oldValue)).appendTo(cell);
                        const value=$("<div>").addClass("qrb-new").appendTo(cell);
                        $("<span>").text(fmt(newValue)).appendTo(value);
                        if(newValue!=null&&oldValue!=null&&next!==old){
                            const delta=next-old;
                            const pct=old?(" ("+(delta>0?"+":"")+(delta/old*100).toFixed(1)+"%)"):"";
                            $("<span>").addClass("qrb-delta "+(delta>0?"qrb-up":"qrb-down")).text((delta>0?"+":"")+fmt(delta)+pct).appendTo(cell);
                        }
                    }
                    for(const r of d.rows){
                        const line=$("<tr>").appendTo(tbody);
                        const eligible=["Pending Approval","New Configuration"].includes(r.status);
                        const box=$("<input>").attr({type:"checkbox","aria-label":__("Select {0}",[r.item_code])}).prop("disabled",!eligible).appendTo($("<td>").addClass("qrb-check").appendTo(line));
                        if(eligible) choices.push([r.name,box]);
                        box.on("change",()=>{if(box.prop("checked")&&selected.size>=50){box.prop("checked",false);return;} if(box.prop("checked")) selected.add(r.name);else selected.delete(r.name);line.toggleClass("qrb-selected",box.prop("checked"));updateSelection();});
                        const item=$("<td>").addClass("qrb-item").appendTo(line);
                        $("<a>").attr("href","#").text(r.item_code).appendTo(item).on("click",e=>{e.preventDefault();frappe.set_route("Form","Item",r.item_code);});
                        const colors={"Pending Approval":"pending","New Configuration":"pending","Approved":"approved","Failed":"failed","Review Required":"pending","Reverted":"neutral"};
                        $("<span>").addClass("qrb-status qrb-"+(colors[r.status]||"neutral")).text(r.status).appendTo($("<td>").addClass("qrb-status-cell").appendTo(line));
                        comparison(line,r.previous_level,r.recommended_level,r.status);
                        comparison(line,r.previous_qty,r.recommended_qty,r.status);
                        const stock=$("<td>").addClass("qrb-stock").appendTo(line);
                        $("<div>").addClass("qrb-new").text(fmt(r.projected_qty)).appendTo(stock);
                        if(eligible&&r.projected_qty!=null&&r.recommended_level!=null&&Number(r.projected_qty)<Number(r.recommended_level))
                            $("<span>").addClass("qrb-delta qrb-down").text(__("Below proposed ROL")).appendTo(stock);
                        const audit=$("<td>").addClass("qrb-reason").appendTo(line);
                        $("<div>").text(r.reason||"—").appendTo(audit);
                        if(r.approval_history) $("<button>").attr("type","button").addClass("btn btn-link btn-xs").text(__("View audit")).appendTo(audit).on("click",()=>frappe.set_route("Form","Reorder Calculation History",r.approval_history));
                    }
                    selectAll.on("change",()=>{selected.clear();for(const [id,box] of choices){const checked=selectAll.prop("checked")&&selected.size<50;box.prop("checked",checked);box.closest("tr").toggleClass("qrb-selected",checked);if(checked) selected.add(id);}updateSelection();});
                }
                pageLabel.text(__("{0}–{1} of {2}",[d.total?offset+1:0,Math.min(offset+limit,d.total),d.total]));
                prev.prop("disabled",offset===0);next.prop("disabled",offset+limit>=d.total);
            }catch(e){if(request===serial)body.empty().append($("<p>").text(__("Unable to load calculation results. Refresh to retry.")));}
        }
        search.on("change",()=>{offset=0;load();});
        filter.on("change",()=>{offset=0;load();});
        size.on("change",()=>{limit=Number(size.val());offset=0;load();});
        updateSelection();load();
    }
});
