"""Expose generic source documents without changing allocation transactions."""

import json

import frappe

from qcmc_logic.storage_allocation_source import source_reference


def execute():
    frappe.reload_doc("qcmc_logics", "doctype", "storage_allocation")
    for name in frappe.get_all("Storage Allocation", pluck="name"):
        doc = frappe.get_doc("Storage Allocation", name)
        frappe.db.set_value(
            "Storage Allocation", name, source_reference(doc), update_modified=False
        )

    fields = frappe.db.get_value("List View Settings", "Storage Allocation", "fields")
    if fields:
        columns = json.loads(fields)
        for column in columns:
            if column.get("fieldname") == "purchase_receipt":
                column.update(fieldname="source_document", label="Source Document")
        frappe.db.set_value(
            "List View Settings", "Storage Allocation", "fields",
            json.dumps(columns), update_modified=False,
        )
    frappe.clear_cache(doctype="Storage Allocation")
