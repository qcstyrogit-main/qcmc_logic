frappe.query_reports["Replenishment Monitoring"] = {
    filters: [
        {fieldname:"company",label:__("Company"),fieldtype:"Link",options:"Company",reqd:1,default:frappe.defaults.get_user_default("Company")},
        {fieldname:"mapping",label:__("Reorder Policy Mapping"),fieldtype:"Link",options:"Reorder Policy Mapping",reqd:1,
            get_query:()=>({filters:{company:frappe.query_report.get_filter_value("company"),enabled:1}})},
        {fieldname:"item_code",label:__("Item"),fieldtype:"Link",options:"Item"},
        {fieldname:"monitor_status",label:__("Monitoring Status"),fieldtype:"Select",
            options:"\nBOM Required\nReplenishment Required\nReview Required\nOpen Material Request\nNeeds Approval\nAbove Reorder Level\nMake to Order"}
    ],
    onload(report) {
        report.page.add_inner_button(__("Open Warehouse Mapping"),()=>{
            const mapping=report.get_filter_value("mapping");
            if(!mapping) return frappe.msgprint(__("Select a warehouse mapping first."));
            frappe.set_route("Form","Reorder Policy Mapping",mapping);
        });
        report.page.add_inner_button(__("Calculate Recommendations"),()=>{
            const company=report.get_filter_value("company"), mapping=report.get_filter_value("mapping");
            if(!company || !mapping) return frappe.msgprint(__("Select company and mapping first."));
            frappe.set_route("query-report","Reorder Analysis",{company,mapping,item_code:report.get_filter_value("item_code") || ""});
        });
        report.page.add_inner_button(__("Request Execution History"),()=>frappe.set_route("List","Replenishment Execution History"));
    },
    formatter(value,row,column,data,default_formatter) {
        const formatted=default_formatter(value,row,column,data);
        if(column.fieldname==="monitor_status" && data) {
            const colors={"BOM Required":"red","Replenishment Required":"red","Review Required":"orange","Open Material Request":"blue",
                "Needs Approval":"orange","Above Reorder Level":"green","Make to Order":"gray"};
            return $("<span>").addClass("indicator-pill "+(colors[data.monitor_status]||"gray")).text(data.monitor_status).prop("outerHTML");
        }
        if(column.fieldname==="manufacturing_readiness" && data && data.manufacturing_readiness) {
            const colors={"BOM Required":"red","Ready":"green","Review Required":"orange"};
            return $("<span>").addClass("indicator-pill "+(colors[data.manufacturing_readiness]||"gray")).text(data.manufacturing_readiness).prop("outerHTML");
        }
        return formatted;
    }
};
