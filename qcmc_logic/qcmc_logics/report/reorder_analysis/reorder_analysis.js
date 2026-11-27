frappe.query_reports["Reorder Analysis"] = {
    filters: [
        {fieldname:"company",label:__("Company"),fieldtype:"Link",options:"Company",reqd:1,default:frappe.defaults.get_user_default("Company")},
        {fieldname:"mapping",label:__("Reorder Policy Mapping"),fieldtype:"Link",options:"Reorder Policy Mapping",reqd:1,get_query:()=>({filters:{company:frappe.query_report.get_filter_value("company"),enabled:1}})},
        {fieldname:"item_group",label:__("Item Group"),fieldtype:"Link",options:"Item Group"},
        {fieldname:"item_code",label:__("Item"),fieldtype:"Link",options:"Item"},
        {fieldname:"policy",label:__("Reorder Policy"),fieldtype:"Link",options:"Reorder Policy"},
        {fieldname:"as_of",label:__("Calculation Date"),fieldtype:"Date",reqd:1,
            default:frappe.datetime.get_today(),max_date:moment(frappe.datetime.get_today(), "YYYY-MM-DD").toDate(),
            description:__("Historical demand ends on the day before the calculation date."),
            on_change: async (report) => {
                const today = frappe.datetime.get_today();
                if (report.get_filter_value("as_of") > today) {
                    frappe.msgprint(__("Future calculation dates are not supported. Historical demand excludes the calculation date."));
                    await report.set_filter_value("as_of", today);
                }
                if (!report._no_refresh) return report.refresh(true);
            }},
        {fieldname:"period_method",label:__("Demand Period Method"),fieldtype:"Select",options:"\nComplete Calendar Months\nRolling Days\nMonth-to-Date Inclusive"},
        {fieldname:"rolling_days",label:__("Rolling Days"),fieldtype:"Int",default:90,depends_on:"eval:doc.period_method=='Rolling Days'"},
        {fieldname:"status",label:__("Status"),fieldtype:"Select",options:"\nPreview\nPending Approval\nNew Reorder Configuration\nSkipped\nFailed"},
        {fieldname:"inventory_health",label:__("Inventory Health"),fieldtype:"Select",options:"\nCritical Stock\nReorder Required\nHealthy Stock\nOverstock\nNo Demand\nNot Evaluated"},
        {fieldname:"seasonal_only",label:__("Seasonal Items Only"),fieldtype:"Check"},
        {fieldname:"changed_only",label:__("Changed Items Only"),fieldtype:"Check"}
    ],
    async onload(report) {
        const today = frappe.datetime.get_today();
        if (report.get_filter_value("as_of") > today) {
            frappe.msgprint(__("Future calculation dates are not supported. The calculation date has been reset to today. Historical demand ends on the previous day."));
            await report.set_filter_value("as_of", today);
        }
        if (frappe.session.user !== "Administrator") return;
        report.page.add_inner_button(__("Create Calculation Batch"), async () => {
            const f=report.get_filter_values();
            if(!f.company || !f.mapping) return frappe.msgprint(__("Select Company and Warehouse Mapping first."));
            if(f.as_of>frappe.datetime.get_today()) return frappe.msgprint(__("Future calculation dates are not supported."));
            const method=f.period_method || null, days=method==="Rolling Days"?Number(f.rolling_days):null;
            if(method==="Rolling Days" && (!Number.isInteger(days)||days<1||days>1096)) return frappe.msgprint(__("Enter a valid Rolling Days value."));
            frappe.confirm(__("Calculate {0} in a background batch? No reorder values will be applied.",[f.item_code||__("all eligible items in this mapping")]),async()=>{
                const response=await frappe.call({method:"qcmc_logic.dynamic_reorder_batch.start",type:"POST",
                    args:{company:f.company,mapping:f.mapping,item_code:f.item_code,item_group:f.item_group,as_of:f.as_of,period_method:method,rolling_days:days},freeze:true});
                frappe.set_route("Form","Reorder Calculation Batch",response.message.batch);
            });
        });
    },
    formatter(value,row,column,data,default_formatter) {
        const formatted=default_formatter(value,row,column,data);
        if (!data) return formatted;
        const field=column.fieldname;
        let color;
        if (field==="inventory_health") color=({"Critical Stock":"#b91c1c","Reorder Required":"#b45309","Healthy Stock":"#15803d","Overstock":"#b45309","No Demand":"#64748b","Not Evaluated":"#64748b"})[data.inventory_health];
        if (field==="status") color=({"Preview":"#15803d","Pending Approval":"#b45309","New Reorder Configuration":"#b45309","Failed":"#b91c1c","Skipped":"#64748b"})[data.status];
        if (["level_change_pct","qty_change_pct"].includes(field) && data[field] == null) return "—";
        if (["level_change_pct","qty_change_pct"].includes(field) && Number(value)!==0 && value!=null) color=Number(value)>0?"#b45309":"#2563eb";
        return color ? '<span style="color:'+color+';font-weight:600">'+formatted+'</span>' : formatted;
    }
};
