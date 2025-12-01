import frappe
from frappe import _
from frappe.utils import flt
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry
from erpnext.accounts.general_ledger import make_gl_entries, process_gl_map
from collections import defaultdict
#comment ako dito
class CustomPaymentEntry(PaymentEntry):
    def make_gl_entries(self, cancel=0, adv_adj=0):
        if self.get("custom_enable_manual_gl_entries") and self.payment_type == "Pay":
            if cancel:
                return super().make_gl_entries(cancel=1)

            gl_map = self.build_custom_gl_map()
            gl_entries = process_gl_map(gl_map)
            make_gl_entries(gl_entries, cancel=0, adv_adj=adv_adj)
        else:
            super().make_gl_entries(cancel=cancel, adv_adj=adv_adj)

    def build_custom_gl_map(self):
        """
        Build GL entries summarizing child table rows:
        - Expense Debits
        - Input Tax Debits
        - EWT Payable Credits
        Same expense_account + cost_center + location will merge into one entry.
        """
        # --- Custom Validation ---
        total_base_amt = sum(flt(row.base_amt) for row in self.get("custom_expense_details") or [])
        total_input_tax = sum(flt(row.input_tax) for row in self.get("custom_expense_details") or [])
        total_ewt_payable = sum(flt(row.ewt_payable) for row in self.get("custom_expense_details") or [])

        expected_paid_amount = total_base_amt ###+ total_input_tax - total_ewt_payable

        precision = self.precision("base_paid_amount")
        if flt(self.base_paid_amount, precision) != flt(expected_paid_amount, precision):
            frappe.throw(
                _("Base Paid Amount does not match the computation from expense details. Expected: {0}, Actual: {1}").format(
                    expected_paid_amount, self.base_paid_amount
                )
            )
        # --- End Custom Validation ---

        company_defaults = frappe.get_cached_value('Company', self.company, 
            ['custom_default_input_tax_account', 'custom_default_ewt_payable_account'], as_dict=True)
        input_tax_account = company_defaults.get('custom_default_input_tax_account')
        ewt_payable_account = company_defaults.get('custom_default_ewt_payable_account')

        gl_entries = []
        total_debit = 0.0
        total_credit = 0.0

        # --- Bank Credit (main account) --- Base - total EWT 
        bank_credit = flt(self.base_paid_amount) - total_ewt_payable

        gl_entries.append(
            self.get_gl_dict({
                "account": self.paid_from,
                "account_currency": self.paid_from_account_currency,
                "against": ", ".join(d.expense_account for d in self.get("custom_expense_details") if d.expense_account),
                "credit_in_account_currency": bank_credit,
                "credit": bank_credit * self.source_exchange_rate,
                "cost_center": self.cost_center,
            }, item=self)
        )
        total_credit += bank_credit * self.source_exchange_rate

        # --- Summarize child rows ---
        summary = defaultdict(lambda: {"debit": 0.0, "input_tax": 0.0, "ewt": 0.0})
        misc_summary = defaultdict(lambda: {"debit": 0.0})

        for row in self.get("custom_expense_details") or []:
            key = (row.expense_account, row.cost_center or self.cost_center, getattr(row, "location", None))
            summary[key]["debit"] += flt(row.taxable_amount - row.input_tax  or 0)
            summary[key]["input_tax"] += flt(row.input_tax or 0)
            summary[key]["ewt"] += flt(row.ewt_payable or 0)
            
            misc_amt = flt(row.misc_amt or 0)
            if misc_amt > 0:
                if not row.get("misc_exp"):
                    frappe.throw(_("Row {0}: Misc Expense account is required when Base Amount is not equal to Taxable Amount.").format(row.idx))
                
                misc_key = (row.misc_exp, row.cost_center or self.cost_center, getattr(row, "location", None))
                misc_summary[misc_key]["debit"] += misc_amt

        # --- Build GL entries from summary ---
        for (expense_account, cost_center, location), amounts in summary.items():
            exchange_rate = self.source_exchange_rate

            # Expense Debit
            if amounts["debit"] > 0:
                total_debit += amounts["debit"] * exchange_rate
                gl_entries.append(
                    self.get_gl_dict({
                        "account": expense_account,
                        "cost_center": cost_center,
                        "debit_in_account_currency": amounts["debit"],
                        "debit": amounts["debit"] * exchange_rate,
                        "against": self.paid_from,
                    }, item=self)
                )

            # Input Tax Debit
            if amounts["input_tax"] > 0:
                if not input_tax_account:
                    frappe.throw(_("Please set 'Default Input Tax Account' in Company settings."))
                total_debit += amounts["input_tax"] * exchange_rate
                gl_entries.append(
                    self.get_gl_dict({
                        "account": input_tax_account,
                        "cost_center": cost_center,
                        "debit_in_account_currency": amounts["input_tax"],
                        "debit": amounts["input_tax"] * exchange_rate,
                        "against": self.paid_from,
                    }, item=self)
                )

            # EWT Credit
            if amounts["ewt"] > 0:
                if not ewt_payable_account:
                    frappe.throw(_("Please set 'Default EWT Payable Account' in Company settings."))
                total_credit += amounts["ewt"] * exchange_rate
                gl_entries.append(
                    self.get_gl_dict({
                        "account": ewt_payable_account,
                        "cost_center": cost_center,
                        "credit_in_account_currency": amounts["ewt"],
                        "credit": amounts["ewt"] * exchange_rate,
                        "against": expense_account,
                    }, item=self)
                )
        
        for (misc_account, cost_center, location), amounts in misc_summary.items():
            exchange_rate = self.source_exchange_rate
            if amounts["debit"] > 0:
                total_debit += amounts["debit"] * exchange_rate
                gl_entries.append(
                    self.get_gl_dict({
                        "account": misc_account,
                        "cost_center": cost_center,
                        "debit_in_account_currency": amounts["debit"],
                        "debit": amounts["debit"] * exchange_rate,
                        "against": self.paid_from,
                    }, item=self)
                )

        # --- Final validation ---
        precision = self.precision("base_paid_amount")
        if flt(total_debit, precision) != flt(total_credit, precision):
            frappe.throw(_("Totals do not balance. Debit: {0}, Credit: {1}").format(total_debit, total_credit))

        return gl_entries
    
