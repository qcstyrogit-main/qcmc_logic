import frappe
from frappe import _
from frappe.utils import flt
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry
from erpnext.accounts.general_ledger import make_gl_entries, process_gl_map
from collections import defaultdict
#comment ako dito
class CustomPaymentEntry(PaymentEntry):
    def validate(self):
        super().validate()
        self.validate_intercompany_collection_payment()

    def on_submit(self):
        super().on_submit()
        self.create_intercompany_collection_transfer()

    def on_cancel(self):
        self.cancel_intercompany_collection_transfer()
        super().on_cancel()

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

    def is_intercompany_collection_payment(self):
        return self.payment_type == "Receive" and "collected by" in (self.mode_of_payment or "").lower()

    def get_collecting_company(self):
        if not self.is_intercompany_collection_payment():
            return None

        collector = (self.mode_of_payment or "").lower().split("collected by", 1)[1].strip()
        if not collector:
            return None

        return frappe.db.get_value("Company", {"abbr": collector.upper()}, "name")

    def validate_intercompany_collection_payment(self):
        if not self.is_intercompany_collection_payment():
            return

        collecting_company = self.get_collecting_company()
        if not collecting_company:
            frappe.throw(
                _("Mode of Payment {0} must end with a valid collecting company abbreviation, like 'Collected by QC'.").format(
                    frappe.bold(self.mode_of_payment)
                )
            )

        if collecting_company == self.company:
            frappe.throw(_("Intercompany collection cannot be collected by the same company."))

        if not self.custom_ref_doc:
            frappe.throw(_("Please set Ref Doc to the collecting company's submitted Payment Entry."))

        if not frappe.db.exists("Payment Entry", self.custom_ref_doc):
            frappe.throw(_("Ref Doc {0} is not a valid Payment Entry.").format(frappe.bold(self.custom_ref_doc)))

        source_payment = frappe.get_cached_doc("Payment Entry", self.custom_ref_doc)
        if source_payment.docstatus != 1:
            frappe.throw(_("Ref Doc {0} must be a submitted Payment Entry.").format(frappe.bold(self.custom_ref_doc)))

        if source_payment.company != collecting_company:
            frappe.throw(
                _("Ref Doc {0} belongs to {1}, but Mode of Payment indicates collection by {2}.").format(
                    frappe.bold(source_payment.name),
                    frappe.bold(source_payment.company),
                    frappe.bold(collecting_company),
                )
            )

        if source_payment.party_type != self.party_type or source_payment.party != self.party:
            frappe.throw(_("Ref Doc must be for the same party as this Payment Entry."))

        if frappe.db.get_value("Account", source_payment.paid_to, "account_type") != "Bank":
            frappe.throw(_("Ref Doc must be a Receive Payment Entry paid into a bank account."))

        if flt(source_payment.unallocated_amount) < flt(self.received_amount):
            frappe.throw(
                _("Ref Doc must have at least {0} unallocated amount. Current unallocated amount is {1}.").format(
                    frappe.bold(self.received_amount),
                    frappe.bold(source_payment.unallocated_amount),
                )
            )

        paid_to_type = frappe.db.get_value("Account", self.paid_to, "account_type")
        paid_to_name = frappe.db.get_value("Account", self.paid_to, "account_name") or ""
        if paid_to_type != "Current Asset" or "advances" not in paid_to_name.lower():
            frappe.throw(_("Paid To must be a Current Asset Advances account for intercompany collections."))

        if flt(self.received_amount) <= 0:
            frappe.throw(_("Received Amount must be greater than zero."))

    def create_intercompany_collection_transfer(self):
        if not self.is_intercompany_collection_payment():
            return

        if self.get("custom_intercompany_source_journal_entry") or self.get("custom_intercompany_target_journal_entry"):
            return

        collecting_company = self.get_collecting_company()
        source_payment = frappe.get_doc("Payment Entry", self.custom_ref_doc)
        amount = flt(self.base_received_amount or self.received_amount)

        target_bank = self.get_company_bank_account(self.company)

        source_jv = self.make_intercompany_source_journal_entry(
            collecting_company=collecting_company,
            source_payment=source_payment,
            amount=amount,
        )
        target_jv = self.make_intercompany_target_journal_entry(
            bank_account=target_bank,
            amount=amount,
            source_jv=source_jv,
        )

        frappe.db.set_value(
            "Payment Entry",
            self.name,
            {
                "custom_intercompany_source_journal_entry": source_jv.name,
                "custom_intercompany_target_journal_entry": target_jv.name,
            },
            update_modified=False,
        )
        self.db_set("custom_intercompany_source_journal_entry", source_jv.name, update_modified=False)
        self.db_set("custom_intercompany_target_journal_entry", target_jv.name, update_modified=False)

    def cancel_intercompany_collection_transfer(self):
        for fieldname in ("custom_intercompany_target_journal_entry", "custom_intercompany_source_journal_entry"):
            journal_entry = self.get(fieldname)
            if journal_entry and frappe.db.exists("Journal Entry", journal_entry):
                doc = frappe.get_doc("Journal Entry", journal_entry)
                if doc.docstatus == 1:
                    doc.cancel()

    def make_intercompany_source_journal_entry(self, collecting_company, source_payment, amount):
        journal_entry = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "voucher_type": "Bank Entry",
                "company": collecting_company,
                "posting_date": self.posting_date,
                "cheque_no": self.reference_no or source_payment.reference_no or self.name,
                "cheque_date": self.reference_date or source_payment.reference_date or self.posting_date,
                "user_remark": _(
                    "Auto-created from intercompany collection Payment Entry {0}; source collection {1}."
                ).format(self.name, source_payment.name),
                "accounts": [
                    {
                        "account": source_payment.paid_from,
                        "party_type": source_payment.party_type,
                        "party": source_payment.party,
                        "debit_in_account_currency": amount,
                        "cost_center": self.get_company_cost_center(collecting_company),
                    },
                    {
                        "account": source_payment.paid_to,
                        "credit_in_account_currency": amount,
                        "cost_center": self.get_company_cost_center(collecting_company),
                    },
                ],
            }
        )
        journal_entry.insert(ignore_permissions=True)
        journal_entry.submit()
        return journal_entry

    def make_intercompany_target_journal_entry(self, bank_account, amount, source_jv):
        journal_entry = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "voucher_type": "Bank Entry",
                "company": self.company,
                "posting_date": self.posting_date,
                "cheque_no": self.reference_no or self.name,
                "cheque_date": self.reference_date or self.posting_date,
                "inter_company_journal_entry_reference": source_jv.name,
                "user_remark": _("Auto-created from intercompany collection Payment Entry {0}.").format(self.name),
                "accounts": [
                    {
                        "account": bank_account,
                        "debit_in_account_currency": amount,
                        "cost_center": self.get_company_cost_center(self.company),
                    },
                    {
                        "account": self.paid_to,
                        "credit_in_account_currency": amount,
                        "cost_center": self.get_company_cost_center(self.company),
                    },
                ],
            }
        )
        journal_entry.insert(ignore_permissions=True)
        journal_entry.submit()
        frappe.db.set_value(
            "Journal Entry",
            source_jv.name,
            "inter_company_journal_entry_reference",
            journal_entry.name,
            update_modified=False,
        )
        return journal_entry

    def get_company_bank_account(self, company):
        company_default = frappe.db.get_value("Company", company, "default_bank_account")
        if company_default:
            return company_default

        account = frappe.db.get_value(
            "Account",
            {"company": company, "account_type": "Bank", "is_group": 0},
            "name",
        )
        if account:
            return account

        frappe.throw(_("No bank account found for company {0}.").format(frappe.bold(company)))

    def get_company_cost_center(self, company):
        cost_center = frappe.db.get_value("Company", company, "cost_center")
        if cost_center:
            return cost_center

        return frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
    
