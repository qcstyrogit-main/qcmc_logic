import frappe
from frappe.model.mapper import get_mapped_doc
from erpnext.stock.doctype.delivery_note.delivery_note import (
    make_sales_invoice as erpnext_make_sales_invoice,
)

from qcmc_logic.api.delivery_note import apply_sales_order_pricing_to_invoice


@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None, args=None):
    sales_invoice = erpnext_make_sales_invoice(source_name, target_doc=target_doc, args=args)
    apply_sales_order_pricing_to_invoice(sales_invoice)
    return sales_invoice


@frappe.whitelist()
def make_delivery_trip(source_name, target_doc=None, kwargs=None):

    def update_stop_details(source_doc, target_doc, source_parent):
        target_doc.customer = source_parent.customer
        target_doc.address = source_parent.shipping_address_name
        target_doc.customer_address = source_parent.shipping_address
        target_doc.contact = source_parent.contact_person
        target_doc.customer_contact = source_parent.contact_display
        target_doc.grand_total = source_parent.grand_total

        delivery_notes.append(target_doc.delivery_note)

    delivery_notes = []

    doclist = get_mapped_doc(
        "Delivery Note",
        source_name,
        {
            "Delivery Note": {
                "doctype": "Delivery Trip",
                "validation": {
                    "workflow_state": ["=", "To Deliver and Bill"]
                }
            },
            "Delivery Note Item": {
                "doctype": "Delivery Stop",
                "field_map": {"parent": "delivery_note"},
                "condition": lambda item: item.parent not in delivery_notes,
                "postprocess": update_stop_details,
            },
        },
        target_doc,
    )

    return doclist


from erpnext.stock.doctype.delivery_note.delivery_note import DeliveryNote
from qcmc_logic import delivery_note_return_allocation as allocation


class CustomDeliveryNote(DeliveryNote):
    def extend(self, key, value):
        if key == 'custom_storage_allocation':
            # Frappe's lazy append reads the computed property again. Populate
            # this virtual table directly to avoid recursive property loading.
            from frappe.model.base_document import BaseDocument
            for row in value:
                BaseDocument.append(self, key, row)
            return
        return super().extend(key, value)

    @property
    def custom_storage_allocation(self):
        return allocation.get_allocation_grid_rows(self)

    def before_validate(self):
        allocation.prepare_return(self)

    def validate(self):
        super().validate()
        allocation.clear_bulk_storage_locations(self)

    def on_update(self):
        super().on_update()
        if self.docstatus == 0:
            allocation.sync_allocations(self)

    def before_submit(self):
        allocation.prepare_return(self)
        allocation.sync_allocations(self, require_complete=True)

    def on_submit(self):
        super().on_submit()
        allocation.submit_allocations(self)

    def before_cancel(self):
        from qcmc_logic.warehouse_capacity import lock_warehouses
        lock_warehouses([row.warehouse for row in self.items + (self.get('packed_items') or [])]
                        + [a.warehouse for a in allocation.linked_allocations(self.name)])
        super().before_cancel()

    def on_cancel(self):
        allocation.cancel_allocations(self)
        super().on_cancel()

    def on_trash(self):
        allocation.delete_draft_allocations(self)
        super().on_trash()
