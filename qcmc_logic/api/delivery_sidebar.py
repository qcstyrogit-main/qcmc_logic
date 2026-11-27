"""Hide retired delivery report links from Frappe Desk navigation."""

RETIRED_REPORTS = frozenset({
    "Delivery Note Printing",
    "Delivery Schedule Confirmation",
    "Sales Order Delivery Scheduling",
})


RETIRED_PAGE = "sales-order-delivery-scheduling-workbench"


def hide_retired_reports(bootinfo):
    for sidebar in (bootinfo.get("workspace_sidebar_item") or {}).values():
        sidebar["items"] = [
            item for item in sidebar.get("items", [])
            if (item.get("link_type") != "Report" or item.get("link_to") not in RETIRED_REPORTS)
        ]
