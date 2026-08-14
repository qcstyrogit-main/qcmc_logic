import frappe
from frappe import _
from frappe.utils import nowdate

from erpnext.manufacturing.doctype.work_order.work_order import (
    check_if_scrap_warehouse_mandatory,
)
from erpnext.controllers.queries import bom as erpnext_bom_query

from qcmc_logic.utils import (
    get_default_company_from_role_profile_default_warehouse,
    get_user_allowed_warehouses,
    has_warehouse_access,
    is_global_warehouse_access_enabled,
)


WORK_ORDER_PARENT_WAREHOUSE_FIELDS = (
    "source_warehouse",
    "wip_warehouse",
    "fg_warehouse",
    "scrap_warehouse",
)

WORK_ORDER_CHILD_WAREHOUSE_FIELDS = {
    "Work Order Item": {
        "parentfield": "required_items",
        "fields": ("source_warehouse",),
    },
    "Work Order Operation": {
        "parentfield": "operations",
        "fields": ("source_warehouse", "wip_warehouse", "fg_warehouse"),
    },
}

JOB_CARD_PARENT_WAREHOUSE_FIELDS = (
    "source_warehouse",
    "wip_warehouse",
    "target_warehouse",
)

JOB_CARD_CHILD_WAREHOUSE_FIELDS = {
    "Job Card Item": {
        "parentfield": "items",
        "fields": ("source_warehouse",),
    },
}


def manufacturing_warehouse_access_applies(user=None):
    user = user or frappe.session.user
    return (
        user != "Administrator"
        and is_global_warehouse_access_enabled()
        and has_warehouse_access(user)
    )


def get_bom_company_scope(user=None, fallback_company=None):
    user = user or frappe.session.user
    if user == "Administrator":
        return fallback_company

    return (
        get_default_company_from_role_profile_default_warehouse(user)
        or fallback_company
    )


def bom_permission_query(user):
    company = get_bom_company_scope(user=user)
    if not company:
        return ""

    return f"`tabBOM`.`company` = {frappe.db.escape(company)}"


def work_order_permission_query(user):
    if not manufacturing_warehouse_access_applies(user):
        return ""

    allowed_warehouses = get_user_allowed_warehouses(user, require_list_view=True)
    if not allowed_warehouses:
        return "1=0"

    allowed_sql = _sql_list(allowed_warehouses)
    return _work_order_sql_conditions(allowed_sql, parent_table="`tabWork Order`")


def job_card_permission_query(user):
    if not manufacturing_warehouse_access_applies(user):
        return ""

    allowed_warehouses = get_user_allowed_warehouses(user, require_list_view=True)
    if not allowed_warehouses:
        return "1=0"

    allowed_sql = _sql_list(allowed_warehouses)
    job_card_query = _job_card_sql_conditions(allowed_sql, parent_table="`tabJob Card`")
    work_order_query = _work_order_sql_conditions(allowed_sql, parent_table="`tabWork Order`")
    return (
        f"{job_card_query} AND "
        "EXISTS ("
        "SELECT 1 FROM `tabWork Order` "
        "WHERE `tabWork Order`.`name` = `tabJob Card`.`work_order` "
        f"AND {work_order_query}"
        ")"
    )


def work_order_has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    if not manufacturing_warehouse_access_applies(user) or ptype == "create":
        return True
    if not doc:
        return None

    require_list_view = ptype in {None, "read", "select"}
    allowed = set(
        get_user_allowed_warehouses(
            user,
            require_transact=not require_list_view,
            require_list_view=require_list_view,
        )
    )
    if not allowed:
        return False

    warehouses = _get_work_order_warehouses(doc)
    return not warehouses or warehouses.issubset(allowed)


def job_card_has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    if not manufacturing_warehouse_access_applies(user) or ptype == "create":
        return True
    if not doc:
        return None

    allowed = set(
        get_user_allowed_warehouses(
            user,
            require_transact=ptype not in {None, "read", "select"},
            require_list_view=ptype in {None, "read", "select"},
        )
    )
    if not allowed:
        return False

    warehouses = _get_job_card_warehouses(doc)
    work_order = doc.get("work_order")
    if work_order:
        warehouses.update(_get_work_order_warehouses(work_order))

    return not warehouses or warehouses.issubset(allowed)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def bom_query(doctype, txt, searchfield, start, page_len, filters):
    if isinstance(filters, str):
        filters = frappe.parse_json(filters)

    filters = frappe._dict(filters or {})
    company = get_bom_company_scope(fallback_company=filters.get("company"))
    if company:
        filters["company"] = company

    return erpnext_bom_query(doctype, txt, searchfield, start, page_len, filters)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def work_order_query(doctype, txt, searchfield, start, page_len, filters):
    if isinstance(filters, str):
        filters = frappe.parse_json(filters)

    filters = frappe._dict(filters or {})
    allowed_searchfields = {"name", "production_item", "bom_no", "sales_order"}
    if searchfield not in allowed_searchfields:
        searchfield = "name"

    values = {
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len,
    }
    conditions = [
        "`tabWork Order`.`docstatus` = 1",
        "`tabWork Order`.`status` != 'Stopped'",
        f"`tabWork Order`.`{searchfield}` LIKE %(txt)s",
    ]

    for fieldname in ("company", "production_item", "bom_no", "sales_order"):
        if filters.get(fieldname):
            values[fieldname] = filters.get(fieldname)
            conditions.append(f"`tabWork Order`.`{fieldname}` = %({fieldname})s")

    if manufacturing_warehouse_access_applies():
        allowed_warehouses = get_user_allowed_warehouses(require_transact=True)
        if not allowed_warehouses:
            return []

        allowed_sql = _sql_list(allowed_warehouses)
        conditions.append(_work_order_sql_conditions(allowed_sql, parent_table="`tabWork Order`"))

    return frappe.db.sql(
        f"""
        SELECT
            `tabWork Order`.`name`,
            `tabWork Order`.`production_item`,
            `tabWork Order`.`bom_no`
        FROM `tabWork Order`
        WHERE {" AND ".join(conditions)}
        ORDER BY
            IF(LOCATE(%(_txt)s, `tabWork Order`.`name`), LOCATE(%(_txt)s, `tabWork Order`.`name`), 99999),
            `tabWork Order`.`modified` DESC
        LIMIT %(start)s, %(page_len)s
        """,
        {
            **values,
            "_txt": txt,
        },
    )


@frappe.whitelist()
def get_work_order_item_details(item, project=None, skip_bom_info=False, throw=True, company=None):
    res = frappe.db.sql(
        """
        select stock_uom, description, item_name, allow_alternative_item,
            include_item_in_manufacturing
        from `tabItem`
        where disabled=0
            and (end_of_life is null or end_of_life='0000-00-00' or end_of_life > %s)
            and name=%s
        """,
        (nowdate(), item),
        as_dict=1,
    )

    if not res:
        return {}

    res = res[0]
    if skip_bom_info:
        return res

    bom_company = get_bom_company_scope(fallback_company=company)
    res["bom_no"] = _get_default_bom_for_company(item, project, bom_company)

    if not res["bom_no"]:
        variant_of = frappe.db.get_value("Item", item, "variant_of")
        if variant_of:
            res["bom_no"] = _get_default_bom_for_company(variant_of, project, bom_company)

    if not res["bom_no"]:
        if project:
            res = get_work_order_item_details(item, throw=throw, company=company)
            frappe.msgprint(
                _("Default BOM not found for Item {0} and Project {1}").format(item, project),
                alert=1,
            )
        else:
            message = _("Default BOM for {0} not found").format(item)
            frappe.msgprint(message, raise_exception=throw, indicator="yellow", alert=(not throw))
            return res

    bom_data = frappe.db.get_value(
        "BOM",
        res["bom_no"],
        ["project", "allow_alternative_item", "transfer_material_against", "item_name"],
        as_dict=1,
    )

    res["project"] = project or bom_data.pop("project")
    res.update(bom_data)
    res.update(check_if_scrap_warehouse_mandatory(res["bom_no"]))

    return res


def validate_work_order_bom_company(doc, method=None):
    if not doc.get("bom_no"):
        return

    _validate_bom_company(doc.bom_no, doc.get("company"))


def validate_stock_entry_bom_company(doc, method=None):
    if not doc.get("bom_no"):
        return

    _validate_bom_company(doc.bom_no, doc.get("company"))


def user_can_transact_work_order(work_order, user=None):
    if not work_order:
        return True

    user = user or frappe.session.user
    if not manufacturing_warehouse_access_applies(user):
        return True

    if not frappe.db.exists("Work Order", work_order):
        return False

    allowed = set(get_user_allowed_warehouses(user, require_transact=True))
    if not allowed:
        return False

    warehouses = _get_work_order_warehouses(work_order)
    return not warehouses or warehouses.issubset(allowed)


def user_can_transact_job_card(job_card, user=None):
    if not job_card:
        return True

    user = user or frappe.session.user
    if not manufacturing_warehouse_access_applies(user):
        return True

    if isinstance(job_card, str):
        if not frappe.db.exists("Job Card", job_card):
            return False

        work_order = frappe.db.get_value("Job Card", job_card, "work_order")
    else:
        work_order = job_card.get("work_order")

    allowed = set(get_user_allowed_warehouses(user, require_transact=True))
    if not allowed:
        return False

    warehouses = _get_job_card_warehouses(job_card)
    if work_order:
        warehouses.update(_get_work_order_warehouses(work_order))

    return not warehouses or warehouses.issubset(allowed)


def _get_default_bom_for_company(item, project=None, company=None):
    filters = {"item": item, "docstatus": 1}
    if project:
        filters["project"] = project
    else:
        filters["is_default"] = 1
    if company:
        filters["company"] = company

    return frappe.db.get_value("BOM", filters=filters)


def _validate_bom_company(bom_no, company):
    if not bom_no or not company:
        return

    bom_company = frappe.db.get_value("BOM", bom_no, "company")
    if bom_company and bom_company != company:
        frappe.throw(
            _("BOM {0} belongs to {1}, not {2}.").format(
                frappe.bold(bom_no),
                frappe.bold(bom_company),
                frappe.bold(company),
            )
        )


def _get_doc_warehouses(doc, fieldnames):
    return {
        doc.get(fieldname)
        for fieldname in fieldnames
        if doc.get(fieldname)
    }


def _get_work_order_warehouses(doc_or_name):
    return _get_document_warehouses(
        "Work Order",
        doc_or_name,
        WORK_ORDER_PARENT_WAREHOUSE_FIELDS,
        WORK_ORDER_CHILD_WAREHOUSE_FIELDS,
    )


def _get_job_card_warehouses(doc_or_name):
    return _get_document_warehouses(
        "Job Card",
        doc_or_name,
        JOB_CARD_PARENT_WAREHOUSE_FIELDS,
        JOB_CARD_CHILD_WAREHOUSE_FIELDS,
    )


def _get_document_warehouses(doctype, doc_or_name, parent_fields, child_fields):
    if isinstance(doc_or_name, str):
        return _get_document_warehouses_from_db(
            doctype,
            doc_or_name,
            parent_fields,
            child_fields,
        )

    warehouses = _get_doc_warehouses(doc_or_name, parent_fields)
    for child_doctype, config in child_fields.items():
        parentfield = config["parentfield"]
        for row in doc_or_name.get(parentfield) or []:
            warehouses.update(_get_doc_warehouses(row, config["fields"]))

    return warehouses


def _get_document_warehouses_from_db(doctype, name, parent_fields, child_fields):
    values = frappe.db.get_value(doctype, name, list(parent_fields), as_dict=True)
    if not values:
        return set()

    warehouses = _get_doc_warehouses(values, parent_fields)
    for child_doctype, config in child_fields.items():
        rows = frappe.get_all(
            child_doctype,
            filters={
                "parent": name,
                "parenttype": doctype,
                "parentfield": config["parentfield"],
            },
            fields=list(config["fields"]),
        )
        for row in rows:
            warehouses.update(_get_doc_warehouses(row, config["fields"]))

    return warehouses


def _work_order_sql_conditions(allowed_sql, parent_table):
    return _document_sql_conditions(
        "Work Order",
        parent_table,
        WORK_ORDER_PARENT_WAREHOUSE_FIELDS,
        WORK_ORDER_CHILD_WAREHOUSE_FIELDS,
        allowed_sql,
    )


def _job_card_sql_conditions(allowed_sql, parent_table):
    return _document_sql_conditions(
        "Job Card",
        parent_table,
        JOB_CARD_PARENT_WAREHOUSE_FIELDS,
        JOB_CARD_CHILD_WAREHOUSE_FIELDS,
        allowed_sql,
    )


def _document_sql_conditions(doctype, parent_table, parent_fields, child_fields, allowed_sql):
    conditions = [
        _warehouse_field_condition(parent_table, fieldname, allowed_sql)
        for fieldname in parent_fields
    ]

    for child_doctype, config in child_fields.items():
        child_table = f"`tab{child_doctype}`"
        parentfield = frappe.db.escape(config["parentfield"])
        for fieldname in config["fields"]:
            conditions.append(
                "NOT EXISTS ("
                f"SELECT 1 FROM {child_table} child "
                f"WHERE child.`parent` = {parent_table}.`name` "
                f"AND child.`parenttype` = {frappe.db.escape(doctype)} "
                f"AND child.`parentfield` = {parentfield} "
                f"AND IFNULL(child.`{fieldname}`, '') != '' "
                f"AND child.`{fieldname}` NOT IN ({allowed_sql})"
                ")"
            )

    return "(" + " AND ".join(conditions) + ")"


def _warehouse_field_condition(table, fieldname, allowed_sql):
    return f"(IFNULL({table}.`{fieldname}`, '') = '' OR {table}.`{fieldname}` IN ({allowed_sql}))"


def _sql_list(values):
    return ", ".join(frappe.db.escape(value) for value in values)
