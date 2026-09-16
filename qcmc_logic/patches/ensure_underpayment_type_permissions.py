import frappe

from qcmc_logic.patches.add_payment_entry_underpayment_breakdown import (
	ensure_underpayment_type_permissions,
)


def execute():
	ensure_underpayment_type_permissions()
	frappe.clear_cache(doctype="Underpayment Type")
