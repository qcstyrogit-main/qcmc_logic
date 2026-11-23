import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime


ACTIVE_STATUSES = {"Draft", "In Progress", "For Approval", "Approved"}
ALLOWED_TRANSITIONS = {
	"Draft": {"Draft", "In Progress", "For Approval", "Cancelled"},
	"In Progress": {"In Progress", "For Approval", "Cancelled"},
	"For Approval": {"For Approval", "In Progress", "Approved", "Cancelled"},
	"Approved": {"Approved"},
	"Cancelled": {"Cancelled"},
}


class ProcessCard(Document):
	def before_validate(self):
		self._apply_status_policy()

	def validate(self):
		self._validate_company_and_workstation()
		self._validate_shift_interval()
		self._validate_jobs()
		self._lock_and_check_shift_window()

	def _apply_status_policy(self):
		if self.is_new():
			self.status = self.status or "Draft"
			if self.status != "Draft":
				frappe.throw(_("A new Process Card must start in Draft status."))
			return

		previous = self.get_doc_before_save()
		if not previous:
			return
		if previous.status == "Approved" and self._business_values() != self._document_values(previous):
			frappe.throw(_("Approved Process Cards are immutable."))
		if self.status not in ALLOWED_TRANSITIONS.get(previous.status, set()):
			frappe.throw(_("Invalid Process Card status transition from {0} to {1}.").format(previous.status, self.status))
		if previous.status == "For Approval" and self.status == "Approved":
			frappe.only_for("System Manager", "Manufacturing Manager")

	def _business_values(self):
		return self._document_values(self)

	@staticmethod
	def _document_values(doc):
		return {key: doc.get(key) for key in (
			"company", "site", "workstation", "shift_date", "shift_type",
			"shift_start", "shift_end", "status", "remarks", "jobs",
		)}

	def _validate_company_and_workstation(self):
		if not self.workstation:
			return
		if not frappe.db.exists("Workstation", self.workstation):
			frappe.throw(_("Select an existing enabled Workstation."))
		workstation = frappe.get_doc("Workstation", self.workstation)
		workstation.check_permission("read")
		if workstation.disabled:
			frappe.throw(_("Select an existing enabled Workstation."))
		if self.company and not frappe.get_list("Company", filters={"name": self.company}, pluck="name", limit_page_length=1):
			frappe.throw(_("You do not have access to the selected Company."), frappe.PermissionError)
		if self.company and workstation.plant_floor:
			floor_company = frappe.db.get_value("Plant Floor", workstation.plant_floor, "company")
			if floor_company and floor_company != self.company:
				frappe.throw(_("Workstation Plant Floor does not belong to the selected Company."))
		if self.site and frappe.db.exists("Production Site", self.site):
			site = frappe.get_doc("Production Site", self.site)
			site.check_permission("read")
			if site.company != self.company:
				frappe.throw(_("Production Site does not belong to the selected Company."))
			if workstation.plant_floor and workstation.plant_floor not in {row.plant_floor for row in site.plant_floors}:
				frappe.throw(_("Workstation must belong to the selected Production Site."))
		elif self.site and workstation.plant_floor and self.site != workstation.plant_floor:
			# Backward compatibility for cards created with the original Plant Floor Data value.
			frappe.throw(_("Site must match the Workstation Plant Floor."))

	def _validate_shift_interval(self):
		if not self.shift_start or not self.shift_end:
			frappe.throw(_("Shift Start and Shift End are required."))
		if get_datetime(self.shift_end) <= get_datetime(self.shift_start):
			frappe.throw(_("Shift End must be later than Shift Start. For overnight shifts, use the next calendar date."))

	def _validate_jobs(self):
		seen = set()
		previous = self.get_doc_before_save()
		previous_job_cards = {row.job_card for row in previous.jobs} if previous else set()
		for row in self.jobs:
			if not row.job_card:
				frappe.throw(_("Every Process Card Job row must link a Job Card."))
			if row.job_card in seen:
				frappe.throw(_("Job Card {0} appears more than once on this Process Card.").format(row.job_card))
			seen.add(row.job_card)
			if not frappe.db.exists("Job Card", row.job_card):
				frappe.throw(_("Job Card {0} does not exist or is cancelled.").format(row.job_card))
			job_card = frappe.get_doc("Job Card", row.job_card)
			job_card.check_permission("read")
			if job_card.docstatus == 2 or job_card.status == "Cancelled":
				frappe.throw(_("Job Card {0} does not exist or is cancelled.").format(row.job_card))
			if not job_card.work_order or not frappe.db.exists("Work Order", job_card.work_order):
				frappe.throw(_("Job Card {0} must belong to a submitted Work Order.").format(row.job_card))
			work_order = frappe.get_doc("Work Order", job_card.work_order)
			work_order.check_permission("read")
			allow_historical = row.job_card in previous_job_cards
			if job_card.status == "Completed" and not allow_historical:
				frappe.throw(_("Job Card {0} is already completed.").format(row.job_card))
			if (
				work_order.docstatus != 1
				or work_order.status == "Cancelled"
				or (not allow_historical and work_order.status in {"Stopped", "Completed"})
			):
				frappe.throw(_("Job Card {0} must belong to a submitted Work Order.").format(row.job_card))
			if job_card.workstation != self.workstation:
				frappe.throw(_("Job Card {0} is assigned to a different Workstation.").format(row.job_card))
			if job_card.company and job_card.company != self.company:
				frappe.throw(_("Job Card {0} belongs to a different Company.").format(row.job_card))
			if work_order.company != self.company:
				frappe.throw(_("Job Card {0} Work Order belongs to a different Company.").format(row.job_card))
			has_operations = frappe.db.exists("Work Order Operation", {"parent": job_card.work_order})
			if job_card.operation_id:
				if not frappe.db.exists(
					"Work Order Operation",
					{
						"name": job_card.operation_id,
						"parent": job_card.work_order,
						"operation": job_card.operation,
					},
				):
					frappe.throw(_("Job Card {0} operation is not part of its Work Order.").format(row.job_card))
			elif has_operations:
				frappe.throw(_("Job Card {0} must identify its Work Order operation.").format(row.job_card))
			row.work_order = job_card.work_order
			row.operation = job_card.operation
			row.production_item = job_card.production_item

	def _lock_and_check_shift_window(self):
		if not self.workstation or not self.shift_start or not self.shift_end:
			return
		# Serialize all creators/editors for this workstation on an existing stable row.
		frappe.db.sql("select name from `tabWorkstation` where name=%s for update", self.workstation)
		start, end = get_datetime(self.shift_start), get_datetime(self.shift_end)
		matches = frappe.db.sql(
			"""select name, shift_start, shift_end from `tabProcess Card`
			where workstation=%s and status in (%s, %s, %s, %s) and name != %s
			and shift_start < %s and shift_end > %s for update""",
			(self.workstation, "Draft", "In Progress", "For Approval", "Approved", self.name or "", end, start),
			as_dict=True,
		)
		if matches:
			frappe.throw(_("Shift window overlaps Process Card {0} for this Workstation.").format(matches[0].name))


class ProcessCardJob(Document):
	pass
