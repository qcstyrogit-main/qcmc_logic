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
	# Only recognize the exact known legacy approval chain. Do not grant V2
	# roles or silently accept an ambiguous or partially configured workflow.
	legacy_chain = {
		("Draft", "Submit for Stock Confirmation", "For Stock Confirmation", "Head Office Sales User"),
		("For Stock Confirmation", "Submit For DR Printing", "For DR Printing", "Sales Coordinator"),
		("For DR Printing", "Submit for Delivery", "To Deliver and Bill", "Head Office Sales User"),
	}
	signatures = [(row.state, row.action, row.next_state, row.allowed) for row in workflow.transitions]
	legacy = not release_transitions and all(signatures.count(route) == 1 for route in legacy_chain)
	if len(release_transitions) != 1 and not legacy:
		frappe.throw(_("Expected exactly one Invoicing Clerk Draft release transition or the recognized legacy approval chain."))

	submit_transitions = [
		row for row in workflow.transitions
		if row.state == "To Deliver and Bill" and row.allowed == "Stock Confirm User"
		and row.next_state == "Completed"
	]
	if len(submit_transitions) != 1:
		frappe.throw(_("Expected exactly one Stock Confirm User Delivery Note submit transition."))

	workflow_changed = False
	if not legacy:
		release = release_transitions[0]
		if release.action != "Submit for Delivery":
			release.action = "Submit for Delivery"
			workflow_changed = True
		if release.condition != SCHEDULE_RELEASE_CONDITION:
			release.condition = SCHEDULE_RELEASE_CONDITION
			workflow_changed = True
	else:
		frappe.logger("qcmc_logic").info("Delivery Note V2 release not configured; retaining legacy approval chain")

	page = frappe.get_doc("Page", "sales-order-delivery-scheduling-workbench")
	page_roles = {row.role for row in page.roles}
	if page_roles != {"Sales Coordinator", "System Manager"} or page.title != "Sales Order Delivery Scheduling Workbench":
		page.set("roles", [{"role": "Sales Coordinator"}, {"role": "System Manager"}])
		page.title = "Sales Order Delivery Scheduling Workbench"
		page.save(ignore_permissions=True)
		frappe.clear_cache(doctype="Page")

	if workflow_changed:
		workflow.save(ignore_permissions=True)
		frappe.clear_cache(doctype="Workflow")

	# The Desk sidebar caches allowed Page names/titles in each user's cache.
	# Clear user caches after changing the Page role so navigation and route access
	# are recalculated from the updated role table.
	for user in frappe.get_all("User", filters={"enabled": 1}, pluck="name"):
		frappe.clear_cache(user=user)
