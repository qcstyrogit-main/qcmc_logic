import frappe
from erpnext.stock.doctype.stock_entry import stock_entry
import erpnext.stock.utils as stock_utils

# Keep reference to original function
original_make_gl_entries = stock_entry.StockEntry.make_gl_entries

def custom_make_gl_entries(self, adv_adj=0):
    frappe.msgprint(f"Custom patch triggered for Stock Entry {self.name}")

    if self.stock_entry_type in ["Warehouse Transfer", "Material Transfer Receipt"]:
        frappe.logger().info(f"Skipping GL entries for Stock Entry {self.name}")
        return

    # Otherwise, call original
    return original_make_gl_entries(self, adv_adj=adv_adj)

# Apply monkey patch
stock_entry.StockEntry.make_gl_entries = custom_make_gl_entries

