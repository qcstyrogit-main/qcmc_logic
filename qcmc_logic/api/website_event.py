import frappe


@frappe.whitelist(allow_guest=True)
def get_website_events(limit=9):
    """Return published Website Event cards for the landing page."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 9

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
            modified
        FROM `tabWebsite Event`
        WHERE
            published = 1
        ORDER BY
            sort_order ASC,
            event_date DESC,
            modified DESC
        LIMIT %(limit)s
        """,
        {"limit": limit},
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
        })

    return results
