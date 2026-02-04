import frappe
from frappe.auth import LoginManager
from frappe.utils import now_datetime

@frappe.whitelist(allow_guest=True)
def login(username, password):
    try:
        login_manager = LoginManager()
        login_manager.authenticate(user=username, pwd=password)
        login_manager.post_login()

        frappe.db.commit()

        return {
            "success": True,
            "message": "Login successful",
            "user": frappe.session.user,
            "sid": frappe.session.sid
        }

    except frappe.AuthenticationError:
        frappe.clear_messages()
        return {
            "success": False,
            "message": "Invalid username or password"
        }

@frappe.whitelist()
def create_employee_checkin(
    log_type="IN",
    latitude=None,
    longitude=None,
    device_id=None,
    skip_auto_attendance=0
):
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("Not allowed", frappe.PermissionError)

    log_type = (log_type or "IN").upper()
    if log_type not in ("IN", "OUT"):
        frappe.throw("Invalid log_type. Use IN or OUT.")

    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if not employee:
        frappe.throw("No Employee linked to this user")

    doc = frappe.new_doc("Employee Checkin")
    doc.employee = employee
    doc.log_type = log_type
    doc.time = now_datetime()
    doc.device_id = device_id
    doc.skip_auto_attendance = int(skip_auto_attendance)

    doc.latitude = latitude
    doc.longitude = longitude

    doc.insert()
    frappe.db.commit()

    return {
        "success": True,
        "checkin": doc.name,
        "employee": employee,
        "time": doc.time,
        "latitude": latitude,
        "longitude": longitude
    }
