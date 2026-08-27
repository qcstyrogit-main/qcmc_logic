import frappe

from qcmc_logic.customs.payroll_role_scope import (
	employee_matches_payroll_role_scope,
	get_payroll_role_rules,
	get_payroll_role_scope,
	get_payroll_type_from_salary_structure,
)
from qcmc_logic.utils import (
    get_user_allowed_warehouses,
    has_warehouse_access,
    is_global_warehouse_access_enabled,
)
from qcmc_logic.customs.territory_access_permissions import (
    get_user_allowed_territories,
    has_territory_access,
    territory_has_permission,
    territory_permission_query,
)


WAREHOUSE_TRANSACTION_DOCTYPES = {
    "Delivery Note": {
        "fields": ["set_warehouse", "set_target_warehouse"],
        "children": {"Delivery Note Item": ["warehouse", "target_warehouse"]},
    },
    "Material Request": {
        "fields": ["set_warehouse", "set_from_warehouse"],
        "children": {"Material Request Item": ["warehouse", "from_warehouse"]},
    },
    "Pick List": {
        "children": {"Pick List Item": ["warehouse"], "Pick List Item Location": ["warehouse"]},
    },
    "POS Invoice": {
        "fields": ["set_warehouse"],
        "children": {"POS Invoice Item": ["warehouse"]},
    },
    "Purchase Invoice": {
        "fields": ["set_warehouse"],
        "children": {"Purchase Invoice Item": ["warehouse"]},
    },
    "Purchase Order": {
        "fields": ["set_warehouse"],
        "children": {"Purchase Order Item": ["warehouse"]},
    },
    "Purchase Receipt": {
        "fields": ["set_warehouse"],
        "children": {
            "Purchase Receipt Item": ["warehouse"],
            "Purchase Receipt Item Supplied": ["reserve_warehouse"],
        },
    },
    "Sales Invoice": {
        "fields": ["set_warehouse"],
        "children": {"Sales Invoice Item": ["warehouse"]},
    },
    "Sales Order": {
        "fields": ["set_warehouse"],
        "children": {"Sales Order Item": ["warehouse"]},
    },
    "Stock Entry": {
        "fields": ["from_warehouse", "to_warehouse"],
        "children": {"Stock Entry Detail": ["s_warehouse", "t_warehouse"]},
    },
    "Stock Reconciliation": {
        "children": {"Stock Reconciliation Item": ["warehouse"]},
    },
    "Subcontracting Order": {
        "fields": ["set_warehouse"],
        "children": {
            "Subcontracting Order Item": ["warehouse"],
            "Subcontracting Order Supplied Item": ["reserve_warehouse"],
        },
    },
    "Subcontracting Receipt": {
        "fields": ["set_warehouse"],
        "children": {
            "Subcontracting Receipt Item": ["warehouse", "rejected_warehouse"],
            "Subcontracting Receipt Supplied Item": ["reserve_warehouse"],
        },
    },
    "Warehouse Transfer": {
        "fields": ["source_warehouse", "target_warehouse"],
    },
}


SALARY_STRUCTURE_PAYROLL_FREQUENCY = {
    "Monthly": "Bimonthly",
    "Weekly": "Weekly",
}


def _warehouse_access_applies(user):
    return (
        user != "Administrator"
        and is_global_warehouse_access_enabled()
        and has_warehouse_access(user)
    )


def _sql_list(values):
    return ", ".join(frappe.db.escape(value) for value in values)


def _get_salary_structure_scope(user):
    if user == "Administrator":
        return None

    scope = get_payroll_role_scope(user=user)
    if not scope:
        return None

    companies = scope.get("companies") or []
    payroll_frequencies = [
        SALARY_STRUCTURE_PAYROLL_FREQUENCY.get(payroll_type)
        for payroll_type in scope.get("payroll_types", [])
    ]
    payroll_frequencies = [value for value in payroll_frequencies if value]

    if not companies or not payroll_frequencies:
        return None

    return {
        "companies": companies,
        "payroll_frequencies": payroll_frequencies,
    }


def salary_structure_permission_query(user):
    scope = _get_salary_structure_scope(user)
    if not scope:
        return ""

    table = "`tabSalary Structure`"
    companies = _sql_list(scope["companies"])
    payroll_frequencies = _sql_list(scope["payroll_frequencies"])
    return (
        f"{table}.`company` IN ({companies}) "
        f"AND {table}.`payroll_frequency` IN ({payroll_frequencies})"
    )


def salary_structure_has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    scope = _get_salary_structure_scope(user)
    if not scope:
        return True

    return (
        doc.get("company") in scope["companies"]
        and doc.get("payroll_frequency") in scope["payroll_frequencies"]
    )


def salary_structure_assignment_permission_query(user):
    if user == "Administrator":
        return ""

    rules = get_payroll_role_rules(user=user)
    if not rules:
        return ""

    conditions = []
    for rule in rules:
        employee_conditions = [
            f"employee.`company` = {frappe.db.escape(rule.get('company'))}",
            f"employee.`custom_payroll_type` = {frappe.db.escape(rule.get('payroll_type'))}",
        ]

        if rule.get("branches"):
            employee_conditions.append(f"employee.`branch` IN ({_sql_list(rule.get('branches'))})")

        if rule.get("employment_types"):
            employee_conditions.append(
                f"employee.`employment_type` IN ({_sql_list(rule.get('employment_types'))})"
            )

        payroll_frequency = SALARY_STRUCTURE_PAYROLL_FREQUENCY.get(rule.get("payroll_type"))
        salary_structure_conditions = [
            "`tabSalary Structure`.`name` = `tabSalary Structure Assignment`.`salary_structure`",
        ]
        if payroll_frequency:
            salary_structure_conditions.append(
                f"`tabSalary Structure`.`payroll_frequency` = {frappe.db.escape(payroll_frequency)}"
            )

        conditions.append(
            "("
            "EXISTS ("
            "SELECT 1 FROM `tabEmployee` employee "
            "WHERE employee.`name` = `tabSalary Structure Assignment`.`employee` "
            f"AND {' AND '.join(employee_conditions)}"
            ") "
            "AND EXISTS ("
            "SELECT 1 FROM `tabSalary Structure` "
            f"WHERE {' AND '.join(salary_structure_conditions)}"
            ")"
            ")"
        )

    return "(" + " OR ".join(conditions) + ")"


def salary_structure_assignment_has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    if user == "Administrator":
        return True

    all_rules = get_payroll_role_rules(user=user)
    if not all_rules:
        return True

    payroll_type = get_payroll_type_from_salary_structure(doc.get("salary_structure"))
    rules = [
        rule for rule in all_rules
        if not payroll_type or rule.get("payroll_type") == payroll_type
    ]
    if not rules:
        return False

    employee = _get_salary_assignment_employee(doc)
    if not employee:
        return True

    return employee_matches_payroll_role_scope(employee, rules)


def _get_salary_assignment_employee(doc):
    employee_id = doc.get("employee")
    if not employee_id:
        return None

    return frappe.db.get_value(
        "Employee",
        employee_id,
        ["name", "company", "branch", "employment_type", "custom_payroll_type"],
        as_dict=True,
    )


def _doctype_has_field(doctype, fieldname):
    return frappe.get_meta(doctype).has_field(fieldname)


def _get_existing_fields(doctype, fieldnames):
    return [fieldname for fieldname in fieldnames if _doctype_has_field(doctype, fieldname)]


def _get_transaction_config(doctype):
    config = WAREHOUSE_TRANSACTION_DOCTYPES.get(doctype) or {}
    fields = _get_existing_fields(doctype, config.get("fields", []))
    children = {}

    for child_doctype, fieldnames in (config.get("children") or {}).items():
        if not frappe.db.table_exists(child_doctype):
            continue

        existing_fields = _get_existing_fields(child_doctype, fieldnames)
        if existing_fields:
            children[child_doctype] = existing_fields

    return {"fields": fields, "children": children}


def _warehouse_transaction_permission_query(doctype, user):
    if not _warehouse_access_applies(user):
        return ""

    allowed_warehouses = get_user_allowed_warehouses(user, require_list_view=True)
    if not allowed_warehouses:
        return "1=0"

    config = _get_transaction_config(doctype)
    if not config["fields"] and not config["children"]:
        return ""

    table = f"`tab{doctype}`"
    allowed_sql = _sql_list(allowed_warehouses)
    has_allowed_conditions = []

    for fieldname in config["fields"]:
        field = f"{table}.`{fieldname}`"
        has_allowed_conditions.append(f"{field} IN ({allowed_sql})")

    for child_doctype, fieldnames in config["children"].items():
        child_table = f"`tab{child_doctype}`"
        for fieldname in fieldnames:
            child_field = f"{child_table}.`{fieldname}`"
            parent_match = f"{child_table}.parent = {table}.name"
            has_allowed_conditions.append(
                "EXISTS ("
                f"SELECT 1 FROM {child_table} "
                f"WHERE {parent_match} AND {child_field} IN ({allowed_sql})"
                ")"
            )

    if not has_allowed_conditions:
        return "1=0"

    return "(" + " OR ".join(has_allowed_conditions) + ")"


def _combined_transaction_permission_query(doctype, user):
    conditions = [
        condition
        for condition in (
            _warehouse_transaction_permission_query(doctype, user),
            territory_permission_query(doctype, user),
        )
        if condition
    ]
    return " AND ".join(f"({condition})" for condition in conditions)


def warehouse_transaction_permission_query(user):
    doctype = frappe.local.form_dict.get("doctype")
    if not doctype:
        return ""

    return _warehouse_transaction_permission_query(doctype, user)


def delivery_note_permission_query(user):
    return _combined_transaction_permission_query("Delivery Note", user)


def material_request_permission_query(user):
    return _warehouse_transaction_permission_query("Material Request", user)


def pick_list_permission_query(user):
    return _warehouse_transaction_permission_query("Pick List", user)


def pos_invoice_permission_query(user):
    return _warehouse_transaction_permission_query("POS Invoice", user)


def purchase_invoice_permission_query(user):
    return _warehouse_transaction_permission_query("Purchase Invoice", user)


def purchase_order_permission_query(user):
    return _warehouse_transaction_permission_query("Purchase Order", user)


def purchase_receipt_permission_query(user):
    return _warehouse_transaction_permission_query("Purchase Receipt", user)


def sales_invoice_permission_query(user):
    return _combined_transaction_permission_query("Sales Invoice", user)


def sales_order_permission_query(user):
    return _combined_transaction_permission_query("Sales Order", user)


def customer_permission_query(user):
    return territory_permission_query("Customer", user)


def payment_entry_permission_query(user):
    if not has_territory_access(user):
        return ""

    allowed = get_user_allowed_territories(user)
    payment_table = "`tabPayment Entry`"
    customer_table = "`tabCustomer`"
    unrestricted_condition = (
        f"({payment_table}.`payment_type` != 'Receive' "
        f"OR {payment_table}.`party_type` != 'Customer')"
    )
    if not allowed:
        return unrestricted_condition

    allowed_sql = _sql_list(allowed)
    return (
        f"({unrestricted_condition} "
        f"OR EXISTS ("
        f"SELECT 1 FROM {customer_table} "
        f"WHERE {customer_table}.`name` = {payment_table}.`party` "
        f"AND {customer_table}.`territory` IN ({allowed_sql})"
        f"))"
    )


def payment_entry_has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    if (
        not has_territory_access(user)
        or ptype == "create"
        or not doc
        or doc.payment_type != "Receive"
        or doc.party_type != "Customer"
        or not doc.party
    ):
        return True

    require_transactions = ptype in {"write", "submit", "cancel", "delete", "amend"}
    allowed = set(get_user_allowed_territories(user, require_transactions))
    territory = frappe.db.get_value("Customer", doc.party, "territory")
    return not territory or territory in allowed


def stock_entry_permission_query(user):
    return _warehouse_transaction_permission_query("Stock Entry", user)


def stock_reconciliation_permission_query(user):
    return _warehouse_transaction_permission_query("Stock Reconciliation", user)


def subcontracting_order_permission_query(user):
    return _warehouse_transaction_permission_query("Subcontracting Order", user)


def subcontracting_receipt_permission_query(user):
    return _warehouse_transaction_permission_query("Subcontracting Receipt", user)


def work_order_permission_query(user):
    return ""


def _iter_doc_warehouse_values(doc):
    config = _get_transaction_config(doc.doctype)

    for fieldname in config["fields"]:
        warehouse = doc.get(fieldname)
        if warehouse:
            yield warehouse

    for child_doctype, fieldnames in config["children"].items():
        table_fieldnames = [
            df.fieldname
            for df in doc.meta.fields
            if df.fieldtype == "Table" and df.options == child_doctype
        ]

        for table_fieldname in table_fieldnames:
            for row in doc.get(table_fieldname) or []:
                for fieldname in fieldnames:
                    warehouse = row.get(fieldname)
                    if warehouse:
                        yield warehouse


def warehouse_transaction_has_permission(doc, ptype=None, user=None):
    if not user:
        user = frappe.session.user
    territory_allowed = territory_has_permission(doc, ptype=ptype, user=user)
    if not territory_allowed:
        return False
    if not _warehouse_access_applies(user):
        return True
    if ptype == "create":
        return True
    if not doc:
        return None

    if ptype in {None, "read", "select"}:
        allowed_warehouses = set(
            get_user_allowed_warehouses(user, require_list_view=True)
        )
    else:
        allowed_warehouses = set(get_user_allowed_warehouses(user, require_transact=True))
    if not allowed_warehouses:
        return False

    warehouses = set(_iter_doc_warehouse_values(doc))
    if not warehouses:
        return False

    if ptype in {None, "read", "select"}:
        return bool(warehouses.intersection(allowed_warehouses))

    return warehouses.issubset(allowed_warehouses)


def territory_document_has_permission(doc, ptype=None, user=None):
    return territory_has_permission(doc, ptype=ptype, user=user)


def warehouse_transfer_permission_query(user):
    if not _warehouse_access_applies(user):
        return ""

    allowed_warehouses = get_user_allowed_warehouses(user, require_list_view=True)
    if not allowed_warehouses:
        return "1=0"

    allowed_sql = _sql_list(allowed_warehouses)
    table = "`tabWarehouse Transfer`"
    return (
        f"({table}.`source_warehouse` IN ({allowed_sql}) "
        f"OR {table}.`target_warehouse` IN ({allowed_sql}))"
    )


def warehouse_transfer_has_permission(doc, ptype=None, user=None):
    if not user:
        user = frappe.session.user
    if not _warehouse_access_applies(user):
        return True
    if ptype == "create":
        return True
    if not doc:
        return None

    if ptype in {None, "read", "select"}:
        list_view_warehouses = set(
            get_user_allowed_warehouses(user, require_list_view=True)
        )
        source_list_allowed = doc.get("source_warehouse") in list_view_warehouses
        target_list_allowed = doc.get("target_warehouse") in list_view_warehouses
        return source_list_allowed or target_list_allowed

    transact_warehouses = set(get_user_allowed_warehouses(user, require_transact=True))
    source_transact_allowed = doc.get("source_warehouse") in transact_warehouses
    target_transact_allowed = doc.get("target_warehouse") in transact_warehouses

    if ptype in {"write", "submit", "cancel", "delete", "amend"}:
        if doc.get("docstatus") == 0:
            return source_transact_allowed
        if doc.get("docstatus") == 1 and target_transact_allowed:
            return True
        return source_transact_allowed

    return source_transact_allowed or target_transact_allowed


def appraisal_permission_query(user):
    roles = frappe.get_roles(user)

    # Only restrict supervisors, never managers/admins
    if "Appraisal User" not in roles or "Appraisal Manager" in roles:
        return ""

    assignment = frappe.db.get_value(
        "Appraisal Section Assignment",
        {"user": user},
        "name"
    )

    if not assignment:
        return "1=0"

    sections = frappe.get_all(
        "Appraisal Section Assignment Detail",
        filters={"parent": assignment},
        pluck="appraisal_section"
    )

    if not sections:
        return "1=0"

    sections_sql = ", ".join(frappe.db.escape(s) for s in sections)

    return f"`tabAppraisal`.custom_appraisal_section IN ({sections_sql})"
