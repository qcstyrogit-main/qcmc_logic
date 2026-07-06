import frappe


USER_BACKGROUND_JOBS = {
	"frappe.core.doctype.user.user.create_contact",
	"frappe.core.doctype.user.user.update_gravatar",
}


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
