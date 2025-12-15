import frappe
from hrms.hr.doctype.appraisal.appraisal import Appraisal

class CustomAppraisal(Appraisal):
    
    def set_manual_rating_status(self):
        """
        Helper method to set rate_goals_manually based on the Appraisal Cycle.
        This logic is similar to the original set_kra_evaluation_method but 
        can be called explicitly when needed, not just on validate.
        """
        if self.appraisal_cycle:
            kra_evaluation_method = frappe.db.get_value(
                "Appraisal Cycle", self.appraisal_cycle, "kra_evaluation_method"
            )
            
            # Set rate_goals_manually to 1 (True) if the method is "Manual Rating", 
            # otherwise set it to 0 (False).
            if kra_evaluation_method == "Manual Rating":
                self.rate_goals_manually = 1
            else:
                self.rate_goals_manually = 0
        else:
            self.rate_goals_manually = 0 # Default to 0 if no cycle is selected

    @frappe.whitelist()
    def set_appraisal_template(self):
        """
        Overrides the core method. First sets the KRA evaluation method based 
        on the cycle, then gets the template, then sets KRAs/Ratings.
        """
        if not self.appraisal_cycle:
            return

        # 1. Set the manual rating status first (Crucial step)
        self.set_manual_rating_status()
        
        # 2. Get the template value from Appraisee table in the Appraisal Cycle
        appraisal_template = frappe.db.get_value(
            "Appraisee",
            {"employee": self.employee, "parent": self.appraisal_cycle},
            "appraisal_template",
        )

        if appraisal_template:
            self.appraisal_template = appraisal_template
        
        # 3. Call the logic to set KRAs and Rating Criteria, which now uses the 
        #    updated self.rate_goals_manually value.
        self.set_kras_and_rating_criteria()


    @frappe.whitelist()
    def set_kras_and_rating_criteria(self):
        """
        Uses the base class implementation for most of the logic, but we need 
        to ensure our custom fields are appended if rate_goals_manually is set.
        """
        if not self.appraisal_template:
            return

        self.set("appraisal_kra", [])
        self.set("self_ratings", [])
        self.set("goals", [])

        template = frappe.get_doc("Appraisal Template", self.appraisal_template)

        for entry in template.goals:
            # table_name is determined by the crucial self.rate_goals_manually field
            table_name = "goals" if self.rate_goals_manually else "appraisal_kra"

            if self.rate_goals_manually:
                self.append(
                    table_name,
                    {
                        "kra": entry.key_result_area,
                        "custom_competency": entry.custom_competency,
                        "custom_kpi": entry.custom_performance_indicator,
                        "custom_targetmeasure": entry.custom_targetmeasure,
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

        return self