// Accounts Payable Voucher (Purchase Invoice) only.
// VAT Details remains reference-only; no changes to totals or GL entries.
frappe.ui.form.on("Purchase Invoice", {
    setup(frm) {
        frm.set_query("cost_center", "custom_vat_details", () => ({
            filters: { company: frm.doc.company, is_group: 0, disabled: 0 },
        }));
        frm.set_query("account_name", "custom_vat_details", () => ({
            filters: {
                root_type: "Expense",
                is_group: 0,
                company: frm.doc.company,
                disabled: 0,
            },
        }));
    },
});






