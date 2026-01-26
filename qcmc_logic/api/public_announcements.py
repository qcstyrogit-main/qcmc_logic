import frappe
from frappe.utils import now_datetime, cint
from frappe.utils.html_utils import sanitize_html


@frappe.whitelist(allow_guest=True)
def list_active_announcements(limit=10, start=0):
    """
    Public list endpoint (paginated), returns only currently-active announcements.

    Active rules:
      - published = 1
      - publish_from is null OR publish_from <= now
      - publish_to is null OR publish_to >= now

    Sorting:
      priority DESC, publish_from DESC (nulls last-ish), modified DESC
    """
    limit = cint(limit) if limit else 10
    start = cint(start) if start else 0

    now = now_datetime()

    # Using SQL for proper date window filtering + ordering
    items = frappe.db.sql(
        """
        SELECT
            name,
            image,
            announcement,
            published,
            publish_from,
            publish_to,
            IFNULL(priority, 0) AS priority,
            modified
        FROM `tabAnnouncements`
        WHERE
            published = 1
            AND (publish_from IS NULL OR publish_from <= %(now)s)
            AND (publish_to   IS NULL OR publish_to   >= %(now)s)
        ORDER BY
            IFNULL(priority, 0) DESC,
            publish_from DESC,
            modified DESC
        LIMIT %(limit)s OFFSET %(start)s
        """,
        {"now": now, "limit": limit, "start": start},
        as_dict=True
    )

    # Total count for pagination (active only)
    total = frappe.db.sql(
        """
        SELECT COUNT(*)
        FROM `tabAnnouncements`
        WHERE
            published = 1
            AND (publish_from IS NULL OR publish_from <= %(now)s)
            AND (publish_to   IS NULL OR publish_to   >= %(now)s)
        """,
        {"now": now},
    )[0][0]

    for r in items:
        r["announcement"] = sanitize_html(r.get("announcement") or "")
        r["image"] = _make_file_url(r.get("image"))

    return {
        "server_time": str(now),
        "total": total,
        "start": start,
        "limit": limit,
        "items": items,
    }


@frappe.whitelist(allow_guest=True)
def get_announcement(name):
    """
    Public single item endpoint.
    NOTE: This does NOT enforce active window by default.
    If you want it to, tell me and I’ll lock it down.
    """
    doc = frappe.get_doc("Announcements", name)

    return {
        "name": doc.name,
        "image": _make_file_url(doc.image),
        "announcement": sanitize_html(doc.announcement or ""),
        "published": doc.published,
        "publish_from": doc.publish_from,
        "publish_to": doc.publish_to,
        "priority": doc.priority or 0,
        "modified": doc.modified,
    }


def _make_file_url(file_url):
    if not file_url:
        return None
    if file_url.startswith("http://") or file_url.startswith("https://"):
        return file_url
    return frappe.utils.get_url() + file_url
