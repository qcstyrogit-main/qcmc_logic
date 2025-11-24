import frappe
import erpnext.assets.doctype.asset.asset as asset_module

def custom_validate_item(self):
    item = frappe.get_doc("Item", self.item_code)
    
    # ✅ Auto-fill asset_category from Item's custom field if not given
    if not self.asset_category:
        custom_cat = item.get("custom_asset_cat")
        if custom_cat:
            self.asset_category = custom_cat
        else:
            frappe.throw(f"Asset Category is missing for Item {self.item_code} "
                         f"and no custom_asset_category is set on the Item")


    if not item.is_fixed_asset and not item.get("custom_is_asset_item"):
        frappe.throw(f"Item {self.item_code} must be marked as Fixed Asset or Custom Asset Item")
    
    if item.disabled:
        frappe.throw(f"Item {self.item_code} is disabled")
    
    if item.has_variants:
        frappe.throw("Asset cannot be created from a template item")
    
    # Allow stock + custom asset, only block if no custom flag
    if item.is_stock_item and not item.get("custom_is_asset_item"):
        frappe.throw("Stock Item must also be marked as Custom Asset Item")

# Replace ERPNext's method with ours
asset_module.Asset.validate_item = custom_validate_item
