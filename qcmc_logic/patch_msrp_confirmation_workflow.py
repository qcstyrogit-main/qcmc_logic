"""
Add the Served Date / requestor confirmation loop to Machine Shop Repairs and Project:
Company setting, MSRP Rework Log child doctype, MSRP custom fields, DocPerm, workflow
states/transitions, and the requestor notification.
Run with: bench --site erp.qcstyro.local execute qcmc_logic.patch_msrp_confirmation_workflow.run
"""
import frappe

from qcmc_logic.customs.machine_shop_repairs_and_project import setup


def run():
    setup()
    frappe.db.commit()
    frappe.clear_cache()
    print("Done.")
