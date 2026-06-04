import frappe
from frappe.desk.query_report import run as core_query_report_run

from qcmc_logic.utils import (
    get_user_allowed_warehouses,
    is_global_warehouse_access_enabled,
)


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


def _get_column_value(row, column, index):
    if isinstance(row, dict):
        fieldname = column.get("fieldname")
        if fieldname and fieldname in row:
            return row.get(fieldname)

        label = column.get("label")
        if label and label in row:
            return row.get(label)

        return None

    if isinstance(row, (list, tuple)) and index < len(row):
        return row[index]

    return None


def _is_warehouse_column(column):
    options = column.get("options")
    fieldname = (column.get("fieldname") or "").lower()
    label = (column.get("label") or "").lower()

    return options == "Warehouse" or "warehouse" in fieldname or "warehouse" in label


def _filter_report_by_warehouse_access(report_result: dict, user=None) -> dict:
    user = user or frappe.session.user
    if user == "Administrator" or not is_global_warehouse_access_enabled():
        return report_result

    allowed_warehouses = set(get_user_allowed_warehouses(user))
    columns = report_result.get("columns") or []
    warehouse_columns = [
        (index, column)
        for index, column in enumerate(columns)
        if isinstance(column, dict) and _is_warehouse_column(column)
    ]

    if not warehouse_columns:
        return report_result

    if not allowed_warehouses:
        report_result["result"] = []
        return report_result

    filtered_rows = []
    for row in report_result.get("result") or []:
        warehouses = [
            warehouse
            for index, column in warehouse_columns
            if (warehouse := _get_column_value(row, column, index))
        ]

        if not warehouses or set(warehouses).issubset(allowed_warehouses):
            filtered_rows.append(row)

    report_result["result"] = filtered_rows
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

    result = _filter_report_by_warehouse_access(result, user=user)

    return result
