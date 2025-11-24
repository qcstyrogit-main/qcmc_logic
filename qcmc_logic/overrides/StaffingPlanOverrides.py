import frappe
from hrms.hr.doctype.staffing_plan.staffing_plan import (
    StaffingPlan as OriginalStaffingPlan,
    get_designation_counts as original_get_designation_counts,
)
from frappe.utils.nestedset import get_descendants_of
from frappe.utils import cint, flt


class CustomStaffingPlan(OriginalStaffingPlan):
    def set_total_estimated_budget(self):
        self.total_estimated_budget = 0

        for detail in self.get("staffing_details"):
            # Set readonly fields
            self.set_number_of_positions(detail)
            designation_counts = self.get_designation_counts(detail)
            detail.current_count = designation_counts["employee_count"]
            detail.current_openings = designation_counts["job_openings"]

            detail.total_estimated_cost = 0
            if detail.number_of_positions > 0:
                if detail.vacancies and detail.estimated_cost_per_position:
                    detail.total_estimated_cost = cint(detail.vacancies) * flt(
                        detail.estimated_cost_per_position
                    )

            self.total_estimated_budget += detail.total_estimated_cost



    def get_designation_counts(self, d, department):
        """
        Override: count based on designation + company + department.
        Department taken from parent Staffing Plan.
        """
        if not department:
            return {"employee_count": 0, "job_openings": 0}

        descendant_departments = get_descendants_of("Department", department, ignore_permissions=True)
        all_departments = [department] + descendant_departments

        employee_count = frappe.db.sql(
            """
            SELECT COUNT(*)
            FROM `tabEmployee`
            WHERE designation = %s
              AND company = %s
              AND department IN %s
              AND status = 'Active'
            """,
            (d.designation, self.company, tuple(all_departments)),
        )[0][0]

        job_openings = frappe.db.count(
            "Job Opening",
            {
                "designation": d.designation,
                "status": "Open",
                "company": self.company,
                "department": ("in", all_departments),
            },
        )

        return {"employee_count": employee_count, "job_openings": job_openings}




import frappe
from hrms.hr.doctype.staffing_plan.staffing_plan import (
    StaffingPlan as OriginalStaffingPlan,
    get_designation_counts as original_get_designation_counts,
)
from frappe.utils.nestedset import get_descendants_of
from frappe.utils import cint, flt


class CustomStaffingPlan(OriginalStaffingPlan):
    # --- BYPASS DESIGNATION OVERLAP CHECK ---
    def validate_overlap(self, staffing_plan_detail):
        """
        Override default behavior:
        Do NOT block creation even if another staffing plan exists
        for the same designation.
        """
        # Simply skip the validation (no frappe.throw)
        return

    def validate_with_parent_plan(self, staffing_plan_detail):
        """
        Override default behavior:
        Do NOT validate against parent staffing plan.
        """
        return

    def validate_with_subsidiary_plans(self, staffing_plan_detail):
        """
        Override default behavior:
        Do NOT validate against subsidiary staffing plans.
        """
        return

    def get_designation_counts(self, d, job_opening=None):
        """
        Override: count based on designation + company + department.
        Department is taken from the staffing detail row, falling back to the parent Staffing Plan.
        """
        department = d.get("department") or self.department

        if not department:
            return {"employee_count": 0, "job_openings": 0}

        descendant_departments = get_descendants_of("Department", department)
        all_departments = [department] + descendant_departments

        employee_count = frappe.db.sql(
            """
            SELECT COUNT(*)
            FROM `tabEmployee`
            WHERE designation = %s
              AND company = %s
              AND department IN %s
              AND status = 'Active'
            """,
            (d.designation, self.company, tuple(all_departments)),
        )[0][0]

        filters = {
            "designation": d.designation,
            "status": "Open",
            "company": self.company,
            "department": ("in", all_departments),
        }
        if job_opening:
            filters["name"] = ("!=", job_opening)

        job_openings = frappe.db.count(
            "Job Opening",
            filters,
        )

        return {"employee_count": employee_count, "job_openings": job_openings}

    def set_total_estimated_budget(self):
        self.total_estimated_budget = 0

        for detail in self.get("staffing_details"):
            # Set readonly fields
            self.set_number_of_positions(detail)
            designation_counts = self.get_designation_counts(detail)
            detail.current_count = designation_counts["employee_count"]
            detail.current_openings = designation_counts["job_openings"]

            detail.total_estimated_cost = 0
            if detail.number_of_positions > 0:
                if detail.vacancies and detail.estimated_cost_per_position:
                    detail.total_estimated_cost = cint(detail.vacancies) * flt(
                        detail.estimated_cost_per_position
                    )

            self.total_estimated_budget += detail.total_estimated_cost


