import frappe
from hrms.hr.doctype.appraisal.appraisal import Appraisal

class CustomAppraisal(Appraisal):
    @frappe.whitelist()
    def set_kras_and_rating_criteria(self):
        # You can paste the original code here and modify it.
        # --- Start of pasted original code ---
        if not self.appraisal_template:
            return

        self.set("appraisal_kra", [])
        self.set("self_ratings", [])
        self.set("goals", [])

        template = frappe.get_doc("Appraisal Template", self.appraisal_template)

        for entry in template.goals:
            table_name = "goals" if self.rate_goals_manually else "appraisal_kra"

            if self.rate_goals_manually:
                self.append(
                    table_name,
                    {
                        "kra": entry.key_result_area,
                        "custom_kpi": entry.custom_performance_indicator, #added custom fields 
                        "custom_targetmeasure": entry.custom_targetmeasure, #add
                        "per_weightage": entry.per_weightage,
                    },
                )
            else:
                self.append(
                    table_name,
                    {
                        "kra": entry.key_result_area,
                        "per_weightage": entry.per_weightage,
                    },
                )


        for entry in template.rating_criteria:
            self.append(
                "self_ratings",
                {
                    "criteria": entry.criteria,
                    "per_weightage": entry.per_weightage,
                },
            )

        # --- End of pasted original code ---

        # --- Add your custom modifications or new logic here ---


        return self