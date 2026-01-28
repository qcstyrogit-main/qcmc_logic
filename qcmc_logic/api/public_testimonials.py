import frappe
from frappe.utils.verified_command import get_signed_params


@frappe.whitelist(allow_guest=True)
def list_active_testimonials():
    """
    Public API: Returns ALL active testimonials (image only)
    """

    items = frappe.get_all(
        "Testimonials",
        filters={"is_active": 1},
        fields=["name", "testimonial_image", "modified"],
        order_by="modified desc"
    )

    for r in items:
        r["testimonial_image"] = _make_file_url(r.get("testimonial_image"))

    return {
        "count": len(items),
        "items": items
    }


def _make_file_url(file_url):
    if not file_url:
        return None
    if file_url.startswith("http://") or file_url.startswith("https://"):
        return file_url
    if file_url.startswith("/private/files/"):
        return (
            frappe.utils.get_url("/api/method/frappe.utils.file_manager.download_file")
            + "?"
            + get_signed_params({"file_url": file_url})
        )
    return frappe.utils.get_url() + file_url
