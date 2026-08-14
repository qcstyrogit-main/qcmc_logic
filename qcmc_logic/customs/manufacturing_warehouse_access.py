import frappe
from frappe import _
from frappe.utils import nowdate

from erpnext.manufacturing.doctype.work_order.work_order import (
    check_if_scrap_warehouse_mandatory,
)
from erpnext.controllers.queries import bom as erpnext_bom_query

from qcmc_logic.utils import (
    get_default_company_from_default_warehouse,
    get_user_allowed_warehouses,
    has_warehouse_access,
    is_global_warehouse_access_enabled,
)


WORK_ORDER_WAREHOUSE_FIELDS = (
    "source_warehouse",
    "wip_warehouse",
    "fg_warehouse",
    "scrap_warehouse",
)


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

    return get_default_company_from_default_warehouse(user) or fallback_company


def work_order_permission_query(user):
    if not manufacturing_warehouse_access_applies(user):
        return ""

    allowed_warehouses = get_user_allowed_warehouses(user, require_list_view=True)
    if not allowed_warehouses:
        return "1=0"

    allowed_sql = _sql_list(allowed_warehouses)
    table = "`tabWork Order`"
    warehouse_conditions = [
        _warehouse_field_condition(table, fieldname, allowed_sql)
        for fieldname in WORK_ORDER_WAREHOUSE_FIELDS
    ]

    return "(" + " AND ".join(warehouse_conditions) + ")"


def job_card_permission_query(user):
    if not manufacturing_warehouse_access_applies(user):
        return ""

    work_order_query = work_order_permission_query(user)
    if not work_order_query:
        return ""

    return (
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

    warehouses = _get_doc_warehouses(doc, WORK_ORDER_WAREHOUSE_FIELDS)
    return not warehouses or warehouses.issubset(allowed)


def job_card_has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    if not manufacturing_warehouse_access_applies(user) or ptype == "create":
        return True
    if not doc:
        return None

    work_order = doc.get("work_order")
    if not work_order:
        return True

    work_order_values = frappe.db.get_value(
        "Work Order",
        work_order,
        ["name", *WORK_ORDER_WAREHOUSE_FIELDS],
        as_dict=True,
    )
    if not work_order_values:
        return False

    return work_order_has_permission(
        frappe._dict({"doctype": "Work Order", **work_order_values}),
        ptype=ptype,
        user=user,
    )


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
        conditions.extend(
            _warehouse_field_condition("`tabWork Order`", fieldname, allowed_sql)
            for fieldname in WORK_ORDER_WAREHOUSE_FIELDS
        )

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

    values = frappe.db.get_value(
        "Work Order",
        work_order,
        ["name", *WORK_ORDER_WAREHOUSE_FIELDS],
        as_dict=True,
    )
    if not values:
        return False

    return work_order_has_permission(
        frappe._dict({"doctype": "Work Order", **values}),
        ptype="write",
        user=user,
    )


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


def _warehouse_field_condition(table, fieldname, allowed_sql):
    return f"(IFNULL({table}.`{fieldname}`, '') = '' OR {table}.`{fieldname}` IN ({allowed_sql}))"


def _sql_list(values):
    return ", ".join(frappe.db.escape(value) for value in values)
