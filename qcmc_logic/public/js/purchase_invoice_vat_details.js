// Accounts Payable Voucher (Purchase Invoice) only.
// VAT Details remains reference-only; no changes to totals or GL entries.
// Amount is VAT-inclusive. VAT Inclusive is the VAT component (12/112).
frappe.ui.form.on("Purchase Invoice", {
    refresh(frm) {
        // Give the VAT Details grid the full available form width.
        const field = frm.get_field("custom_vat_details");
        if (!field || !field.$wrapper) return;
        const $grid = field.$wrapper;
        $grid.css({ width: "100%", "max-width": "100%" });
        $grid.closest(".frappe-control").css({ width: "100%", "max-width": "100%" });
        const $column = $grid.closest(".form-column");
        if ($column.length) {
            $column.css({ flex: "0 0 100%", "max-width": "100%", width: "100%" });
            $column.siblings(".form-column").css({ flex: "0 0 100%", "max-width": "100%", width: "100%" });
        }
    },
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

frappe.ui.form.on("Purchase Invoice VAT Detail", {
    amount(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const amount = flt(row.amount);
        const vat = Math.round((amount * 12 / 112 + Number.EPSILON) * 100) / 100;
        frappe.model.set_value(cdt, cdn, "custom_vat_inclusive", vat);
        frappe.model.set_value(cdt, cdn, "custom_pv_amount", Math.round((amount - vat + Number.EPSILON) * 100) / 100);
    },
});






