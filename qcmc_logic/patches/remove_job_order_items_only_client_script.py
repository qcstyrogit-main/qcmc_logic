import frappe


def execute():
    if frappe.db.exists("Client Script", "JobOrderItemsOnly"):
        frappe.delete_doc(
            "Client Script",
            "JobOrderItemsOnly",
            force=True,
            ignore_permissions=True,
        )
