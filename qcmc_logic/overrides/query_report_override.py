import frappe
from frappe.desk.query_report import run as core_query_report_run


HIDDEN_FIELDS_BY_REPORT = {
    "Stock Ledger": {
        "in_out_rate",
        "incoming_rate",
        "stock_value",
        "stock_value_difference",
        "valuation_rate",
    },
    "Stock Balance": {
        "bal_val",
        "in_val",
        "opening_val",
        "out_val",
        "val_rate",
    },
}


def _can_see_rate_fields() -> bool:
    return frappe.session.user == "Administrator" or "Allow Rate" in frappe.get_roles()


def _strip_rate_fields(report_result: dict, hidden_fields: set[str]) -> dict:
    columns = report_result.get("columns") or []
    rows = report_result.get("result") or []

    report_result["columns"] = [
        column for column in columns if column.get("fieldname") not in hidden_fields
    ]

    for row in rows:
        for fieldname in hidden_fields:
            if fieldname in row:
                del row[fieldname]

    return report_result


@frappe.whitelist()
def run(
    report_name,
    filters=None,
    user=None,
    ignore_prepared_report=False,
    custom_columns=None,
    is_tree=False,
    parent_field=None,
    are_default_filters=True,
):
    result = core_query_report_run(
        report_name=report_name,
        filters=filters,
        user=user,
        ignore_prepared_report=ignore_prepared_report,
        custom_columns=custom_columns,
        is_tree=is_tree,
        parent_field=parent_field,
        are_default_filters=are_default_filters,
    )

    hidden_fields = HIDDEN_FIELDS_BY_REPORT.get(report_name)
    if hidden_fields and not _can_see_rate_fields():
        result = _strip_rate_fields(result, hidden_fields)

    return result
