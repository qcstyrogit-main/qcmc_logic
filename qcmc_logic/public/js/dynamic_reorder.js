frappe.ui.form.on("Reorder Settings", {
    refresh(frm) {
        if (frappe.session.user !== "Administrator") return;
        frm.add_custom_button(__("Preview Recommendations"), () => {
            const d = new frappe.ui.Dialog({
                title: __("Dynamic Reorder Preview"),
                fields: [
                    {fieldname:"company",fieldtype:"Link",options:"Company",label:"Company",reqd:1},
                    {fieldname:"warehouse",fieldtype:"Link",options:"Warehouse",label:"Warehouse",reqd:1,
                        get_query:()=>({filters:{company:d.get_value("company"),is_group:0,disabled:0}})},
                    {fieldname:"item_group",fieldtype:"Link",options:"Item Group",label:"Item Group"},
                    {fieldname:"item_code",fieldtype:"Link",options:"Item",label:"Item"},
                    {fieldname:"as_of",fieldtype:"Date",label:"Calculation Date",default:frappe.datetime.get_today()},
                    {fieldname:"period_method",fieldtype:"Select",label:"Demand Period Method",reqd:1,default:"Complete Calendar Months",options:"Complete Calendar Months\nRolling Days\nMonth-to-Date Inclusive"},
                    {fieldname:"rolling_days",fieldtype:"Int",label:"Rolling Days",default:90,depends_on:"eval:doc.period_method=='Rolling Days'"}
                ],
                primary_action_label:__("Run Preview"),
                async primary_action(values) {
                    const method = d.fields_dict.period_method.$input.val();
                    if (!["Complete Calendar Months","Rolling Days","Month-to-Date Inclusive"].includes(method)) {
                        frappe.msgprint(__("Select a Demand Period Method."));
                        return;
                    }
                    const days = method === "Rolling Days" ? Number(d.fields_dict.rolling_days.$input.val()) : null;
                    if (method === "Rolling Days" && (!Number.isInteger(days) || days < 1 || days > 1096)) {
                        frappe.msgprint(__("Rolling Days must be between 1 and 1096."));
                        return;
                    }
                    const args = {company:values.company,warehouse:values.warehouse,item_group:values.item_group,
                        item_code:values.item_code,as_of:values.as_of,period_method:method,rolling_days:days};
                    const response=await frappe.call({method:"qcmc_logic.dynamic_reorder_audit.run_preview",args,freeze:true});
                    if ((response.message.rows || []).some(row => row.demand_period_method && row.demand_period_method !== method)) {
                        frappe.msgprint(__("Saved preview period differs from the selected method. Do not apply; review calculation history."));
                    }
                    d.hide();
                    frappe.set_route("List","Reorder Calculation History",{batch:response.message.batch});
                }
            });
            d.show();
        });
    }
});
frappe.ui.form.on("Reorder Calculation History", {
    refresh(frm) {
        if (frappe.session.user !== "Administrator" || frm.is_new()) return;
        const apply = async () => {
            const response = await frappe.call({
                method:"qcmc_logic.dynamic_reorder_audit.application_precheck",
                type:"POST",args:{name:frm.doc.name},freeze:true
            });
            const result=response.message;
            if (!result.allowed) {
                const d=new frappe.ui.Dialog({
                    title:__("Cannot Apply Recommendation"),
                    fields:[{fieldname:"requirements",fieldtype:"HTML"}],
                    primary_action_label:__("Close"),
                    primary_action:()=>d.hide()
                });
                const wrapper=d.fields_dict.requirements.$wrapper;
                $("<p>").text(__("Resolve the following requirements before applying.")).appendTo(wrapper);
                const routes={
                    settings:["Form","Reorder Settings"],
                    policy:["Form","Reorder Policy",result.policy],
                    item:["Form","Item",result.item_code],
                    preview:["query-report","Reorder Analysis"]
                };
                for(const check of result.checks) {
                    const row=$("<div>").addClass("d-flex align-items-start mb-2").appendTo(wrapper);
                    $("<span>").addClass(check.ok?"text-success mr-2":"text-danger mr-2").text(check.ok?"✓":"✕").appendTo(row);
                    const body=$("<div>").appendTo(row);
                    $("<div>").text(__(check.label)).appendTo(body);
                    if(!check.ok && routes[check.target] && !routes[check.target].some(v=>!v)) {
                        $("<a>").attr("href","#").text(__({settings:"Open Reorder Settings",policy:"Open Reorder Policy",item:"Open Item",preview:"Generate Fresh Preview"}[check.target])).on("click",e=>{
                            e.preventDefault();d.hide();
                            if(check.target==="preview") {
                                frappe.set_route("query-report","Reorder Analysis",{company:frm.doc.company,warehouse:frm.doc.warehouse,item_code:frm.doc.item_code});
                            } else frappe.set_route(...routes[check.target]);
                        }).appendTo(body);
                    }
                }
                d.show();
                return;
            }
            frappe.confirm(__("Apply this recommendation to the Item Reorder configuration?"),async()=>{
                await frappe.call({method:"qcmc_logic.dynamic_reorder_audit.apply",args:{name:frm.doc.name},freeze:true});
                await frm.reload_doc();
            });
        };
        if ((["Preview","Pending Approval"].includes(frm.doc.status) && frm.doc.reorder_row) || frm.doc.status==="New Reorder Configuration") frm.add_custom_button(__("Apply Recommendation"),apply);
        if (["Approved","Automatically Applied"].includes(frm.doc.status)) frm.add_custom_button(__("Rollback"),()=>frappe.confirm(__("Confirm rollback of this reorder action?"),async()=>{
            await frappe.call({method:"qcmc_logic.dynamic_reorder_audit.rollback",args:{name:frm.doc.name},freeze:true});
            await frm.reload_doc();
        }));
    }
});
