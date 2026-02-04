import frappe
from frappe.utils import now_datetime


@frappe.whitelist(allow_guest=True)
def get_website_events(limit=9):
    """Return published Website Event cards for the landing page."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 9

    today = now_datetime().date()

    events = frappe.db.sql(
        """
        SELECT
            name,
            title,
            event_date,
            url,
            thumbnail,
            summary,
            sort_order,
            published,
            publish_from,
            publish_to,
            modified
        FROM `tabWebsite Event`
        WHERE
            published = 1
            AND (publish_from IS NULL OR DATE(publish_from) <= %(today)s)
            AND (publish_to   IS NULL OR DATE(publish_to)   >= %(today)s)
        ORDER BY
            sort_order ASC,
            event_date DESC,
            modified DESC
        LIMIT %(limit)s
        """,
        {"today": today, "limit": limit},
        as_dict=True,
    )

    results = []
    for item in events:
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        thumbnail = (item.get("thumbnail") or "").strip()
        summary = (item.get("summary") or "").strip()
        if not title:
            continue
        results.append({
            "name": item.get("name"),
            "title": title,
            "event_date": item.get("event_date"),
            "url": url,
            "thumbnail": thumbnail,
            "summary": summary,
            "sort_order": item.get("sort_order") or 0,
            "publish_from": item.get("publish_from"),
            "publish_to": item.get("publish_to"),
        })

    return results
