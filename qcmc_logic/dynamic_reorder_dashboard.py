"""Read-only operational overview. Existing Administrator-only boundary is preserved."""
import frappe
from frappe.utils import cint
from qcmc_logic.dynamic_reorder_clock import business_date
from qcmc_logic.dynamic_reorder_policy import active_on
from qcmc_logic.dynamic_reorder_replenishment import automatic_enabled, manual_enabled

@frappe.whitelist(methods=["GET"])
def overview():
    if frappe.session.user != "Administrator":
        frappe.throw("Administrator access required", frappe.PermissionError)
    settings = frappe.get_single("Reorder Settings")
    today = business_date()
    mappings = [m for m in frappe.get_all("Reorder Policy Mapping", filters={"enabled":1},
        fields=["name","enabled","effective_from","effective_to","automatic_draft_replenishment","policy"])
        if active_on(m,today) and frappe.db.get_value("Reorder Policy",m.policy,"enabled")
        and frappe.db.exists("Reorder Mapping Warehouse",{"parent":m.name,"parenttype":"Reorder Policy Mapping","parentfield":"warehouses"})]
    names = [m.name for m in mappings]
    managed = 0
    if names:
        managed = frappe.db.sql("""SELECT COUNT(DISTINCT r.parent,r.custom_reorder_mapping)
            FROM `tabItem Reorder` r JOIN `tabReorder Calculation History` h
            ON h.name=r.custom_reorder_history AND h.reorder_row=r.name
            WHERE r.custom_managed_reorder=1 AND h.status='Approved'
            AND r.parenttype='Item' AND r.parentfield='reorder_levels'
            AND r.custom_reorder_mapping IN %s""",(tuple(names),))[0][0]
    pending = frappe.db.count("Reorder Calculation History",{"status":["in",["Preview","Pending Approval","New Reorder Configuration"]],"mapping":["in",names]}) if names else 0
    legacy_pending = pending
    pending = frappe.db.sql("""SELECT COUNT(*) FROM `tabReorder Calculation Item` i
        JOIN `tabReorder Calculation Batch` b ON b.name=i.batch
        WHERE b.mapping IN %s AND i.status IN ('Pending Approval','New Configuration')""",(tuple(names),))[0][0] if names else 0
    drafts = frappe.db.count("Material Request",{"docstatus":0,"custom_replenishment_mapping":["is","set"]})
    last = frappe.get_all("Replenishment Execution History",fields=["name","status","started_at","finished_at","created"],order_by="creation desc",limit_page_length=1)
    return dict(managed=managed,pending=pending,legacy_pending=legacy_pending,drafts=drafts,active_mappings=len(names),
        automatic_mappings=sum(bool(m.automatic_draft_replenishment) for m in mappings),
        enabled=bool(settings.enabled),simulation=bool(settings.preview_only),
        mode=settings.replenishment_mode or "Disabled",
        native_enabled=bool(cint(frappe.db.get_single_value("Stock Settings","auto_indent"))),
        manual_ready=manual_enabled(),automatic_ready=automatic_enabled() and any(m.automatic_draft_replenishment for m in mappings),
        policies=frappe.db.count("Reorder Policy",{"enabled":1}),
        last_execution=last[0] if last else None)
