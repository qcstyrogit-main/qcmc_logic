frappe.query_reports["Reorder Analysis"] = {
    filters: [
        {fieldname:"company",label:__("Company"),fieldtype:"Link",options:"Company",reqd:1,default:frappe.defaults.get_user_default("Company")},
        {fieldname:"warehouse",label:__("Warehouse"),fieldtype:"Link",options:"Warehouse",reqd:1,get_query:()=>({filters:{company:frappe.query_report.get_filter_value("company"),is_group:0,disabled:0}})},
        {fieldname:"item_group",label:__("Item Group"),fieldtype:"Link",options:"Item Group"},
        {fieldname:"item_code",label:__("Item"),fieldtype:"Link",options:"Item"},
        {fieldname:"policy",label:__("Reorder Policy"),fieldtype:"Link",options:"Reorder Policy"},
        {fieldname:"as_of",label:__("Calculation Date"),fieldtype:"Date",default:frappe.datetime.get_today()},
        {fieldname:"period_method",label:__("Demand Period Method"),fieldtype:"Select",options:"\nComplete Calendar Months\nRolling Days\nMonth-to-Date Inclusive"},
        {fieldname:"rolling_days",label:__("Rolling Days"),fieldtype:"Int",default:90,depends_on:"eval:doc.period_method=='Rolling Days'"},
        {fieldname:"status",label:__("Status"),fieldtype:"Select",options:"\nPreview\nPending Approval\nNew Reorder Configuration\nSkipped\nFailed"},
        {fieldname:"inventory_health",label:__("Inventory Health"),fieldtype:"Select",options:"\nCritical Stock\nReorder Required\nHealthy Stock\nOverstock\nNo Demand\nNot Evaluated"},
        {fieldname:"seasonal_only",label:__("Seasonal Items Only"),fieldtype:"Check"},
        {fieldname:"changed_only",label:__("Changed Items Only"),fieldtype:"Check"}
    ],
    onload(report) {
        if (frappe.session.user !== "Administrator") return;
        report.page.add_inner_button(__("Save Preview for Approval"), async () => {
            const f = report.get_filter_values();
            if (!f.company || !f.warehouse || !f.item_code) {
                frappe.msgprint(__("Select Company, Warehouse and a single Item first."));
                return;
            }
            const method = f.period_method || "Complete Calendar Months";
            const days = method === "Rolling Days" ? Number(f.rolling_days) : null;
            if (method === "Rolling Days" && (!Number.isInteger(days) || days < 1 || days > 1096)) {
                frappe.msgprint(__("Enter a valid Rolling Days value."));
                return;
            }
            frappe.confirm(__("Save a fresh preview for {0} using {1}? This will not update Item Reorder settings.", [f.item_code, method]), async () => {
                const response = await frappe.call({
                    method:"qcmc_logic.dynamic_reorder_audit.run_preview",
                    args:{company:f.company,warehouse:f.warehouse,item_code:f.item_code,
                        item_group:f.item_group,as_of:f.as_of,period_method:method,rolling_days:days},
                    freeze:true
                });
                const rows = response.message.rows || [];
                if (!rows.length) {
                    frappe.msgprint(__("No eligible item found."));
                    return;
                }
                if (rows.some(r => r.demand_period_method && r.demand_period_method !== method)) {
                    frappe.msgprint(__("Preview period mismatch. Do not apply."));
                    return;
                }
                frappe.set_route("List","Reorder Calculation History",{batch:response.message.batch});
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
