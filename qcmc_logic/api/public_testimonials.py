import frappe
from urllib.parse import urlencode


@frappe.whitelist(allow_guest=True)
def list_active_testimonials():
    """Public API: return all active employee testimonials."""

    items = frappe.get_all(
        "Testimonials",
        filters={"is_active": 1},
        fields=[
            "name",
            "testimonial",
            "employee_image",
            "employee_name",
            "employee_position",
            "rating",
            "modified",
        ],
        order_by="modified desc",
    )

    for row in items:
        image = _make_testimonial_image_url(row)
        employee_name = (row.get("employee_name") or "").strip()
        employee_position = (row.get("employee_position") or "").strip()

        # Compatibility keys consumed by the public website carousel.
        row["testimonial_image"] = image
        row["testimonial_caption"] = employee_name or row.get("name")
        row["testimonial_alt"] = (
            f"Testimonial from {employee_name}" if employee_name else "Employee testimonial"
        )
        row["employee_position"] = employee_position

    return {
        "count": len(items),
        "items": items,
    }


@frappe.whitelist(allow_guest=True)
def get_testimonial_image(name):
    """Serve only the private image belonging to an active testimonial."""
    file_url = frappe.db.get_value(
        "Testimonials",
        {"name": name, "is_active": 1},
        "employee_image",
    )
    if not file_url:
        raise frappe.PermissionError

    file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not file_name:
        raise frappe.DoesNotExistError

    file_doc = frappe.get_doc("File", file_name)
    frappe.local.response.filename = file_doc.file_name
    frappe.local.response.filecontent = file_doc.get_content()
    frappe.local.response.type = "download"
    frappe.local.response.display_content_as = "inline"


def _make_testimonial_image_url(row):
    file_url = row.get("employee_image")
    if file_url and file_url.startswith("/private/files/"):
        endpoint = frappe.utils.get_url(
            "/api/method/qcmc_logic.api.public_testimonials.get_testimonial_image"
        )
        return endpoint + "?" + urlencode({"name": row.get("name")})
    return _make_file_url(file_url)


def _make_file_url(file_url):
    """Convert relative public/private files into absolute, usable URLs."""
    if not file_url:
        return None
    if file_url.startswith("http://") or file_url.startswith("https://"):
        return file_url
    return frappe.utils.get_url() + file_url
