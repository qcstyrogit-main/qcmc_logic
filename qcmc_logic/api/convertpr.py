import frappe
from frappe.utils import nowdate
import json

@frappe.whitelist()
def convert_pr_to_partner(source_pr, target_company,target_warehouse, selected_items=None):
    """Convert a Material Request to a new one for a different company, keeping only selected items."""
    frappe.logger().info(f"Raw selected_items: {repr(selected_items)}")

    if not selected_items:
        frappe.throw("No items selected were sent to the server.")

    if isinstance(selected_items, str):
        try:
            if selected_items.startswith('['):
                selected_items_list = json.loads(selected_items)
            else:
                selected_items_list = json.loads(json.loads(selected_items))
        except Exception as e:
            frappe.throw(f"Error decoding selected items: {e}")
    else:
        selected_items_list = selected_items

    frappe.logger().info(f"Parsed selected_items_list: {selected_items_list}")

    source = frappe.get_doc("Material Request", source_pr)

    if source.company == target_company:
        frappe.throw("Target Company must be different from the source company.")

    new_pr = frappe.copy_doc(source)
    new_pr.company = target_company
    new_pr.set_warehouse = target_warehouse
    new_pr.name = None
    new_pr.partner_pr = source.name

    # Keep only selected items (match from source)
    new_items = []
    for src_item in source.items:
        if src_item.name in selected_items_list:
            new_item = frappe.copy_doc(src_item.as_dict())
            new_item.warehouse = target_warehouse
            new_item.name = None
            new_items.append(new_item)

    if not new_items:
        frappe.throw("No matching items found in source PR.")

    new_pr.items = new_items

    # Reset fields
    new_pr.docstatus = 0
    frappe.msgprint(f"Source workflow state: {source.workflow_state}")
    new_pr.workflow_state = "Draft"
    frappe.msgprint(f"Source status: {source.status}")
    #new_pr.status = source.status
    new_pr.amended_from = None
    new_pr.owner = frappe.session.user
    new_pr.creation = nowdate()
    new_pr.modified = nowdate()
    new_pr.modified_by = frappe.session.user

    # Save new PR
   
    new_pr.insert(ignore_permissions=True,ignore_mandatory=True)

    new_pr.flags.ignore_validate = True
    new_pr.flags.ignore_links = True
    new_pr.flags.ignore_mandatory = True
    new_pr.flags.ignore_permissions = True
    new_pr.flags.ignore_workflow = True
    
    new_pr.db_set("docstatus", 1)
    new_pr.db_set("workflow_state", source.workflow_state)
 

    # Mark converted items in source
    for i in source.items:
        if i.name in selected_items_list:
            i.db_set("custom_converted_item", 1)
    source.db_set("custom_is_converted", 1)
    
    frappe.db.commit()
    return new_pr.name