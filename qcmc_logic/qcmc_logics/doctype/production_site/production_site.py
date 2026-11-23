import frappe
from frappe import _
from frappe.model.document import Document


class ProductionSite(Document):
	def validate(self):
		if not (set(frappe.get_roles()) & {"Manufacturing Manager", "System Manager"}):
			frappe.throw(_("Production Site setup requires a manufacturing manager."), frappe.PermissionError)
		if not frappe.has_permission("Company", "read", self.company):
			frappe.throw(_("Company access denied."), frappe.PermissionError)
		seen = set()
		for row in self.plant_floors:
			if not row.plant_floor or row.plant_floor in seen:
				frappe.throw(_("Plant Floors must be selected once per site."))
			seen.add(row.plant_floor)
			if frappe.db.get_value("Plant Floor", row.plant_floor, "company") != self.company:
				frappe.throw(_("Every Plant Floor must belong to the site's Company."))
			other = frappe.db.get_value(
				"Production Site Plant Floor",
				{"plant_floor": row.plant_floor, "parent": ["!=", self.name or ""]},
				"parent",
			)
			if other:
				frappe.throw(_("Plant Floor {0} is already assigned to site {1}.").format(row.plant_floor, other))
