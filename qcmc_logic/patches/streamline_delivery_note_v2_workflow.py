"""Tighten the V2 Draft release transition while retaining legacy DN states."""

import frappe
from frappe import _


SCHEDULE_RELEASE_CONDITION = (
	"doc.items and doc.custom_dr_number and doc.custom_sales_order and "
	"not frappe.db.get_value('Delivery Note Item', "
	"{'parent': doc.name, 'custom_so_delivery_schedule': ['is', 'not set']}, 'name')"
)


def execute():
	workflow = frappe.get_doc("Workflow", "Delivery Note")
	release_transitions = [
		row for row in workflow.transitions
		if row.state == "Draft" and row.allowed == "Invoicing Clerk"
		and row.action in ("Submit for Delivery", "Release for Delivery")
	]
	if len(release_transitions) != 1:
		frappe.throw(_("Expected exactly one Invoicing Clerk Draft release transition."))

	submit_transitions = [
		row for row in workflow.transitions
		if row.state == "To Deliver and Bill" and row.allowed == "Stock Confirm User"
		and row.next_state == "Completed"
	]
	if len(submit_transitions) != 1:
		frappe.throw(_("Expected exactly one Stock Confirm User Delivery Note submit transition."))

	changed = False
	release = release_transitions[0]
	if release.action != "Submit for Delivery":
		release.action = "Submit for Delivery"
		changed = True
	if release.condition != SCHEDULE_RELEASE_CONDITION:
		release.condition = SCHEDULE_RELEASE_CONDITION
		changed = True

	page = frappe.get_doc("Page", "sales-order-delivery-scheduling-workbench")
	page_roles = {row.role for row in page.roles}
	if page_roles != {"System Manager"} or page.title != "Sales Order Delivery Scheduling Workbench":
		page.set("roles", [{"role": "System Manager"}])
		page.title = "Sales Order Delivery Scheduling Workbench"
		changed = True

	if changed:
		workflow.save(ignore_permissions=True)
		page.save(ignore_permissions=True)
		frappe.clear_cache(doctype="Workflow")
		frappe.clear_cache(doctype="Page")

	# The Desk sidebar caches allowed Page names/titles in each user's cache.
	# Clear user caches after changing the Page role so navigation and route access
	# are recalculated from the updated role table.
	for user in frappe.get_all("User", filters={"enabled": 1}, pluck="name"):
		frappe.clear_cache(user=user)
