import frappe
from frappe.utils import getdate, today

@frappe.whitelist(allow_guest=True)
def employee_celebrations(month=None, day=None):
    """
    Public API:
    - Birthdays (date_of_birth)
    - Anniversaries (date_of_joining)

    Query params:
      ?month=1
      ?month=1&day=26
    """

    now = getdate(today())
    month = int(month) if month else now.month
    day = int(day) if day else None

    params = {"month": month}
    day_filter = ""

    if day:
        params["day"] = day
        day_filter = " AND DAY(dt)=%(day)s "

    # Birthdays
    birthdays = frappe.db.sql(
        f"""
        SELECT
            employee_name,
            department,
            designation,
            date_of_birth AS date
        FROM `tabEmployee`
        WHERE status='Active'
          AND date_of_birth IS NOT NULL
          AND MONTH(date_of_birth)=%(month)s
          {day_filter.replace("dt", "date_of_birth")}
        ORDER BY DAY(date_of_birth), employee_name
        """,
        params,
        as_dict=True
    )

    # Anniversaries
    anniversaries = frappe.db.sql(
        f"""
        SELECT
            employee_name,
            department,
            designation,
            date_of_joining AS date
        FROM `tabEmployee`
        WHERE status='Active'
          AND date_of_joining IS NOT NULL
          AND MONTH(date_of_joining)=%(month)s
          {day_filter.replace("dt", "date_of_joining")}
        ORDER BY DAY(date_of_joining), employee_name
        """,
        params,
        as_dict=True
    )

    return {
        "month": month,
        "day": day,
        "birthdays": birthdays,
        "anniversaries": anniversaries
    }
