from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


APPROVED_PRODUCTION_WAREHOUSES = {
	"RMFS - Guyong",
	"Recycling - Guyong",
	"RMFS - Sta Clara",
	"Recycling - Sta Clara",
	"Recycling - MC1",
	"Recycling - MC2",
	"RMFS - MC1",
	"RMFS - MC2",
}


class ProductionPlantilla(Document):
	def validate(self):
		self.production_position = (self.production_position or "").strip()
		self._validate_positive_values()
		self._validate_effective_dates()
		validate_warehouse(self.company, self.warehouse)
		validate_section_machine(self.warehouse, self.section, self.machine)
		self._validate_unique_plantilla_id()
		self._validate_unique_slot()

	def _validate_positive_values(self):
		if not self.plantilla_id or self.plantilla_id < 1:
			frappe.throw(_("Plantilla ID must be a positive whole number."))
		if not self.plantilla_slot or self.plantilla_slot < 1:
			frappe.throw(_("Plantilla Slot must be a positive whole number."))

	def _validate_effective_dates(self):
		if self.effective_from and self.effective_to:
			if getdate(self.effective_to) < getdate(self.effective_from):
				frappe.throw(_("Effective To cannot be earlier than Effective From."))

	def _validate_unique_plantilla_id(self):
		existing = frappe.db.exists(
			"Production Plantilla",
			{
				"warehouse": self.warehouse,
				"plantilla_id": self.plantilla_id,
				"name": ("!=", self.name or ""),
			},
		)
		if existing:
			frappe.throw(
				_("Plantilla ID {0} already exists for Warehouse {1}.").format(
					frappe.bold(self.plantilla_id),
					frappe.bold(self.warehouse),
				)
			)

	def _validate_unique_slot(self):
		rows = frappe.get_all(
			"Production Plantilla",
			filters={
				"warehouse": self.warehouse,
				"section": self.section,
				"machine": self.machine,
				"plantilla_slot": self.plantilla_slot,
				"name": ("!=", self.name or ""),
			},
			fields=["name", "production_position"],
		)
		position_key = self.production_position.casefold()
		if any((row.production_position or "").strip().casefold() == position_key for row in rows):
			frappe.throw(
				_(
					"Production Position {0}, Slot {1} already exists for this Warehouse, Section, and Machine."
				).format(
					frappe.bold(self.production_position),
					frappe.bold(self.plantilla_slot),
				)
			)


def validate_warehouse(company: str, warehouse: str):
	warehouse_row = frappe.db.get_value(
		"Warehouse",
		warehouse,
		["warehouse_name", "company", "disabled"],
		as_dict=True,
	)
	if not warehouse_row:
		frappe.throw(_("Warehouse {0} does not exist.").format(frappe.bold(warehouse)))
	if warehouse_row.disabled:
		frappe.throw(_("Warehouse {0} is disabled.").format(frappe.bold(warehouse)))
	if warehouse_row.company != company:
		frappe.throw(
			_("Warehouse {0} does not belong to Company {1}.").format(
				frappe.bold(warehouse),
				frappe.bold(company),
			)
		)
	if warehouse_row.warehouse_name not in APPROVED_PRODUCTION_WAREHOUSES:
		frappe.throw(
			_("Warehouse {0} is not approved for production employee scheduling.").format(
				frappe.bold(warehouse_row.warehouse_name)
			)
		)


def validate_section_machine(warehouse: str, section: str, machine: str):
	plant_floor = frappe.db.get_value(
		"Plant Floor",
		section,
		["warehouse", "company"],
		as_dict=True,
	)
	if not plant_floor:
		frappe.throw(_("Section {0} does not exist.").format(frappe.bold(section)))
	if plant_floor.warehouse and plant_floor.warehouse != warehouse:
		frappe.throw(
			_("Section {0} does not belong to Warehouse {1}.").format(
				frappe.bold(section),
				frappe.bold(warehouse),
			)
		)

	workstation = frappe.db.get_value(
		"Workstation",
		machine,
		["plant_floor", "warehouse", "disabled"],
		as_dict=True,
	)
	if not workstation:
		frappe.throw(_("Machine {0} does not exist.").format(frappe.bold(machine)))
	if workstation.disabled:
		frappe.throw(_("Machine {0} is disabled.").format(frappe.bold(machine)))
	if workstation.plant_floor and workstation.plant_floor != section:
		frappe.throw(
			_("Machine {0} does not belong to Section {1}.").format(
				frappe.bold(machine),
				frappe.bold(section),
			)
		)
	if workstation.warehouse and workstation.warehouse != warehouse:
		frappe.throw(
			_("Machine {0} does not belong to Warehouse {1}.").format(
				frappe.bold(machine),
				frappe.bold(warehouse),
			)
		)

