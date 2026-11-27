"""One-time transition: preserve actual approved/allocated delivery work only."""
import frappe


def execute():
    if not frappe.db.has_column("SO Delivery Schedule", "endorsement_status"):
        frappe.throw("Migrate SO Delivery Schedule endorsement fields first.")
    for row in frappe.get_all("SO Delivery Schedule",
            fields=["name", "history_status", "endorsement_status", "sales_confirmed_by",
                    "logistics_confirmed_by", "confirmation_status", "current_total"]):
        if row.endorsement_status not in (None, "", "For Planning"):
            continue
        active_dn = frappe.db.sql("""
            SELECT dni.name FROM {0}tabDelivery Note Item{0} dni
            JOIN {0}tabDelivery Note{0} dn ON dn.name = dni.parent
            WHERE dni.custom_so_delivery_schedule = %s AND dn.docstatus IN (0,1) LIMIT 1
        """.format(chr(96)), row.name)
        if row.history_status == "Verified" and (active_dn or (
                row.confirmation_status == "Finalized" and row.sales_confirmed_by and row.logistics_confirmed_by)):
            frappe.db.set_value("SO Delivery Schedule", row.name, {
                "endorsement_status": "Endorsed",
                "endorsed_by": row.sales_confirmed_by or None,
            })
            frappe.get_doc("SO Delivery Schedule", row.name).add_comment("Info",
                "Migration preserved an existing jointly finalized or allocated schedule; no retrospective endorsement time was invented.")
        else:
            frappe.db.set_value("SO Delivery Schedule", row.name, "endorsement_status", "For Planning")
    frappe.clear_cache(doctype="SO Delivery Schedule")
    frappe.clear_cache(doctype="Page")
