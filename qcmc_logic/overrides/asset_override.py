import frappe
from erpnext.assets.doctype.asset.asset import Asset

class CustomAsset(Asset):
    def validate(self):
        # Your custom validation logic (optional)
        self.validate_item()
        super().validate()
        #self.set_status()
    def validate_item(self):
        # Override this method to allow your custom logic
        item = frappe.get_doc("Item", self.item_code)
        
        if not item.get("is_fixed_asset") and not item.get("custom_is_asset_item"):
            frappe.throw(f"Item {self.item_code} must be marked as Fixed Asset or Custom Asset Item")
        
        if item.disabled:
            frappe.throw(f"Item {self.item_code} is disabled")
        
        if item.has_variants:
            frappe.throw("Asset cannot be created from a template item")

        #if item.is_stock_item and item.is_fixed_asset:
         #   frappe.throw("Item cannot be both stock item and fixed asset item")

        if item.is_stock_item and not item.get("custom_is_asset_item"): #not item.custom_is_asset_item:
            frappe.throw("Stock Item must also be marked as Custom Asset Item")

    def before_save(self):

        if not self.custodian:
            self.custom_custodian_name = ""
            self.department = ""

        else:
            employee = frappe.db.get_value(
                "Employee",
                self.custodian,
                ["employee_name", "custom_location", "department"],
                as_dict=True
            )

            if employee:
                self.custom_custodian_name = employee.employee_name
                self.location = employee.custom_location
                self.department = employee.department

        # Scrapped logic
        if self.status == "Scrapped":
            old_doc = self.get_doc_before_save()
            if old_doc and old_doc.status != "Scrapped":
                self.workflow_state = "Scrapped"

                
    #def custom_validate_item(self):
        # Instead of this:
        # self.validate_item()
        # Add your own condition
     #   if not self.item_code:
 #           frappe.throw("Item Code is required")
#
        # Example: check your custom field instead of is_fixed_asset
      #  item = frappe.get_doc("Item", self.item_code)
       # if not item.get("custom_is_asset_item") and not item.get("is_fixed_asset"):
        #    frappe.throw(f"Item {self.item_code} must be marked as Custom Asset Item")
