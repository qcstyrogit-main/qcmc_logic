import frappe
from hrms.hr.doctype.appraisal_cycle.appraisal_cycle import AppraisalCycle

class CustomAppraisalCycle(AppraisalCycle):

    @frappe.whitelist()
    def set_employees(self):
        """Pull employees that have designation AND mapped appraisal template"""

        if not self.custom_appraisal_group:
            frappe.throw("Please select an Appraisal Group")

        employees = self.get_employees_for_appraisal()
        template_map = self.get_appraisal_template_map()

        self.set("appraisees", [])

        valid_count = 0

        for emp in employees:
            # Skip employees without designation
            if not emp.designation:
                continue

            # Get template for designation
            template = template_map.get(emp.designation)

            # Skip if no template is configured
            if not template:
                continue

            self.append(
                "appraisees",
                {
                    "employee": emp.name,
                    "employee_name": emp.employee_name,
                    "branch": emp.branch,
                    "designation": emp.designation,
                    "department": emp.department,
                    "appraisal_template": template,
                },
            )

            valid_count += 1

        if not valid_count:
            frappe.msgprint(
                "No employees with both Designation and Appraisal Template were found."
            )

        return self


    def get_employees_for_appraisal(self):
        """Employees fetched by Appraisal Group from Department"""

        departments = frappe.get_all(
            "Department",
            filters={"custom_appraisal_group": self.custom_appraisal_group},
            pluck="name"
        )
        #add here console log to check if it is working
        frappe.logger().debug(f"Departments for Appraisal Group '{self.custom_appraisal_group}': {departments}")
        if not departments:
            return []

        return frappe.db.get_all(
            "Employee",
            filters={
                "status": "Active",
                "department": ["in", departments],
            },
            fields=[
                "name",
                "employee_name",
                "branch",
                "designation",
                "department",
            ],
        )

    def get_appraisal_template_map(self):
        """
        Resolve appraisal templates per designation:
        - single template OR
        - group-based template table
        """

        appraisal_templates = frappe._dict()

        designations = frappe.get_all(
            "Designation",
            fields=["name", "appraisal_template", "custom_use_groupbased_appraisal_templates"],
        )

        for des in designations:
            template = None

            # CASE 1: Single template
            if not des.custom_use_groupbased_appraisal_templates:
                template = des.appraisal_template

            # CASE 2: Group-based template
            else:
                rows = frappe.get_all(
                    "Designation Appraisal Template",
                    filters={
                        "parent": des.name,
                        "appraisal_group": self.custom_appraisal_group,
                    },
                    fields=["appraisal_template"],
                    limit=1,
                )

                if rows:
                    template = rows[0].appraisal_template

            appraisal_templates[des.name] = template

        return appraisal_templates