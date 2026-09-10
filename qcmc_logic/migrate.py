import frappe


USER_BACKGROUND_JOBS = {
	"frappe.core.doctype.user.user.create_contact",
	"frappe.core.doctype.user.user.update_gravatar",
}

LENDING_COLLECTION_OFFSET_FIELDS = (
	"collection_offset_sequence_for_standard_asset",
	"collection_offset_sequence_for_sub_standard_asset",
	"collection_offset_sequence_for_written_off_asset",
	"collection_offset_sequence_for_settlement_collection",
)

LENDING_COLLECTION_OFFSET_ORDERS = (
	"Standard Collection Offset",
	"Sub Standard Collection Offset",
	"Written Off Collection Offset",
	"Settlement Collection Offset",
)


def restore_lending_collection_offset_fields():
	"""Repair stale cross-app fixtures that restore the pre-Link field schema."""
	if not frappe.db.exists("DocType", "Loan Demand Offset Order"):
		return

	for title in LENDING_COLLECTION_OFFSET_ORDERS:
		if frappe.db.exists("Loan Demand Offset Order", title):
			continue

		order = frappe.new_doc("Loan Demand Offset Order")
		order.title = title
		for demand_type in ("Penalty", "Interest", "Principal"):
			order.append("components", {"demand_type": demand_type})
		order.insert(ignore_permissions=True)

	for fieldname in LENDING_COLLECTION_OFFSET_FIELDS:
		custom_field = f"Company-{fieldname}"
		if not frappe.db.exists("Custom Field", custom_field):
			continue

		frappe.db.set_value(
			"Custom Field",
			custom_field,
			{"fieldtype": "Link", "options": "Loan Demand Offset Order"},
			update_modified=False,
		)

	frappe.clear_cache(doctype="Company")


def run_role_profile_updates_inline():
	"""Avoid stale Role Profile queue locks while importing fixtures in migrate."""
	from frappe.core.doctype.role_profile.role_profile import RoleProfile

	if getattr(RoleProfile, "_qcmc_inline_update_all_users", False):
		return

	original_on_update = RoleProfile.on_update

	def on_update(self):
		if not frappe.flags.in_migrate:
			return original_on_update(self)

		self.clear_cache()
		if self.is_locked:
			self.unlock()

		# User.save() is still required to synchronize roles from the profile, but
		# User.on_update also queues unrelated Contact and Gravatar work per user.
		# Suppress only those jobs during this migration-specific bulk update.
		original_enqueue = frappe.enqueue

		def enqueue(method, *args, **kwargs):
			if method in USER_BACKGROUND_JOBS:
				return None
			return original_enqueue(method, *args, **kwargs)

		frappe.enqueue = enqueue
		try:
			self.update_all_users()
		finally:
			frappe.enqueue = original_enqueue

	RoleProfile.on_update = on_update
	RoleProfile._qcmc_inline_update_all_users = True
