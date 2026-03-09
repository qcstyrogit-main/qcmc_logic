import frappe
from frappe import _
from frappe.utils import cint
from hrms.hr.doctype.job_opening.job_opening import JobOpening, get_designation_counts


class CustomJobOpening(JobOpening):
    def validate_current_vacancies(self):
        if not self.staffing_plan or not self.designation or not self.company:
            return

        designation_counts = get_designation_counts(
            self.designation, self.company, self.name
        ) or {}

        current_count = cint(designation_counts.get("job_openings", 0))
        planned_vacancies = cint(self.planned_vacancies or 0)

        if planned_vacancies <= current_count:
            frappe.throw(
                _(
                    "Job Openings for the designation {0} are already open or the hiring is complete as per the Staffing Plan {1}"
                ).format(
                    frappe.bold(self.designation),
                    frappe.bold(self.staffing_plan),
                )
            )