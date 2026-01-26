import frappe
from frappe.utils.html_utils import sanitize_html


@frappe.whitelist(allow_guest=True)
def list_active_testimonials():
    """
    Public API: Returns ALL active testimonials
    Sorted by rating DESC, then modified DESC
    """

    items = frappe.db.sql(
        """
        SELECT
            name,
            testimonial,
            employee_image,
            employee_name,
            employee_position,
            rating,
            modified
        FROM `tabTestimonials`
        WHERE is_active = 1
        ORDER BY
            IFNULL(rating, 0) DESC,
            modified DESC
        """,
        as_dict=True
    )

    for r in items:
        # sanitize text (Small Text, but still safe)
        r["testimonial"] = sanitize_html(r.get("testimonial") or "")
        r["employee_image"] = _make_file_url(r.get("employee_image"))

    return {
        "count": len(items),
        "items": items
    }


def _make_file_url(file_url):
    if not file_url:
        return None
    if file_url.startswith("http://") or file_url.startswith("https://"):
        return file_url
    return frappe.utils.get_url() + file_url
