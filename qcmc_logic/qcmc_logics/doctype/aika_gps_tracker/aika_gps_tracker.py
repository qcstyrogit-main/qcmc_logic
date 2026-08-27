from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.model.document import Document


class AIKAGPSTracker(Document):
	def validate(self):
		self.tracker_name = (self.tracker_name or "").strip()
		self.username = (self.username or "").strip()
		parsed = urlparse((self.server_url or "").strip())
		if parsed.scheme not in {"http", "https"} or not parsed.hostname:
			frappe.throw(_("Server URL must be a complete AIKA HTTP or HTTPS URL."))
		hostname = parsed.hostname.lower().rstrip(".")
		if hostname != "aika168.com" and not hostname.endswith(".aika168.com"):
			frappe.throw(_("Only aika168.com server hosts are permitted."))
		if parsed.scheme == "http":
			frappe.msgprint(
				_("AIKA uses unencrypted HTTP. Credentials and GPS information may be exposed in transit."),
				indicator="orange",
				alert=True,
			)
