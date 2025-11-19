import frappe

@frappe.whitelist()
def get_designations_from_custom_staffing_plan(doctype, txt, searchfield, start, page_len, filters):
    """Return designations linked to the selected Staffing Plan (for Job Requisition filter)."""
    staffing_plan = filters.get("custom_staffing_plan")
    additional_manpower = filters.get("custom_additional_manpower")

    if not staffing_plan:
        return []

    # Normalize additional_manpower to boolean
    # Handles cases like True/False, 1/0, "1"/"0", "true"/"false"
    additional_manpower = (
        str(additional_manpower).lower() in ("1", "true", "yes", "on")
    )

    # Build filters dynamically
    conditions = {"parent": staffing_plan}
    if not additional_manpower:  # Only filter by vacancies if unchecked
        conditions["vacancies"] = (">", 0)

    designations = frappe.db.get_all(
        "Staffing Plan Detail",
        filters=conditions,
        pluck="designation"
    )

    txt = (txt or "").lower()
    return [(d,) for d in designations if txt in d.lower()]
