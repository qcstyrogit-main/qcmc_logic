frappe.query_reports["Collection Report"] = {
filters:[
{fieldname:"company",label:__("Company"),fieldtype:"Link",options:"Company",reqd:1,default:frappe.defaults.get_user_default("Company")},
{fieldname:"from_date",label:__("From Date"),fieldtype:"Date",reqd:1,default:frappe.datetime.month_start()},
{fieldname:"to_date",label:__("To Date"),fieldtype:"Date",reqd:1,default:frappe.datetime.month_end()},
{fieldname:"sales_manager",label:__("Sales Manager"),fieldtype:"Data"},
{fieldname:"territory",label:__("Territory / Region"),fieldtype:"Link",options:"Territory"},
{fieldname:"customer",label:__("Customer"),fieldtype:"Link",options:"Customer"},
{fieldname:"customer_group",label:__("Customer Group"),fieldtype:"Link",options:"Customer Group"},
{fieldname:"include_cancelled",label:__("Include Cancelled"),fieldtype:"Check",default:0}
],
onload(report){report.page.add_inner_button(__("Print Collection Layout"),()=>{
const f=report.get_values();if(!f)return;
const p=new URLSearchParams();Object.entries(f).forEach(([k,v])=>{if(v!==undefined&&v!==null)p.set(k,String(v))});
window.open("/api/method/qcmc_logic.qcmc_logics.report.collection_report.collection_report.print_report?"+p.toString(),"_blank");
});}
};