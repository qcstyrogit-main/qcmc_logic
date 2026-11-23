import json
import math

import frappe
from frappe import _
from frappe.model.document import Document


KINDS = {"building", "machine", "section", "walkway", "static"}
MAX_ELEMENTS = 400


def validate_layout(data, allowed_floors):
	if isinstance(allowed_floors, str):
		allowed_floors = {allowed_floors}
	else:
		allowed_floors = set(allowed_floors)
	if not isinstance(data, dict) or set(data) != {"width", "height", "buildings"}:
		frappe.throw(_("Layout must contain width, height and buildings."))
	_validate_size(data)
	buildings = data["buildings"]
	if not isinstance(buildings, list) or len(buildings) > MAX_ELEMENTS:
		frappe.throw(_("Too many buildings in the layout."))
	ids = set()
	workstations = set()
	for building in buildings:
		_validate_element(building, "building", data, ids)
		if set(building) - {"id", "kind", "label", "x", "y", "w", "h", "color", "interior"}:
			frappe.throw(_("Unsupported building property."))
		interior = building.get("interior")
		if not isinstance(interior, dict) or set(interior) != {"width", "height", "elements"}:
			frappe.throw(_("Every building must have a valid interior."))
		_validate_size(interior)
		elements = interior["elements"]
		if not isinstance(elements, list) or len(elements) > MAX_ELEMENTS:
			frappe.throw(_("Too many interior elements."))
		for element in elements:
			_validate_element(element, element.get("kind"), interior, ids)
			if set(element) - {"id", "kind", "label", "x", "y", "w", "h", "color", "workstation"}:
				frappe.throw(_("Unsupported floor element property."))
			if element["kind"] == "building":
				frappe.throw(_("Buildings belong on the plant canvas."))
			if element["kind"] == "machine":
				workstation = element.get("workstation")
				if not isinstance(workstation, str) or not workstation or workstation in workstations:
					frappe.throw(_("Each machine needs a distinct Workstation."))
				workstations.add(workstation)
			elif element.get("workstation"):
				frappe.throw(_("Only machines can link a Workstation."))
	if workstations:
		rows = frappe.get_all("Workstation", filters={"name": ["in", list(workstations)]}, fields=["name", "plant_floor", "disabled"])
		if {row.name for row in rows if row.plant_floor in allowed_floors and not row.disabled} != workstations:
			frappe.throw(_("Machine Workstations must be enabled and belong to this Production Site."))
		for name in workstations:
			if not frappe.has_permission("Workstation", "read", name):
				frappe.throw(_("Workstation access denied."), frappe.PermissionError)


def _validate_size(container):
	for key in ("width", "height"):
		value = container.get(key)
		if type(value) not in (int, float) or not math.isfinite(value) or not 200 <= value <= 10000:
			frappe.throw(_("Layout dimensions must be between 200 and 10000."))


def _validate_element(element, kind, bounds, ids):
	if not isinstance(element, dict) or kind not in KINDS:
		frappe.throw(_("Invalid floor element."))
	if kind == "building" and element.get("kind") != "building":
		frappe.throw(_("Plant layout contains a non-building element."))
	identifier, label = element.get("id"), element.get("label")
	if not isinstance(identifier, str) or not 1 <= len(identifier) <= 80 or identifier in ids:
		frappe.throw(_("Floor elements need distinct IDs of at most 80 characters."))
	ids.add(identifier)
	if not isinstance(label, str) or not 1 <= len(label.strip()) <= 100:
		frappe.throw(_("Floor element label must be 1 to 100 characters."))
	for key, limit in (("x", bounds["width"]), ("y", bounds["height"]), ("w", bounds["width"]), ("h", bounds["height"])):
		value = element.get(key)
		if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= limit:
			frappe.throw(_("Invalid floor element geometry."))
	if element["w"] < 20 or element["h"] < 20 or element["x"] + element["w"] > bounds["width"] or element["y"] + element["h"] > bounds["height"]:
		frappe.throw(_("Floor element must fit inside its canvas."))
	color = element.get("color", "#d9e8ef")
	if not isinstance(color, str) or len(color) != 7 or color[0] != "#" or any(c not in "0123456789abcdefABCDEF" for c in color[1:]):
		frappe.throw(_("Invalid floor element color."))
	if kind == "machine" and element.get("interior"):
		frappe.throw(_("Machines cannot contain interiors."))


class ProductionFloorLayout(Document):
	def validate(self):
		if self.production_site:
			site = frappe.db.get_value("Production Site", self.production_site, ["name", "company"], as_dict=True)
			if not site or site.company != self.company:
				frappe.throw(_("Production Site and Company do not match."))
			floors = frappe.get_all("Production Site Plant Floor", filters={"parent": self.production_site}, pluck="plant_floor")
		else:
			# Preserve existing Plant Floor layouts until their site mapping is confirmed.
			floor = frappe.db.get_value("Plant Floor", self.plant_floor, ["name", "company"], as_dict=True)
			if not floor or floor.company != self.company:
				frappe.throw(_("Plant Floor and Company do not match."))
			floors = [self.plant_floor]
		if not frappe.has_permission("Company", "read", self.company):
			frappe.throw(_("Company access denied."), frappe.PermissionError)
		if not (set(frappe.get_roles()) & {"Manufacturing Manager", "System Manager"}):
			frappe.throw(_("Layout editing requires a manufacturing manager."), frappe.PermissionError)
		try:
			data = json.loads(self.layout_json or "{}")
		except (TypeError, ValueError):
			frappe.throw(_("Invalid layout JSON."))
		validate_layout(data, floors)
