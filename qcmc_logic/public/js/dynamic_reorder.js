// Reorder Management V2: explicit manual approvals and draft-only replenishment.
function qcmc_run_replenishment(frm, mapping) {
    if (frm.is_dirty()) {
        frappe.msgprint(__("Save your changes before running replenishment."));
        return;
    }
    const scope = mapping ? __("this mapping") : __("all enabled mappings");
    frappe.confirm(__("Check {0} now and create draft Material Requests for eligible approved items? This does not submit requests.",[scope]), async () => {
        const response = await frappe.call({
            method:"qcmc_logic.dynamic_reorder_replenishment.run_now",
            type:"POST",args:mapping ? {mapping} : {},
            freeze:true,freeze_message:__("Checking replenishment requirements...")
        });
        const result = response.message || {};
        const content = $("<div>");
        const descriptions = {
            "Disabled":__("Enable Reorder Settings, turn off Preview Only, select Manual Draft or Automatic Draft, and keep native automatic reorder disabled."),
            "Already Running":__("Another replenishment execution is in progress."),
            "Not Installed":__("Replenishment metadata is not installed. Run site migration.")
        };
        $("<p>").text(descriptions[result.status] || result.status || __("Unknown result")).appendTo(content);
        if (result.execution) {
            const table=$("<table>").addClass("table table-bordered").appendTo(content);
            for (const [label,key] of [[__("Checked"),"checked"],[__("Created"),"created"],[__("Skipped"),"skipped"],[__("Failed"),"failed"]]) {
                const row=$("<tr>").appendTo(table);
                $("<th>").text(label).appendTo(row);
                $("<td>").text(result[key] ?? 0).appendTo(row);
            }
            const dialog = new frappe.ui.Dialog({title:__("Replenishment Execution"),fields:[{fieldtype:"HTML",fieldname:"summary"}],
                primary_action_label:__("View Execution History"),primary_action:()=>{
                    dialog.hide();
                    frappe.set_route("Form","Replenishment Execution History",result.execution);
                }});
            dialog.fields_dict.summary.$wrapper.append(content);
            dialog.show();
        } else {
            frappe.msgprint({title:__("Replenishment Execution"),message:content.html()});
        }
    });
}
async function qcmc_reorder_overview(frm) {
    const field=frm.fields_dict.operational_overview;
    if (!field) return;
    const root=field.$wrapper.empty();
    $("<p>").addClass("text-muted").text(__("Loading saved configuration and operational counts...")).appendTo(root);
    try {
        const {message:d}=await frappe.call({method:"qcmc_logic.dynamic_reorder_dashboard.overview",type:"GET"});
        if (frappe.get_route()[1]!=="Reorder Settings") return;
        root.empty();
        const header=$("<div>").addClass("d-flex justify-content-between align-items-center mb-3").appendTo(root);
        $("<h4>").text(__("Inventory planning overview")).appendTo(header);
        $("<button>").attr("type","button").addClass("btn btn-default btn-sm").text(__("Refresh")).appendTo(header).on("click",()=>qcmc_reorder_overview(frm));
        const cards=$("<div>").addClass("row").appendTo(root);
        for (const [label,value,route] of [
            [__("Approved item / mapping pairs"),d.managed,["List","Reorder Calculation History",{status:"Approved"}]],
            [__("Batch items awaiting review"),d.pending,["List","Reorder Calculation Batch",{status:"Pending Review"}]],
            [__("Draft replenishment requests"),d.drafts,["List","Material Request",{docstatus:0,custom_replenishment_mapping:["is","set"]}]],
            [__("Active warehouse mappings"),d.active_mappings,["List","Reorder Policy Mapping",{enabled:1}]]
        ]) {
            const card=$("<div>").addClass("col-sm-6 col-lg-3 mb-3").appendTo(cards);
            const button=$("<button>").attr("type","button").addClass("btn btn-default text-left w-100 border p-3").appendTo(card).on("click",()=>frappe.set_route(...route));
            $("<div>").addClass("text-muted small").text(label).appendTo(button);
            $("<div>").addClass("h3 mb-0").text(value).appendTo(button);
        }
        $("<p>").addClass("text-muted small").text(__("Counts are saved configuration and records, not a live stock shortage count. Open Replenishment Monitoring to see current stock.")).appendTo(root);
        const status=$("<div>").addClass("border rounded p-3 mb-3").appendTo(root);
        $("<strong>").text(__("Replenishment status")).appendTo(status);
        $("<p>").addClass("mb-1").text(d.automatic_ready?__("Automatic draft generation configured; scheduler runs every 15 minutes."):d.manual_ready?__("Manual draft generation available. Automatic generation is not configured."):__("Request generation blocked by current settings.")).appendTo(status);
        $("<p>").addClass("mb-1").text(__("Native automatic reorder: {0}",[d.native_enabled?__("Enabled — custom requests blocked"):__("Disabled")])).appendTo(status);
        $("<p>").addClass("mb-1").text(__("Last execution: {0}",[d.last_execution?d.last_execution.status+" / "+frappe.datetime.str_to_user(d.last_execution.started_at):__("Not recorded")])).appendTo(status);
        $("<small>").addClass("text-muted").text(__("Configured status is not a scheduler heartbeat.")).appendTo(status);
        $("<h5>").text(__("Getting started")).appendTo(root);
        const steps=[
            [d.enabled,__("Enable Reorder Settings"),__("Enable this feature and choose simulation or request mode."),()=>frm.scroll_to_field("enabled")],
            [d.policies>0,__("Create a reorder policy"),__("Choose demand history and stock coverage."),()=>frappe.set_route("List","Reorder Policy")],
            [d.active_mappings>0,__("Map warehouses"),__("Choose combined warehouses and a replenishment destination."),()=>frappe.set_route("List","Reorder Policy Mapping")],
            [d.managed>0,__("Calculate and approve"),__("Open Reorder Analysis from your mapping, save the calculation and approve it."),()=>frappe.set_route("List","Reorder Policy Mapping")],
            [d.manual_ready,__("Enable request generation"),__("Turn off simulation and choose Manual Draft or Automatic Draft. Native auto reorder must be off."),()=>frm.scroll_to_field("replenishment_mode")]
        ];
        for(const [done,label,description,action] of steps) {
            const line=$("<div>").addClass("d-flex align-items-start justify-content-between border-bottom py-2").appendTo(root);
            const left=$("<div>").appendTo(line);
            $("<strong>").text((done?"✓ ":"○ ")+label).appendTo(left);
            $("<div>").addClass("small text-muted").text(description).appendTo(left);
            $("<button>").attr("type","button").addClass("btn btn-default btn-xs ml-2").text(done?__("Review"):__("Open")).appendTo(line).on("click",action);
        }
    } catch(e) {
        root.empty().append($("<p>").addClass("text-muted").text(__("Overview unavailable. Check migration and access, then refresh.")));
    }
}
frappe.ui.form.on("Reorder Settings", {
    refresh(frm) {
        if (frappe.session.user !== "Administrator") return;
        qcmc_reorder_overview(frm);
        frm.add_custom_button(__("Run Replenishment Now"), () => qcmc_run_replenishment(frm));
        frm.add_custom_button(__("Replenishment Execution History"), () => frappe.set_route("List","Replenishment Execution History"));
        frm.add_custom_button(__("Preview Recommendations"), () => {
            const d = new frappe.ui.Dialog({
                title: __("Consolidated Reorder Preview"),
                fields: [
                    {fieldname:"company",fieldtype:"Link",options:"Company",label:__("Company"),reqd:1},
                    {fieldname:"mapping",fieldtype:"Link",options:"Reorder Policy Mapping",label:__("Reorder Policy Mapping"),reqd:1,
                        get_query:()=>({filters:{company:d.get_value("company"),enabled:1}})},
                    {fieldname:"item_code",fieldtype:"Link",options:"Item",label:__("Item (optional)")},
                    {fieldname:"as_of",fieldtype:"Date",label:__("Calculation Date"),default:frappe.datetime.get_today()},
                    {fieldname:"period_method",fieldtype:"Select",label:__("Demand Period Method"),options:"\nComplete Calendar Months\nRolling Days\nMonth-to-Date Inclusive",
                        description:__("Leave blank to use the policy demand period.")},
                    {fieldname:"rolling_days",fieldtype:"Int",label:__("Rolling Days"),default:90,depends_on:"eval:doc.period_method=='Rolling Days'"}
                ],
                primary_action_label:__("Save Preview"),
                async primary_action(values) {
                    const days=values.period_method === "Rolling Days" ? Number(values.rolling_days) : null;
                    if (days !== null && (!Number.isInteger(days) || days < 1 || days > 1096)) {
                        frappe.msgprint(__("Rolling Days must be between 1 and 1096."));
                        return;
                    }
                    const response=await frappe.call({method:"qcmc_logic.dynamic_reorder_batch.start",type:"POST",
                        args:{...values,rolling_days:days},freeze:true});
                    d.hide();
                    frappe.set_route("Form","Reorder Calculation Batch",response.message.batch);
                }
            });
            d.show();
        });
    }
});

frappe.ui.form.on("Reorder Policy Mapping", {
    setup(frm) {
        frm.set_query("warehouse","warehouses",()=>({filters:{company:frm.doc.company,is_group:0,disabled:0}}));
        frm.set_query("replenishment_warehouse",()=>({filters:{company:frm.doc.company,is_group:0,disabled:0,
            name:["in",(frm.doc.warehouses || []).map(row=>row.warehouse).filter(Boolean)]}}));
        frm.set_query("policy",()=>({filters:{enabled:1}}));
    },
    refresh(frm) {
        frm.dashboard.set_headline_alert(frm.doc.automatic_draft_replenishment
            ? __("Automatic draft replenishment selected. Global mode and approval safeguards must also permit execution.")
            : __("Automatic draft replenishment is disabled for this mapping."));
        if (frm.is_new()) return;
        if (frappe.session.user === "Administrator" && frm.doc.enabled) {
            frm.add_custom_button(__("Run Replenishment Now"), () => qcmc_run_replenishment(frm,frm.doc.name));
        }
        for (const report of ["Reorder Analysis","Replenishment Monitoring"]) {
            frm.add_custom_button(__(report),()=>frappe.set_route("query-report",report,{company:frm.doc.company,mapping:frm.doc.name}));
        }
    },
    async policy(frm) {
        if (!frm.doc.policy) return;
        const response=await frappe.db.get_value("Reorder Policy",frm.doc.policy,["inventory_category","inventory_type"]);
        await frm.set_value({inventory_group:response.message.inventory_category,inventory_type:response.message.inventory_type});
    },
    company(frm) {
        frm.clear_table("warehouses");
        frm.refresh_field("warehouses");
        frm.set_value("replenishment_warehouse",null);
    }
});

frappe.ui.form.on("Item Reorder Override", {
    setup(frm) {
        frm.set_query("mapping",()=>({filters:{company:frm.doc.company,enabled:1}}));
    }
});

frappe.ui.form.on("Reorder Calculation History", {
    refresh(frm) {
        if (frm.doc.mapping) {
            const messages = {
                "Approved": __("Next step: monitor current projected stock or create a draft Material Request when replenishment is needed."),
                "Pending Approval": __("Next step: review recommended ROL and ROQ, then use Approval Readiness and Approve & Apply."),
                "Preview": __("Next step: review the recommendation and approve it to update Item Reorder."),
                "New Reorder Configuration": __("Next step: review the recommendation before creating a managed Item Reorder row."),
                "Rejected": __("No reorder values were applied. Generate a fresh calculation if needed."),
                "Reverted": __("The applied reorder configuration was rolled back. Generate a fresh calculation before applying again."),
                "Skipped": __("No recommendation was applied. Review the calculation reason."),
                "Failed": __("Calculation failed. Review the reason before retrying.")
            };
            frm.dashboard.set_headline_alert(messages[frm.doc.status] || __("Review the calculation status and reason."));
        }
        if (frappe.session.user === "Administrator" && frm.doc.mapping &&
            ["Preview","Pending Approval","New Reorder Configuration"].includes(frm.doc.status)) {
            frm.add_custom_button(__("Approve & Apply"), async () => {
                const result = await frappe.call({method:"qcmc_logic.dynamic_reorder_audit.application_precheck",
                    type:"POST",args:{name:frm.doc.name},freeze:true});
                if (!result.message?.allowed) {
                    const content = $("<div>");
                    for (const check of result.message?.checks || []) $("<p>").text(check.label).appendTo(content);
                    frappe.msgprint({title:__("Approval blocked"),message:content.html()});
                    return;
                }
                frappe.confirm(__("Apply these ROL and ROQ values to the managed Item Reorder row? No Material Request will be created."), async () => {
                    await frappe.call({method:"qcmc_logic.dynamic_reorder_audit.apply",type:"POST",
                        args:{name:frm.doc.name},freeze:true});
                    await frm.reload_doc();
                });
            });
            frm.add_custom_button(__("Approval Readiness"), async () => {
                const result = await frappe.call({method:"qcmc_logic.dynamic_reorder_audit.application_precheck",
                    type:"POST",args:{name:frm.doc.name},freeze:true});
                const checks = result.message?.checks || [];
                const content = $("<div>");
                for (const check of checks) $("<p>").text(check.label).appendTo(content);
                frappe.msgprint({title:__("Approval Readiness"),message:content.html()});
            });
            frm.add_custom_button(__("Reject"), () => {
                frappe.prompt([{fieldname:"reason",fieldtype:"Small Text",label:__("Rejection Reason"),reqd:1}],
                    async values => {
                        await frappe.call({method:"qcmc_logic.dynamic_reorder_audit.reject",type:"POST",
                            args:{name:frm.doc.name,reason:values.reason},freeze:true});
                        await frm.reload_doc();
                    }, __("Reject Consolidated Preview"), __("Reject"));
            });
        }
        if (frappe.session.user === "Administrator" && frm.doc.mapping && frm.doc.status === "Approved") {
            frm.add_custom_button(__("Create Draft Material Request"), () => {
                frappe.confirm(__("Check current combined projected stock and outstanding requests? A draft will be created only if replenishment is required."), async () => {
                    const response = await frappe.call({
                        method:"qcmc_logic.dynamic_reorder_replenishment.create_draft",
                        type:"POST",args:{name:frm.doc.name},freeze:true
                    });
                    const result=response.message || {};
                    if (result.status==="Draft Created") {
                        frappe.set_route("Form","Material Request",result.name);
                    } else if (result.status==="Open Material Request") {
                        const content=$("<div>");
                        $("<p>").text(__("Existing Material Requests already cover this replenishment scope.")).appendTo(content);
                        for (const name of result.requests || []) $("<p>").text(name).appendTo(content);
                        frappe.msgprint({title:__("Duplicate prevented"),message:content.html()});
                    } else {
                        frappe.msgprint(__("No replenishment required. Combined projected stock: {0}",[result.projected_qty]));
                    }
                });
            });
        }
        // Keep rollback available for historical legacy applications.
        if (frappe.session.user === "Administrator" && ["Approved","Automatically Applied"].includes(frm.doc.status)) {
            frm.add_custom_button(__("Rollback"),()=>frappe.confirm(__("Confirm rollback of this reorder action?"),async()=>{
                await frappe.call({method:"qcmc_logic.dynamic_reorder_audit.rollback",type:"POST",args:{name:frm.doc.name},freeze:true});
                await frm.reload_doc();
            }));
        }
    }
});
frappe.ui.form.on("Reorder Schedule Settings", {
    async refresh(frm) {
        if (frappe.session.user !== "Administrator") return;
        const wrapper=frm.fields_dict.schedule_overview.$wrapper.empty();
        $("<p>").text(__("Time zone: Asia/Manila. The background checker runs every 15 minutes. Scheduled runs save previews only.")).appendTo(wrapper);
        try {
            const response=await frappe.call({method:"qcmc_logic.dynamic_reorder_schedule.schedule_summary",type:"GET"});
            const info=response.message;
            const rows=[
                [__("Schedule Status"),info.status],
                [__("Next Scheduled Execution"),info.next_execution || __("Disabled")],
                [__("Last Scheduled Date"),info.last_execution?.scheduled_date || __("Not yet executed")],
                [__("Last Execution Status"),info.last_execution?.status || __("Not yet executed")],
                [__("Last Finished At"),info.last_execution?.finished_at || "—"]
            ];
            const table=$("<table>").addClass("table table-bordered").appendTo(wrapper);
            for (const [label,value] of rows) {
                const row=$("<tr>").appendTo(table);
                $("<th>").text(label).appendTo(row);
                $("<td>").text(value).appendTo(row);
            }
            $("<p>").addClass("text-muted").text(__("Summary reflects saved settings, not a live scheduler heartbeat. Changes to timing or enablement take effect at the next future slot.")).appendTo(wrapper);
        } catch(e) {
            $("<p>").addClass("text-muted").text(__("Save schedule settings and refresh to view the summary.")).appendTo(wrapper);
        }
        frm.add_custom_button(__("Execution History"),()=>frappe.set_route("List","Reorder Execution History"));
    }
});
