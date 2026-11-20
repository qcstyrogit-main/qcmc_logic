"""Read-only debugging of outbound picker for a specific operator."""
import frappe
from qcmc_logic.api.outbound_pick_scanner import list_available_documents, _context
from qcmc_logic.api.warehouse_workflow import WorkflowError
USER = "mmagbojos@qcstyro.com"
frappe.init(site="erp.qcstyro.local", sites_path="/home/qcmc_admin/frappe-bench/sites")
frappe.connect()
try:
    frappe.set_user(USER)
    print("USER_EXISTS", bool(frappe.db.exists("User", USER)))
    print("ROLES", sorted(frappe.get_roles(USER)))
    for kind, doctype in [("material_issue","Stock Entry"),("delivery_note","Delivery Note")]:
        print("KIND",kind)
        for docstatus in (0, 1):
            filters={"docstatus":docstatus}
            if kind=="material_issue": filters.update({"stock_entry_type":"Material Issue"})
            else: filters["is_return"]=0
            try:
                rows=frappe.get_list(doctype, filters=filters, fields=["name","docstatus","modified"], order_by="modified desc",limit_page_length=50)
                print("VISIBLE",docstatus,len(rows),[x.name for x in rows[:12]])
            except Exception as e:
                print("VISIBLE_ERROR",str(e)[:200])
        try:
            listing=list_available_documents(kind)
            docs = listing.get("documents", [])
            from collections import Counter
            print("SCANNER_RESULT", kind, "count", len(docs), "states", dict(Counter(d.get("state") for d in docs)), "first", [(d.get("reference"),d.get("state"),d.get("pick_list")) for d in docs[:5]])
        except Exception as e:
            print("SCANNER_ERROR",type(e).__name__,str(e)[:200])
    try:
        _context("delivery_note", "MAT-DN-2026-00238", USER)
        print("SELECTED_DN_CONTEXT", "allowed")
    except Exception as exc:
        print("SELECTED_DN_CONTEXT", type(exc).__name__, str(exc)[:240])
    frappe.set_user("Administrator")
    print("ADMIN_RECENT_DELIVERIES")
    for dn in frappe.get_all("Delivery Note",filters={"docstatus":0,"is_return":0},
            fields=["name","workflow_state","company","modified"],limit_page_length=30,order_by="modified desc"):
        doc=frappe.get_doc("Delivery Note",dn.name)
        names=sorted({str(r.against_pick_list) for r in doc.items if r.against_pick_list})
        print("DN",dn.name,dn.workflow_state,names,[frappe.db.get_value("Pick List",n,"docstatus") for n in names])
    print("RECENT_ISSUES")
    for se in frappe.get_all("Stock Entry",filters={"stock_entry_type":"Material Issue","docstatus":0},
            fields=["name","pick_list","company"],limit_page_length=12):
        if not se.pick_list: continue
        rows=frappe.get_all("Pick List Item",filters={"parent":se.pick_list},fields=["item_code","warehouse","location","stock_qty"],limit_page_length=8)
        print("SE",se.name,se.pick_list,[(x.item_code,x.warehouse,x.location,x.stock_qty) for x in rows])
        for x in rows:
            if x.location:
                print("LOCATION_MASTER",x.location,frappe.db.get_value("Storage Location",x.location,["custom_warehouse","location_code","location_name"],as_dict=True))
finally:
    frappe.destroy()
