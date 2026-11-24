frappe.query_reports["Accounts Payable Voucher VAT"] = {
onload(report) {
  report.page.add_inner_button(__("Print Legacy Layout"), () => {
    const f = report.get_values();
    if (!f) return;
    const params = new URLSearchParams();
    ["company","from_date","to_date","supplier","expense_account"].forEach(k => {
      if (f[k] != null && f[k] !== "") params.set(k, f[k]);
    });
    window.open("/api/method/qcmc_logic.qcmc_logics.report.accounts_payable_voucher_vat.accounts_payable_voucher_vat.print_report?" + params.toString(), "_blank", "noopener");
  });
},
filters:[
{fieldname:"company",label:__("Company"),fieldtype:"Link",options:"Company",reqd:1,default:frappe.defaults.get_user_default("Company")},
{fieldname:"from_date",label:__("From Date"),fieldtype:"Date",reqd:1,default:frappe.datetime.month_start()},
{fieldname:"to_date",label:__("To Date"),fieldtype:"Date",reqd:1,default:frappe.datetime.month_end()},
{fieldname:"supplier",label:__("Supplier"),fieldtype:"Link",options:"Supplier"},
{fieldname:"expense_account",label:__("Expense Account"),fieldtype:"Link",options:"Account"}
]};