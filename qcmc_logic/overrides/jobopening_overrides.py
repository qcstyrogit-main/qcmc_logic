# your_app/overrides/job_opening.py

import frappe
from hrms.hr.doctype.job_opening.job_opening import JobOpening

class CustomJobOpening(JobOpening):
    def validate_current_vacancies(self):
        designation_counts = get_designation_counts(
            self.designation, self.company, self.name
        )

        current_count = designation_counts.get("job_openings", 0)

        if self.planned_vacancies <= current_count:
            frappe.throw(
                f"Job Openings for the designation {self.designation} are already open "
                f"or the hiring is complete as per the Staffing Plan {self.staffing_plan}"
            )