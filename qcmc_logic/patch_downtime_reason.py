"""
Remove 'plant' field from Downtime Reason and delete the one duplicate record.
Run with: bench --site erp.qcstyro.local execute qcmc_logic.patch_downtime_reason.run
"""
import frappe


def run():
    _remove_plant_field()
    _delete_duplicate()
    frappe.db.commit()
    frappe.clear_cache(doctype="Downtime Reason")
    print("Done.")


def _remove_plant_field():
    dt = frappe.get_doc("DocType", "Downtime Reason")
    original_count = len(dt.fields)
    dt.fields = [f for f in dt.fields if f.fieldname != "plant"]
    if len(dt.fields) == original_count:
        print("'plant' field not found — skipping.")
        return
    dt.flags.ignore_permissions = True
    dt.save()
    # Must commit before running DDL (ALTER TABLE causes implicit commit in MariaDB)
    frappe.db.commit()
    frappe.db.sql("ALTER TABLE `tabDowntime Reason` DROP COLUMN IF EXISTS `plant`")
    print("'plant' field removed.")


def _delete_duplicate():
    # Record 88 is an exact duplicate of 22 (same description/category/subcategory, only differed by plant)
    if frappe.db.exists("Downtime Reason", "88"):
        frappe.delete_doc("Downtime Reason", "88", ignore_permissions=True, force=True)
        print("Duplicate record '88' deleted (kept '22').")
    else:
        print("Record '88' not found — already removed.")
