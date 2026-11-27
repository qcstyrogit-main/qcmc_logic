"""Add V2 metadata without deleting legacy rows or activating broadened scopes."""
import frappe

def install_child():
    if not frappe.db.exists("DocType","Reorder Mapping Warehouse"):
        frappe.get_doc(dict(doctype="DocType",name="Reorder Mapping Warehouse",
            module="QCMC Logics",custom=1,istable=1,fields=[
                dict(fieldname="warehouse",label="Warehouse",fieldtype="Link",options="Warehouse",reqd=1,in_list_view=1)
            ])).insert(ignore_permissions=True)

def install_fields():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({"Item Reorder":[
        dict(fieldname="custom_reorder_mapping",label="Reorder Policy Mapping",fieldtype="Link",options="Reorder Policy Mapping",insert_after="warehouse",read_only=1),
        dict(fieldname="custom_managed_reorder",label="Managed by Reorder Management",fieldtype="Check",insert_after="custom_reorder_mapping",read_only=1,default="0"),
        dict(fieldname="custom_reorder_history",label="Calculation History",fieldtype="Link",options="Reorder Calculation History",insert_after="custom_managed_reorder",read_only=1),
        dict(fieldname="custom_reorder_excluded_mapping",label="Preserved under Reorder Mapping",fieldtype="Link",options="Reorder Policy Mapping",insert_after="custom_reorder_history",read_only=1,no_copy=1)
    ],"Material Request":[
        dict(fieldname="custom_replenishment_mapping",label="Replenishment Mapping",fieldtype="Link",options="Reorder Policy Mapping",insert_after="material_request_type",read_only=1,no_copy=1),
        dict(fieldname="custom_replenishment_history",label="Replenishment Calculation",fieldtype="Link",options="Reorder Calculation History",insert_after="custom_replenishment_mapping",read_only=1,no_copy=1)
    ]},update=True)
    migrate_legacy_scopes()


def migrate_legacy_scopes():
    from qcmc_logic.dynamic_reorder_policy import is_v2_mapping
    quarantined=set()
    # Never infer children or a broader item selection from legacy fields.
    for row in frappe.get_all("Reorder Policy Mapping",fields=["name"]):
        doc=frappe.get_doc("Reorder Policy Mapping",row.name)
        if not is_v2_mapping(doc):
            quarantined.add(doc.name)
            frappe.db.set_value("Reorder Policy Mapping",doc.name,dict(enabled=0,migration_review_required=1,
                migration_note="Legacy scope retained: " + ", ".join(k+"="+str(doc.get(k)) for k in ("item_code","item_group","warehouse","include_item_descendants","include_warehouse_descendants") if doc.get(k)) + ". Review explicitly before enabling V2."),update_modified=False)
    for row in frappe.get_all("Item Reorder Override",filters={"enabled":1},fields=["name","mapping","warehouse","legacy_scope_reviewed"]):
        if not row.mapping or row.mapping in quarantined or (row.get("warehouse") and not row.get("legacy_scope_reviewed")):
            frappe.db.set_value("Item Reorder Override",row.name,dict(enabled=0),update_modified=False)


def readiness():
    """Read-only preflight. Never installs metadata, changes settings or saves rows."""
    from qcmc_logic.dynamic_reorder_policy import is_v2_mapping, mapping_conflicts, validate_scope, mapping_warehouses
    required={
        "Reorder Policy":["demand_delivery","demand_manufacture","demand_intercompany","demand_provincial"],
        "Reorder Policy Mapping":["warehouses","replenishment_warehouse","inventory_group","inventory_type","legacy_scope_reviewed","migration_review_required","migration_note","transfer_source_warehouse"],
        "Reorder Mapping Warehouse":["warehouse"],
        "Item Reorder Override":["mapping","legacy_scope_reviewed"],
        "Reorder Calculation History":["mapping","calculation_key"],
        "Item Reorder":["custom_reorder_mapping","custom_managed_reorder","custom_reorder_history","custom_reorder_excluded_mapping"],
    }
    missing=[]
    for dt,fields in required.items():
        if not frappe.db.exists("DocType",dt):
            missing.append(dt)
        else:
            meta=frappe.get_meta(dt)
            missing.extend(dt+"."+field for field in fields if not meta.has_field(field))
    summary=dict(schema_ready=not missing,missing_metadata=missing,mappings=0,v2_mappings=0,
        legacy_scope_review_required=0,active_mapping_conflicts=[],invalid_scopes=[],
        automatic_replenishment_available=False,standard_erpnext_integration_validated=False)
    if not frappe.db.exists("DocType","Reorder Policy Mapping"):
        return summary
    classified=[]
    for row in frappe.get_all("Reorder Policy Mapping",fields=["name"]):
        mapping=frappe.get_doc("Reorder Policy Mapping",row.name)
        summary["mappings"]+=1
        if not is_v2_mapping(mapping):
            summary["legacy_scope_review_required"]+=1
        else:
            summary["v2_mappings"]+=1
            warehouses={w.name:w for w in frappe.get_all("Warehouse",filters={"name":["in",mapping_warehouses(mapping)]},
                fields=["name","company","disabled","is_group"])}
            try:
                validate_scope(mapping,warehouses)
            except ValueError as exc:
                summary["invalid_scopes"].append(dict(mapping=row.name,reason=str(exc)))
        policy=frappe.get_doc("Reorder Policy",mapping.policy)
        data=mapping.as_dict()
        data.update(inventory_group=policy.inventory_category,inventory_type=policy.inventory_type)
        for other in classified:
            if mapping_conflicts(data,other):
                summary["active_mapping_conflicts"].append([data["name"],other["name"]])
        classified.append(data)
    return summary
