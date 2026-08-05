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
        self.validate_underpayment_breakdown()

    def on_cancel(self):
        self.cleanup_intercompany_collection_links(delete=False)
        super().on_cancel()

    def on_trash(self):
        self.cleanup_intercompany_collection_links(delete=True)
        self.clear_intercompany_collection_reference_links()
        _delete_voucher_ledger_rows(self.doctype, self.name)

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

        if not frappe.db.exists("Account", {"name": source_payment.paid_to, "is_group": 0}):
            frappe.throw(_("Ref Doc must be paid into a valid ledger account."))

        source_collection_amount = _get_affiliate_collection_deduction_amount(source_payment)
        if source_collection_amount < flt(self.received_amount):
            frappe.throw(
                _("Ref Doc must have at least {0} affiliate collection deduction amount. Current amount is {1}.").format(
                    frappe.bold(self.received_amount),
                    frappe.bold(source_collection_amount),
                )
            )

        paid_to_type = frappe.db.get_value("Account", self.paid_to, "account_type")
        paid_to_name = frappe.db.get_value("Account", self.paid_to, "account_name") or ""
        if paid_to_type != "Current Asset" or "advances" not in paid_to_name.lower():
            frappe.throw(_("Paid To must be a Current Asset Advances account for intercompany collections."))

        if flt(self.received_amount) <= 0:
            frappe.throw(_("Received Amount must be greater than zero."))

    def validate_underpayment_breakdown(self):
        if self.payment_type != "Receive":
            return
        if not frappe.db.table_exists("Payment Entry Underpayment"):
            return

        required = self.get_required_underpayment_by_invoice()
        breakdown = self.get_underpayment_breakdown_by_invoice()
        precision = self.precision("paid_amount") or 2
        is_submit = getattr(self, "_action", None) == "submit"
        invoices_to_validate = required if is_submit else {
            invoice: amount
            for invoice, amount in required.items()
            if invoice in breakdown
        }

        for invoice, expected_amount in invoices_to_validate.items():
            actual_amount = breakdown.get(invoice, 0)
            if flt(actual_amount, precision) != flt(expected_amount, precision):
                frappe.throw(
                    _(
                        "Underpayment Breakdown for Sales Invoice {0} must total {1}. Current total is {2}."
                    ).format(
                        frappe.bold(invoice),
                        frappe.bold(frappe.format_value(expected_amount, {"fieldtype": "Currency"})),
                        frappe.bold(frappe.format_value(actual_amount, {"fieldtype": "Currency"})),
                    )
                )

        unexpected_invoices = sorted(set(breakdown) - set(required))
        if unexpected_invoices:
            frappe.throw(
                _("Underpayment Breakdown is only allowed for first underpaid Sales Invoice payments. Remove rows for: {0}").format(
                    ", ".join(frappe.bold(invoice) for invoice in unexpected_invoices)
                )
            )

    def get_required_underpayment_by_invoice(self):
        required = {}
        precision = self.precision("paid_amount") or 2

        for row in self.get("references") or []:
            if row.reference_doctype != "Sales Invoice" or not row.reference_name:
                continue

            allocated_amount = flt(row.allocated_amount, precision)
            outstanding_amount = flt(row.outstanding_amount, precision)
            underpayment_amount = flt(outstanding_amount - allocated_amount, precision)

            if allocated_amount <= 0 or underpayment_amount <= 0:
                continue
            if not _is_first_sales_invoice_payment(row.reference_name, self.name):
                continue
            if _has_submitted_underpayment_breakdown(row.reference_name, self.name):
                continue

            required[row.reference_name] = flt(
                required.get(row.reference_name, 0) + underpayment_amount,
                precision,
            )

        return required

    def get_underpayment_breakdown_by_invoice(self):
        breakdown = {}
        precision = self.precision("paid_amount") or 2

        for row in self.get("custom_underpayment_breakdown") or []:
            if not row.sales_invoice:
                frappe.throw(_("Sales Invoice is required in Underpayment Breakdown row {0}.").format(row.idx))
            if not row.underpayment_type:
                frappe.throw(_("Underpayment Type is required in Underpayment Breakdown row {0}.").format(row.idx))
            if flt(row.amount, precision) <= 0:
                frappe.throw(_("Amount must be greater than zero in Underpayment Breakdown row {0}.").format(row.idx))
            if _has_submitted_underpayment_breakdown(row.sales_invoice, self.name):
                existing_payment = _get_submitted_underpayment_payment_entry(row.sales_invoice, self.name)
                frappe.throw(
                    _(
                        "Sales Invoice {0} already has an underpayment breakdown in submitted Payment Entry {1}. "
                        "It cannot be used again for underpayment."
                    ).format(frappe.bold(row.sales_invoice), frappe.bold(existing_payment))
                )

            breakdown[row.sales_invoice] = flt(
                breakdown.get(row.sales_invoice, 0) + flt(row.amount, precision),
                precision,
            )

        return breakdown

    def cleanup_intercompany_collection_links(self, delete=False):
        for fieldname in ("custom_intercompany_target_journal_entry", "custom_intercompany_source_journal_entry"):
            journal_entry = self.get(fieldname)
            if journal_entry and frappe.db.exists("Journal Entry", journal_entry):
                _cancel_or_delete_doc("Journal Entry", journal_entry, delete=delete)

        target_payment_entry = self.get("custom_intercompany_target_payment_entry")
        if target_payment_entry and frappe.db.exists("Payment Entry", target_payment_entry):
            _cancel_or_delete_doc("Payment Entry", target_payment_entry, delete=delete)

        source_payment_entry = self.get("custom_intercompany_source_payment_entry") or self.get("custom_ref_doc")
        if source_payment_entry and frappe.db.exists("Payment Entry", source_payment_entry):
            linked_target = frappe.db.get_value(
                "Payment Entry",
                source_payment_entry,
                "custom_intercompany_target_payment_entry",
            )
            if linked_target == self.name:
                frappe.db.set_value(
                    "Payment Entry",
                    source_payment_entry,
                    "custom_intercompany_target_payment_entry",
                    None,
                    update_modified=False,
                )

    def clear_intercompany_collection_reference_links(self):
        if self.get("custom_intercompany_target_payment_entry"):
            frappe.db.set_value(
                "Payment Entry",
                self.name,
                "custom_intercompany_target_payment_entry",
                None,
                update_modified=False,
            )

        for fieldname in (
            "custom_intercompany_source_payment_entry",
            "custom_ref_doc",
        ):
            linked_source = self.get(fieldname)
            if linked_source and frappe.db.exists("Payment Entry", linked_source):
                linked_target = frappe.db.get_value(
                    "Payment Entry",
                    linked_source,
                    "custom_intercompany_target_payment_entry",
                )
                if linked_target == self.name:
                    frappe.db.set_value(
                        "Payment Entry",
                        linked_source,
                        "custom_intercompany_target_payment_entry",
                        None,
                        update_modified=False,
                    )

        for journal_entry in frappe.get_all(
            "Journal Entry",
            filters=[
                ["Journal Entry", "custom_intercompany_source_payment_entry", "=", self.name],
            ],
            pluck="name",
        ):
            _cancel_or_delete_doc("Journal Entry", journal_entry, delete=True)

        for journal_entry in frappe.get_all(
            "Journal Entry",
            filters=[
                ["Journal Entry", "custom_intercompany_target_payment_entry", "=", self.name],
            ],
            pluck="name",
        ):
            _cancel_or_delete_doc("Journal Entry", journal_entry, delete=True)

    def make_intercompany_source_journal_entry(self, collecting_company, source_payment, amount, target_company=None):
        target_company = target_company or self.company
        payable_account = _get_affiliate_collection_deduction_account(source_payment, target_company)
        cash_account = self.get_company_cash_account(collecting_company)
        journal_entry = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "voucher_type": "Cash Entry",
                "company": collecting_company,
                "posting_date": self.posting_date,
                "cheque_no": self.reference_no or source_payment.reference_no or self.name,
                "cheque_date": self.reference_date or source_payment.reference_date or self.posting_date,
                "custom_intercompany_source_payment_entry": source_payment.name,
                "custom_intercompany_target_payment_entry": self.name,
                "user_remark": _(
                    "Auto-created cash settlement from intercompany collection Payment Entry {0}; source collection {1}."
                ).format(self.name, source_payment.name),
                "accounts": [
                    {
                        "account": payable_account,
                        "debit_in_account_currency": amount,
                        "cost_center": self.get_company_cost_center(collecting_company),
                    },
                    {
                        "account": cash_account,
                        "credit_in_account_currency": amount,
                        "cost_center": self.get_company_cost_center(collecting_company),
                    },
                ],
            }
        )
        journal_entry.insert(ignore_permissions=True)
        journal_entry.submit()
        return journal_entry

    def make_intercompany_target_journal_entry(self, cash_account, amount, source_jv, source_payment):
        journal_entry = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "voucher_type": "Cash Entry",
                "company": self.company,
                "posting_date": self.posting_date,
                "cheque_no": self.reference_no or self.name,
                "cheque_date": self.reference_date or self.posting_date,
                "inter_company_journal_entry_reference": source_jv.name,
                "custom_intercompany_source_payment_entry": source_payment.name,
                "custom_intercompany_target_payment_entry": self.name,
                "user_remark": _("Auto-created cash settlement from intercompany collection Payment Entry {0}.").format(self.name),
                "accounts": [
                    {
                        "account": cash_account,
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

    def get_company_cash_account(self, company):
        company_default = frappe.db.get_value("Company", company, "default_cash_account")
        if company_default:
            return company_default

        abbr = _get_company_abbr(company)
        if abbr:
            cash_on_hand = frappe.db.get_value(
                "Account",
                {
                    "company": company,
                    "account_type": "Cash",
                    "is_group": 0,
                    "account_name": ["like", "%Cash On Hand%"],
                },
                "name",
            )
            if cash_on_hand:
                return cash_on_hand

        account = frappe.db.get_value(
            "Account",
            {"company": company, "account_type": "Cash", "is_group": 0},
            "name",
        )
        if account:
            return account

        frappe.throw(_("No cash account found for company {0}.").format(frappe.bold(company)))

    def get_company_cost_center(self, company):
        cost_center = frappe.db.get_value("Company", company, "cost_center")
        if cost_center:
            return cost_center

        return frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")


def _get_company_abbr(company):
    return frappe.db.get_value("Company", company, "abbr")


def _is_first_sales_invoice_payment(sales_invoice, payment_entry=None):
    conditions = [
        "per.reference_doctype = 'Sales Invoice'",
        "per.reference_name = %(sales_invoice)s",
        "ifnull(per.allocated_amount, 0) > 0",
        "pe.docstatus = 1",
    ]
    values = {"sales_invoice": sales_invoice}
    if payment_entry:
        conditions.append("pe.name != %(payment_entry)s")
        values["payment_entry"] = payment_entry

    existing = frappe.db.sql(
        f"""
        select per.name
        from `tabPayment Entry Reference` per
        inner join `tabPayment Entry` pe on pe.name = per.parent
        where {" and ".join(conditions)}
        limit 1
        """,
        values,
    )
    return not existing


def _has_submitted_underpayment_breakdown(sales_invoice, payment_entry=None):
    return bool(_get_submitted_underpayment_payment_entry(sales_invoice, payment_entry))


def _get_submitted_underpayment_payment_entry(sales_invoice, payment_entry=None):
    if not frappe.db.table_exists("Payment Entry Underpayment"):
        return None

    conditions = [
        "peu.sales_invoice = %(sales_invoice)s",
        "pe.docstatus = 1",
    ]
    values = {"sales_invoice": sales_invoice}

    if payment_entry:
        conditions.append("pe.name != %(payment_entry)s")
        values["payment_entry"] = payment_entry

    rows = frappe.db.sql(
        f"""
        select pe.name
        from `tabPayment Entry Underpayment` peu
        inner join `tabPayment Entry` pe on pe.name = peu.parent
        where {" and ".join(conditions)}
        limit 1
        """,
        values,
        as_dict=True,
    )
    return rows[0].name if rows else None


@frappe.whitelist()
def get_existing_underpayment_invoices(sales_invoices, payment_entry=None):
    if isinstance(sales_invoices, str):
        sales_invoices = frappe.parse_json(sales_invoices)
    sales_invoices = list(filter(None, sales_invoices or []))

    if not sales_invoices or not frappe.db.table_exists("Payment Entry Underpayment"):
        return {}

    conditions = [
        "peu.sales_invoice in %(sales_invoices)s",
        "pe.docstatus = 1",
    ]
    values = {"sales_invoices": tuple(sales_invoices)}

    if payment_entry:
        conditions.append("pe.name != %(payment_entry)s")
        values["payment_entry"] = payment_entry

    rows = frappe.db.sql(
        f"""
        select peu.sales_invoice, pe.name as payment_entry
        from `tabPayment Entry Underpayment` peu
        inner join `tabPayment Entry` pe on pe.name = peu.parent
        where {" and ".join(conditions)}
        group by peu.sales_invoice
        """,
        values,
        as_dict=True,
    )
    return {row.sales_invoice: row.payment_entry for row in rows}


def _get_affiliate_collection_deduction_amount(payment_entry):
    amount = 0
    for row in payment_entry.get("deductions") or []:
        account = frappe.db.get_value(
            "Account",
            row.account,
            ["account_name", "root_type", "is_group"],
            as_dict=True,
        )
        account_name = (account.account_name if account else row.account or "").lower()
        if (
            account
            and account.root_type == "Liability"
            and not account.is_group
            and "advances from affiliates" in account_name
            and flt(row.amount) < 0
        ):
            amount += abs(flt(row.amount))

    return flt(amount)


def _get_affiliate_collection_deduction_account(payment_entry, affiliate_company=None):
    affiliate_abbr = _get_company_abbr(affiliate_company) if affiliate_company else None
    for row in payment_entry.get("deductions") or []:
        account = frappe.db.get_value(
            "Account",
            row.account,
            ["account_name", "root_type", "is_group"],
            as_dict=True,
        )
        account_name = (account.account_name if account else row.account or "").lower()
        if not (
            account
            and account.root_type == "Liability"
            and not account.is_group
            and "advances from affiliates" in account_name
            and flt(row.amount) < 0
        ):
            continue

        if affiliate_abbr and affiliate_abbr.lower() not in account_name:
            continue

        return row.account

    frappe.throw(_("No negative Advances From Affiliates deduction account found."))


def _cancel_or_delete_doc(doctype, name, delete=False):
    doc = frappe.get_doc(doctype, name)
    doc.flags.ignore_permissions = True
    doc.flags.ignore_validate = True
    doc.flags.ignore_links = True
    doc.ignore_linked_doctypes = (
        "GL Entry",
        "Payment Ledger Entry",
        "Advance Payment Ledger Entry",
        "Repost Payment Ledger",
        "Repost Payment Ledger Items",
        "Repost Accounting Ledger",
        "Repost Accounting Ledger Items",
        "Tax Withholding Entry",
    )

    if doc.docstatus == 1:
        doc.cancel()

    _delete_voucher_ledger_rows(doctype, name)

    if (delete or doc.docstatus == 0) and frappe.db.exists(doctype, name):
        frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)


def _delete_voucher_ledger_rows(voucher_type, voucher_no):
    frappe.db.delete("GL Entry", {"voucher_type": voucher_type, "voucher_no": voucher_no})

    if frappe.db.exists("DocType", "Payment Ledger Entry"):
        frappe.db.delete("Payment Ledger Entry", {"voucher_type": voucher_type, "voucher_no": voucher_no})

    if frappe.db.exists("DocType", "Advance Payment Ledger Entry"):
        frappe.db.delete("Advance Payment Ledger Entry", {"voucher_type": voucher_type, "voucher_no": voucher_no})


@frappe.whitelist()
def get_affiliate_collection_deduction_defaults(company, affiliate_company):
    if not frappe.db.exists("Company", company):
        frappe.throw(_("Company {0} does not exist.").format(frappe.bold(company)))
    if not frappe.db.exists("Company", affiliate_company):
        frappe.throw(_("Affiliate Company {0} does not exist.").format(frappe.bold(affiliate_company)))
    if company == affiliate_company:
        frappe.throw(_("Affiliate Company must be different from the Payment Entry company."))

    return {
        "account": _find_affiliate_advance_account(
            company,
            affiliate_company,
            root_type="Liability",
            account_direction="from",
        ),
        "cost_center": _get_company_cost_center(company),
    }


def _get_company_cost_center(company):
    cost_center = frappe.db.get_value("Company", company, "cost_center")
    if cost_center:
        return cost_center

    abbr = _get_company_abbr(company)
    if abbr:
        main_cost_center = "Main - {0}".format(abbr)
        if frappe.db.exists("Cost Center", {"name": main_cost_center, "company": company, "is_group": 0}):
            return main_cost_center

    cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
    if cost_center:
        return cost_center

    frappe.throw(_("No default Cost Center found for company {0}.").format(frappe.bold(company)))


def _get_intercompany_target_options(source_company):
    source_abbr = _get_company_abbr(source_company)
    if not source_abbr:
        frappe.throw(_("Please set an abbreviation for company {0}.").format(frappe.bold(source_company)))

    companies = frappe.get_all("Company", filters={"name": ["!=", source_company]}, fields=["name", "abbr"], order_by="name")
    options = []
    for company in companies:
        account = _find_affiliate_advance_account(company.name, source_company, root_type="Asset", throw=False)
        if account:
            options.append(
                {
                    "company": company.name,
                    "abbr": company.abbr,
                    "paid_to": account,
                }
            )

    if not options:
        frappe.throw(
            _(
                "No intercompany collection target company found for {0}. Set up an Advances to Affiliates ledger account in the target company that references {1}."
            ).format(frappe.bold(source_company), frappe.bold(source_abbr))
        )

    return options


def _get_collected_by_mode(collecting_company):
    abbr = _get_company_abbr(collecting_company)
    mode = frappe.db.get_value("Mode of Payment", {"name": ["like", "Collected%{0}".format(abbr)]}, "name")
    if mode:
        return mode

    mode = "Collected By {0}".format(abbr)
    if frappe.db.exists("Mode of Payment", mode):
        return mode

    frappe.throw(_("Mode of Payment {0} does not exist.").format(frappe.bold(mode)))


def _find_affiliate_advance_account(company, affiliate_company, root_type="Asset", throw=True, account_direction="to"):
    affiliate_abbr = _get_company_abbr(affiliate_company)
    phrase = "advances {0} affiliates".format(account_direction).lower()
    accounts = frappe.get_all(
        "Account",
        filters={
            "company": company,
            "is_group": 0,
            "root_type": root_type,
        },
        fields=["name", "account_name"],
        order_by="name",
    )
    for account in accounts:
        account_name = (account.account_name or account.name or "").lower()
        if phrase in account_name and affiliate_abbr.lower() in account_name:
            return account.name

    matching_direction_accounts = [
        account.name
        for account in accounts
        if phrase in ((account.account_name or account.name or "").lower())
    ]
    if len(matching_direction_accounts) == 1:
        return matching_direction_accounts[0]

    if not throw:
        return None

    frappe.throw(
        _("No affiliate advances account found in {0} for {1}.").format(
            frappe.bold(company),
            frappe.bold(affiliate_company),
        )
    )


def _get_matching_account_for_company(source_account, target_company):
    if not source_account:
        return None

    source = frappe.db.get_value(
        "Account",
        source_account,
        ["account_number", "account_name", "account_type", "root_type", "company"],
        as_dict=True,
    )
    if not source:
        return None

    if source.account_number:
        account = frappe.db.get_value(
            "Account",
            {"company": target_company, "account_number": source.account_number, "is_group": 0},
            "name",
        )
        if account:
            return account

    source_abbr = _get_company_abbr(source.company)
    target_abbr = _get_company_abbr(target_company)
    if source.account_name and source_abbr and target_abbr:
        target_account_name = source.account_name.rsplit("- {0}".format(source_abbr), 1)[0].strip()
        target_account_name = "{0} - {1}".format(target_account_name, target_abbr)
        account = frappe.db.get_value(
            "Account",
            {"company": target_company, "account_name": target_account_name, "is_group": 0},
            "name",
        )
        if account:
            return account

    account = frappe.db.get_value(
        "Account",
        {
            "company": target_company,
            "account_type": source.account_type,
            "root_type": source.root_type,
            "is_group": 0,
        },
        "name",
    )
    if account:
        return account

    frappe.throw(
        _("No matching account found in {0} for {1}.").format(
            frappe.bold(target_company),
            frappe.bold(source_account),
        )
    )


def _preview_from_target_payment(target_payment):
    source_payment = frappe.get_doc("Payment Entry", target_payment.custom_ref_doc)
    controller = target_payment
    if not isinstance(controller, CustomPaymentEntry):
        controller = CustomPaymentEntry(target_payment.as_dict())

    amount = flt(target_payment.base_received_amount or target_payment.received_amount)
    collecting_company = controller.get_collecting_company()
    payable_account = _get_affiliate_collection_deduction_account(source_payment, target_payment.company)
    source_cash = controller.get_company_cash_account(collecting_company)
    target_cash = controller.get_company_cash_account(target_payment.company)

    return {
        "source_payment_entry": source_payment.name,
        "target_payment_entry": target_payment.name,
        "collecting_company": collecting_company,
        "target_company": target_payment.company,
        "party_type": target_payment.party_type,
        "party": target_payment.party,
        "posting_date": target_payment.posting_date,
        "amount": amount,
        "source_journal_entry": {
            "company": collecting_company,
            "posting_date": target_payment.posting_date,
            "accounts": [
                {
                    "account": payable_account,
                    "debit": amount,
                    "credit": 0,
                },
                {
                    "account": source_cash,
                    "debit": 0,
                    "credit": amount,
                },
            ],
        },
        "target_journal_entry": {
            "company": target_payment.company,
            "posting_date": target_payment.posting_date,
            "accounts": [
                {
                    "account": target_cash,
                    "debit": amount,
                    "credit": 0,
                },
                {
                    "account": target_payment.paid_to,
                    "debit": 0,
                    "credit": amount,
                },
            ],
        },
    }


@frappe.whitelist()
def get_intercompany_collection_payment_preview(source_payment_entry, target_company=None):
    source_payment = frappe.get_doc("Payment Entry", source_payment_entry)
    source_payment.check_permission("read")

    if source_payment.docstatus != 1:
        frappe.throw(_("Source Payment Entry must be submitted."))
    if source_payment.payment_type != "Receive":
        frappe.throw(_("Source Payment Entry must be a Receive payment."))
    collection_amount = _get_affiliate_collection_deduction_amount(source_payment)
    if collection_amount <= 0:
        frappe.throw(_("Source Payment Entry has no negative Advances From Affiliates deduction."))
    if source_payment.get("custom_intercompany_target_payment_entry"):
        frappe.throw(_("This Payment Entry already has an intercompany target Payment Entry."))

    target_options = _get_intercompany_target_options(source_payment.company)
    if target_company:
        valid_targets = {option["company"] for option in target_options}
        if target_company not in valid_targets:
            frappe.throw(
                _("{0} is not configured as an intercompany collection target for {1}.").format(
                    frappe.bold(target_company),
                    frappe.bold(source_payment.company),
                )
            )
    else:
        target_company = target_options[0]["company"]

    amount = collection_amount
    paid_to = _find_affiliate_advance_account(target_company, source_payment.company, root_type="Asset")

    return {
        "source_payment_entry": source_payment.name,
        "target_company": target_company,
        "target_options": target_options,
        "collecting_company": source_payment.company,
        "mode_of_payment": _get_collected_by_mode(source_payment.company),
        "party_type": source_payment.party_type,
        "party": source_payment.party,
        "posting_date": source_payment.posting_date,
        "amount": amount,
        "paid_from": _get_matching_account_for_company(source_payment.paid_from, target_company),
        "paid_to": paid_to,
        "reference_no": source_payment.reference_no or source_payment.name,
        "reference_date": source_payment.reference_date or source_payment.posting_date,
    }


@frappe.whitelist()
def create_intercompany_collection_payment(source_payment_entry, target_company=None, paid_to=None, amount=None):
    preview = get_intercompany_collection_payment_preview(source_payment_entry, target_company=target_company)
    source_payment = frappe.get_doc("Payment Entry", source_payment_entry)
    source_payment.check_permission("write")

    amount = flt(amount or preview["amount"])
    collection_amount = _get_affiliate_collection_deduction_amount(source_payment)
    if amount <= 0 or amount > collection_amount:
        frappe.throw(_("Amount must be greater than zero and not more than the source affiliate collection deduction amount."))

    paid_to = paid_to or preview["paid_to"]
    if not frappe.db.exists("Account", {"name": paid_to, "company": preview["target_company"], "is_group": 0}):
        frappe.throw(_("Paid To must be a ledger account for {0}.").format(frappe.bold(preview["target_company"])))

    payment = frappe.get_doc(
        {
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "company": preview["target_company"],
            "posting_date": preview["posting_date"],
            "mode_of_payment": preview["mode_of_payment"],
            "party_type": preview["party_type"],
            "party": preview["party"],
            "paid_from": preview["paid_from"],
            "paid_to": paid_to,
            "paid_amount": amount,
            "received_amount": amount,
            "reference_no": preview["reference_no"],
            "reference_date": preview["reference_date"],
            "custom_ref_doc": source_payment.name,
            "custom_intercompany_source_payment_entry": source_payment.name,
        }
    )
    payment.insert(ignore_permissions=True)

    frappe.db.set_value(
        "Payment Entry",
        source_payment.name,
        "custom_intercompany_target_payment_entry",
        payment.name,
        update_modified=False,
    )
    frappe.db.commit()

    return {"payment_entry": payment.name}


@frappe.whitelist()
def get_intercompany_collection_journal_preview(target_payment_entry):
    target_payment = frappe.get_doc("Payment Entry", target_payment_entry)
    target_payment.check_permission("read")

    if target_payment.docstatus != 1:
        frappe.throw(_("Target Payment Entry must be submitted before creating intercompany JVs."))
    if not target_payment.is_intercompany_collection_payment():
        frappe.throw(_("Payment Entry is not an intercompany collection payment."))
    if not target_payment.custom_ref_doc:
        frappe.throw(_("Payment Entry must reference the source collection Payment Entry."))
    if target_payment.get("custom_intercompany_source_journal_entry"):
        frappe.throw(_("Intercompany Journal Entry already exists for this Payment Entry."))

    return _preview_from_target_payment(target_payment)


@frappe.whitelist()
def create_intercompany_collection_journals(target_payment_entry):
    preview = get_intercompany_collection_journal_preview(target_payment_entry)
    target_payment = frappe.get_doc("Payment Entry", target_payment_entry)
    target_payment.check_permission("write")
    source_payment = frappe.get_doc("Payment Entry", target_payment.custom_ref_doc)
    controller = target_payment
    if not isinstance(controller, CustomPaymentEntry):
        controller = CustomPaymentEntry(target_payment.as_dict())

    amount = flt(target_payment.base_received_amount or target_payment.received_amount)
    source_jv = controller.make_intercompany_source_journal_entry(
        collecting_company=preview["collecting_company"],
        source_payment=source_payment,
        amount=amount,
        target_company=target_payment.company,
    )
    target_jv = controller.make_intercompany_target_journal_entry(
        cash_account=controller.get_company_cash_account(target_payment.company),
        amount=amount,
        source_jv=source_jv,
        source_payment=source_payment,
    )

    frappe.db.set_value(
        "Payment Entry",
        target_payment.name,
        {
            "custom_intercompany_source_journal_entry": source_jv.name,
            "custom_intercompany_target_journal_entry": target_jv.name,
        },
        update_modified=False,
    )
    frappe.db.commit()

    return {
        "source_journal_entry": source_jv.name,
        "target_journal_entry": target_jv.name,
        "journal_entry": source_jv.name,
    }
    
