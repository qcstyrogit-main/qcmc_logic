import frappe

def validate(doc, method):

    debug_messages = []

        

    for item in doc.items:
        if item.qty and item.total_weight:
            item.weight_per_unit = item.total_weight / item.qty
            
            
        total_weight = item.total_weight or 0 


        debug_messages.append(
            f"Item: {item.item_code} | Total: {total_weight} "
        )

    # 👇 show once after loop
    if debug_messages:
        frappe.msgprint("<br>".join(debug_messages))