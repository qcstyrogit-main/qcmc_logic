import frappe

@frappe.whitelist()
def recalculate_staffing_plan(staffing_plan):
    """Recalculate total current positions directly via SQL (works after submit)."""
    doc = frappe.get_doc("Staffing Plan", staffing_plan)

    from_date = doc.from_date
    to_date = doc.to_date

    for d in doc.staffing_details:
        # example: count active employees with matching designation, section, etc.
        current_count = frappe.db.count(
            "Employee",
            filters={
                "designation": d.designation,
                "department": doc.department,
                "status": "Active",
            }
        )
        
        additional_count = frappe.db.sql(
            """
            SELECT COALESCE(SUM(no_of_positions), 0)
            FROM `tabJob Requisition`
            WHERE `custom_staffing_plan` = %s
              AND `custom_additional_manpower` = 1
              AND `designation` = %s
              AND `department` = %s
              AND `status` = 'Open & Approved'
              AND `posting_date` BETWEEN %s AND %s
            """,
            (staffing_plan, d.designation, doc.department, from_date, to_date),
        )[0][0]

        number_of_positions = d.number_of_positions

        # directly update the child row (bypass save validation)
        frappe.db.set_value("Staffing Plan Detail", d.name, "current_count", current_count)
        vacancies = (d.number_of_positions - current_count) + additional_count
        frappe.db.set_value("Staffing Plan Detail", d.name, "vacancies", vacancies)

        if number_of_positions < vacancies and additional_count > 0:
            number_of_positions = vacancies
            frappe.db.set_value("Staffing Plan Detail", d.name, "number_of_positions", number_of_positions)


    frappe.db.commit()
    return f"Recalculation completed successfully."
