from __future__ import annotations

import frappe
from frappe import _
from frappe.desk.search import validate_and_sanitize_search_inputs
from frappe.model.document import Document
from frappe.utils import add_days, getdate


PLAN_LENGTH_DAYS = 14


class WeeklyProductionPlan(Document):
	def autoname(self):
		self._set_computed_values()
		self.name = make_record_no(self.section, self.start_date)

	def validate(self):
		self._set_computed_values()
		validate_section_company(self.company, self.section)
		self._validate_scheduled_items()
		self._populate_scheduled_item_details()
		self._populate_machine_schedule()

	def _validate_scheduled_items(self):
		for row in self.get("machine_schedule"):
			for fieldname, label in (("second_item", _("Item 1")), ("third_item", _("Item 2"))):
				item_code = row.get(fieldname)
				if item_code and not item_has_active_bom_for_machine(item_code, row.machine):
					frappe.throw(
						_("Row {0}: {1} must be an FG item with an active submitted BOM for machine {2}.").format(
							row.idx, label, frappe.bold(row.machine)
						)
					)

		for table_field, label in (("item_1_schedule", _("Item 1")), ("item_2_schedule", _("Item 2"))):
			for row in self.get(table_field):
				if row.product_code and not item_has_active_bom_for_machine(row.product_code, row.machine):
					frappe.throw(
						_("{0}, row {1}: {2} must have an active submitted BOM for machine {3}.").format(
							label, row.idx, row.product_code, frappe.bold(row.machine)
						)
					)

	def _populate_scheduled_item_details(self):
		for table_field in ("item_1_schedule", "item_2_schedule"):
			for row in self.get(table_field):
				details = get_item_production_details(row.product_code, row.machine, check_permission=False)
				for fieldname in ("product_description", "cavs", "soph", "std_weight_gm", "cycle_time"):
					row.set(fieldname, details.get(fieldname))
				hours = (row.get("plan_hrs") or 0) if table_field == "item_1_schedule" else 24
				row.daily_volume_qty = hours * (row.soph or 0)
				row.daily_volume_kgs = (row.daily_volume_qty or 0) * (row.std_weight_gm or 0) / 1000

	def _set_computed_values(self):
		if not self.start_date:
			return

		self.end_date = add_days(self.start_date, PLAN_LENGTH_DAYS - 1)
		if self.section:
			self.record_no = make_record_no(self.section, self.start_date)

	def _populate_machine_schedule(self):
		if not self.start_date or not self.section:
			self.set("machine_schedule", [])
			return

		workstations = get_section_workstations(self.section)
		if not workstations:
			frappe.throw(
				_("No enabled Workstations are assigned to Plant Floor {0}.").format(
					frappe.bold(self.section)
				)
			)

		# Keep the planner's saved choices when validation rebuilds the generated
		# machine/date matrix.  The live Sales Order candidates are deliberately
		# not fields in the document and are fetched by the client when a row opens.
		saved_slots = {}
		for row in self.get("machine_schedule"):
			if not row.machine or not row.plan_date:
				continue
			saved_slots.setdefault((row.machine, getdate(row.plan_date)), []).append({
				"second_item": row.second_item,
				"second_item_description": row.second_item_description,
				"third_item": row.third_item,
				"third_item_description": row.third_item_description,
			})

		self.set("machine_schedule", [])
		for workstation in workstations:
			for day_offset in range(PLAN_LENGTH_DAYS):
				plan_date = add_days(self.start_date, day_offset)
				saved_rows = saved_slots.get((workstation, getdate(plan_date))) or [{}]
				for saved_row in saved_rows:
					self.append("machine_schedule", {
						"machine": workstation,
						"plan_date": plan_date,
						**saved_row,
					})


def make_record_no(section: str, start_date: str) -> str:
	"""Build IDs like CPS101926 from a section and 2026-10-19."""
	if not section or not start_date:
		frappe.throw(_("Section and Start Date are required to create the Record No."))

	section_code = "".join(character for character in section.upper() if character.isalnum())
	return f"{section_code}{getdate(start_date).strftime('%m%d%y')}"


def get_section_workstations(section: str) -> list[str]:
	return frappe.get_all(
		"Workstation",
		filters={"plant_floor": section, "disabled": 0},
		pluck="name",
		order_by="name asc",
	)


def validate_section_company(company: str, section: str) -> None:
	if not company or not section:
		return

	section_company = frappe.db.get_value("Plant Floor", section, "company")
	if not section_company:
		frappe.throw(
			_("Plant Floor {0} does not have a Company assigned.").format(
				frappe.bold(section)
			)
		)
	if section_company != company:
		frappe.throw(
			_("Plant Floor {0} belongs to Company {1}, not {2}.").format(
				frappe.bold(section), frappe.bold(section_company), frappe.bold(company)
			)
		)


def item_has_active_bom_for_machine(item_code: str, machine: str) -> bool:
	"""Match either the BOM header machine or a workstation on its operation rows."""
	return bool(
		frappe.db.sql(
			"""
			select bom.name
			from `tabBOM` bom
			where bom.item = %(item_code)s
				and bom.docstatus = 1
				and bom.is_active = 1
				and (
					bom.custom_machine = %(machine)s
					or exists (
						select 1
						from `tabBOM Operation` operation
						where operation.parent = bom.name
							and operation.parenttype = 'BOM'
							and operation.workstation = %(machine)s
					)
				)
			limit 1
			""",
			{"item_code": item_code, "machine": machine},
		)
	)


@frappe.whitelist()
def get_item_production_details(item_code: str, machine: str, check_permission: bool = True) -> dict:
	if check_permission and not frappe.has_permission("Weekly Production Plan", "read"):
		frappe.throw(_("Not permitted to read Weekly Production Plans."), frappe.PermissionError)
	if not item_code or not machine:
		return {}

	bom = frappe.db.sql(
		"""
		select
			bom.name,
			bom.custom_number_of_cavity as cavs,
			bom.custom_soph as soph,
			bom.custom_rate_per_minute as cycle_time
		from `tabBOM` bom
		where bom.item = %(item_code)s
			and bom.docstatus = 1
			and bom.is_active = 1
			and (
				bom.custom_machine = %(machine)s
				or exists (
					select 1 from `tabBOM Operation` operation
					where operation.parent = bom.name
						and operation.parenttype = 'BOM'
						and operation.workstation = %(machine)s
				)
			)
		order by bom.is_default desc, bom.modified desc
		limit 1
		""",
		{"item_code": item_code, "machine": machine},
		as_dict=True,
	)
	if not bom:
		return {}

	item = frappe.db.get_value(
		"Item", item_code, ["item_name", "description", "weight_per_unit"], as_dict=True
	) or {}
	return {
		"bom": bom[0].name,
		"product_description": item.get("description") or item.get("item_name"),
		"cavs": bom[0].cavs,
		"soph": bom[0].soph,
		"std_weight_gm": item.get("weight_per_unit"),
		"cycle_time": bom[0].cycle_time,
	}
@frappe.whitelist()
def get_machine_schedule(company: str, section: str, start_date: str) -> dict:
	if not company or not section or not start_date:
		return {"end_date": None, "record_no": None, "rows": []}

	validate_section_company(company, section)
	workstations = get_section_workstations(section)
	rows = [
		{"machine": workstation, "plan_date": add_days(start_date, day_offset)}
		for workstation in workstations
		for day_offset in range(PLAN_LENGTH_DAYS)
	]
	return {
		"end_date": add_days(start_date, PLAN_LENGTH_DAYS - 1),
		"record_no": make_record_no(section, start_date),
		"rows": rows,
	}


@frappe.whitelist()
def get_possible_sales_order_items(machine: str) -> list[dict]:
	"""Return live, unsaved SO candidates whose FG BOM is assigned to a machine."""
	if not frappe.has_permission("Weekly Production Plan", "read"):
		frappe.throw(_("Not permitted to read Weekly Production Plans."), frappe.PermissionError)
	if not machine:
		return []

	return frappe.db.sql(
		"""
		select
			so.name as sales_order,
			so.transaction_date as sales_order_date,
			so.docstatus,
			so.status,
			soi.item_code,
			soi.qty - coalesce(soi.delivered_qty, 0) as remaining_qty,
			coalesce(nullif(item.description, ''), item.item_name) as description
		from `tabSales Order` so
		inner join `tabSales Order Item` soi on soi.parent = so.name
		inner join `tabItem` item on item.name = soi.item_code
		where so.docstatus < 2
			and (so.docstatus = 0 or so.status in ('To Deliver and Bill', 'To Deliver'))
			and item.disabled = 0
			and coalesce(soi.delivered_qty, 0) < soi.qty
			and exists (
				select 1
				from `tabBOM` bom
				where bom.item = soi.item_code
					and bom.docstatus = 1
					and bom.is_active = 1
					and (
						bom.custom_machine = %(machine)s
						or exists (
							select 1
							from `tabBOM Operation` operation
							where operation.parent = bom.name
								and operation.parenttype = 'BOM'
								and operation.workstation = %(machine)s
						)
					)
			)
		order by so.transaction_date asc, so.name asc, soi.idx asc
		""",
		{"machine": machine},
		as_dict=True,
	)


@frappe.whitelist()
@validate_and_sanitize_search_inputs
def get_machine_fg_items(
	doctype: str,
	txt: str,
	searchfield: str,
	start: int,
	page_len: int,
	filters: dict | None = None,
) -> list[list]:
	"""Link-field options limited to FG items with a BOM for the row's machine."""
	machine = (filters or {}).get("machine")
	if not machine:
		return []

	return frappe.db.sql(
		"""
		select distinct item.name, item.description
		from `tabItem` item
		inner join `tabBOM` bom on bom.item = item.name
		where bom.docstatus = 1
			and bom.is_active = 1
			and item.disabled = 0
			and (
				bom.custom_machine = %(machine)s
				or exists (
					select 1
					from `tabBOM Operation` operation
					where operation.parent = bom.name
						and operation.parenttype = 'BOM'
						and operation.workstation = %(machine)s
				)
			)
			and (
				item.name like %(txt)s
				or item.item_name like %(txt)s
				or item.description like %(txt)s
			)
		order by item.name
		limit %(start)s, %(page_len)s
		""",
		{
			"machine": machine,
			"txt": f"%{txt}%",
			"start": start,
			"page_len": page_len,
		},
	)
