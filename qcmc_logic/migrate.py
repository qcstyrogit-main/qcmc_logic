import frappe


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
		self.update_all_users()

	RoleProfile.on_update = on_update
	RoleProfile._qcmc_inline_update_all_users = True
