"""Read-only ERPNext outbound picker smoke check. Does not save/submit any document."""
import frappe
from qcmc_logic.api.outbound_pick_scanner import _context
from qcmc_logic.api.warehouse_workflow import WorkflowError

frappe.init(site="erp.qcstyro.local", sites_path="/home/qcmc_admin/frappe-bench/sites")
frappe.connect()
frappe.set_user("Administrator")
try:
    issued = 0
    for row in frappe.get_all("Stock Entry", filters={"docstatus": 0, "stock_entry_type": "Material Issue"},
                              fields=["name", "pick_list"], limit_page_length=30):
        if not row.pick_list:
            continue
        try:
            source, pick = _context("material_issue", row.name, "Administrator")
            print("MATERIAL_ISSUE_CONTEXT_OK", source.name, pick.name, len(pick.locations), pick.docstatus)
            issued += 1
            break
        except WorkflowError as error:
            print("MATERIAL_ISSUE_CONTEXT_VALIDATION", row.name, error.code)
    if not issued:
        print("MATERIAL_ISSUE_NO_LINKED_DRAFT_SAMPLE")
    delivered = 0
    for row in frappe.get_all("Delivery Note", filters={"docstatus": 0, "is_return": 0},
                              fields=["name"], limit_page_length=45):
        try:
            source, pick = _context("delivery_note", row.name, "Administrator")
            print("DELIVERY_NOTE_CONTEXT_OK", source.name, pick.name, len(pick.locations), pick.docstatus)
            delivered += 1
            break
        except WorkflowError:
            continue
    if not delivered:
        print("DELIVERY_NOTE_NO_LINKED_DRAFT_SAMPLE")
    from qcmc_logic.api.outbound_pick_scanner import list_available_documents
    for kind in ("material_issue", "delivery_note"):
        listed = list_available_documents(kind)
        assert listed.get("success") is True, listed
        assert isinstance(listed.get("documents"), list)
        assert all(record.get("reference") and record.get("state") for record in listed["documents"])
        assert all(record.get("pick_list") for record in listed["documents"] if record.get("state") in ("scan_ready", "needs_location", "picked"))
        print("OUTBOUND_DOCUMENT_LIST_OK", kind, len(listed["documents"]))
finally:
    frappe.destroy()
