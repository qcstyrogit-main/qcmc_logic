import hashlib

import frappe
from frappe.utils import cint, flt, getdate


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_customer_history_item_query(doctype, txt, searchfield, start, page_len, filters):
    if isinstance(filters, str):
        filters = frappe.parse_json(filters)

    filters = frappe._dict(filters or {})
    customer = filters.get("customer")
    company = filters.get("company")

    if not customer or not company:
        return []

    conditions = [
        "h.customer = %(customer)s",
        "h.company = %(company)s",
        "ifnull(i.disabled, 0) = 0",
        "ifnull(i.is_sales_item, 0) = 1",
        f"i.`{searchfield}` like %(txt)s",
    ]
    values = {
        "company": company,
        "customer": customer,
        "page_len": page_len,
        "start": start,
        "txt": "%{0}%".format(txt),
    }

    return frappe.db.sql(
        """
        select distinct
            i.name,
            i.item_name
        from `tabCustomer Item History` h
        inner join `tabItem` i on i.name = h.item
        where {conditions}
        order by h.last_transaction_date desc, i.name
        limit %(start)s, %(page_len)s
        """.format(conditions=" and ".join(conditions)),
        values,
    )


@frappe.whitelist()
def get_previous_item_rates(customer, item_code, company):
    if not customer or not item_code or not company:
        return []

    return frappe.db.sql(
        """
        select
            rate,
            uom,
            currency,
            min(first_transaction_date) as first_transaction_date,
            max(last_transaction_date) as last_transaction_date,
            sum(ifnull(times_used, 0)) as times_used
        from `tabCustomer Item Rate History`
        where customer = %(customer)s
            and item = %(item_code)s
            and company = %(company)s
        group by rate, uom, currency
        order by last_transaction_date desc, times_used desc, rate desc
        """,
        {
            "company": company,
            "customer": customer,
            "item_code": item_code,
        },
        as_dict=True,
    )


@frappe.whitelist()
def get_customer_history_items(customer, company, limit=500):
    if not customer or not company:
        return []

    limit = frappe.utils.cint(limit) or 500
    limit = min(limit, 1000)

    rows = frappe.db.sql(
        """
        select
            h.item,
            h.item_name,
            h.last_rate,
            h.last_uom,
            h.currency,
            h.first_transaction_date,
            h.last_transaction_date,
            h.order_count
        from `tabCustomer Item History` h
        inner join `tabItem` i on i.name = h.item
        where h.customer = %(customer)s
            and h.company = %(company)s
            and ifnull(i.disabled, 0) = 0
            and ifnull(i.is_sales_item, 0) = 1
        order by h.last_transaction_date desc, h.order_count desc, h.item
        limit %(limit)s
        """,
        {
            "company": company,
            "customer": customer,
            "limit": limit,
        },
        as_dict=True,
    )

    items = {}
    for row in rows:
        item = row.item
        if item not in items:
            items[item] = row
            items[item].order_count = cint(row.order_count)
            continue

        current = items[item]
        current.order_count = cint(current.order_count) + cint(row.order_count)
        if row.first_transaction_date and (
            not current.first_transaction_date
            or getdate(row.first_transaction_date) < getdate(current.first_transaction_date)
        ):
            current.first_transaction_date = row.first_transaction_date

    return list(items.values())[:limit]


def update_customer_item_history_on_submit(doc, method=None):
    _sync_customer_item_history(doc)


def update_customer_item_history_on_cancel(doc, method=None):
    _sync_customer_item_history(doc)


def _sync_customer_item_history(doc):
    affected_items = set()
    affected_rates = set()

    for row in doc.get("items") or []:
        if not row.item_code:
            continue

        affected_items.add(row.item_code)
        affected_rates.add(
            (
                row.item_code,
                row.get("uom") or row.get("stock_uom"),
                doc.get("currency"),
                flt(row.get("rate")),
            )
        )

    if doc.docstatus == 1:
        for item_code in affected_items:
            _sync_erpnext_customer_item_history(doc.customer, doc.company, item_code)

    for item_code, uom, currency, rate in affected_rates:
        _sync_erpnext_customer_item_rate_history(
            doc.customer,
            doc.company,
            item_code,
            uom,
            currency,
            rate,
        )

    if doc.docstatus != 1:
        for item_code in affected_items:
            _sync_erpnext_customer_item_history(doc.customer, doc.company, item_code)


def _sync_erpnext_customer_item_history(customer, company, item_code):
    summary = frappe.db.sql(
        """
        select
            min(so.transaction_date) as first_transaction_date,
            max(so.transaction_date) as last_transaction_date,
            count(*) as order_count
        from `tabSales Order` so
        inner join `tabSales Order Item` soi on soi.parent = so.name
        where so.docstatus = 1
            and so.customer = %(customer)s
            and so.company = %(company)s
            and soi.item_code = %(item_code)s
        """,
        {
            "company": company,
            "customer": customer,
            "item_code": item_code,
        },
        as_dict=True,
    )[0]

    name = _get_erpnext_history_name("Customer Item History", customer, company, item_code)
    if not cint(summary.order_count):
        _delete_doc_if_exists("Customer Item History", name)
        return None

    latest = frappe.db.sql(
        """
        select
            soi.item_name,
            soi.rate,
            soi.uom,
            so.currency
        from `tabSales Order` so
        inner join `tabSales Order Item` soi on soi.parent = so.name
        where so.docstatus = 1
            and so.customer = %(customer)s
            and so.company = %(company)s
            and soi.item_code = %(item_code)s
        order by so.transaction_date desc, so.name desc, soi.idx desc
        limit 1
        """,
        {
            "company": company,
            "customer": customer,
            "item_code": item_code,
        },
        as_dict=True,
    )[0]

    data = {
        "company": company,
        "currency": latest.currency,
        "customer": customer,
        "first_transaction_date": summary.first_transaction_date,
        "history_key": _make_history_key("Customer Item History", customer, company, item_code),
        "item": item_code,
        "item_name": latest.item_name,
        "last_rate": latest.rate,
        "last_transaction_date": summary.last_transaction_date,
        "last_uom": latest.uom,
        "order_count": cint(summary.order_count),
        "source_system": "ERPNext",
    }

    return _upsert_history_doc("Customer Item History", name, data)


def _sync_erpnext_customer_item_rate_history(customer, company, item_code, uom, currency, rate):
    summary = frappe.db.sql(
        """
        select
            min(so.transaction_date) as first_transaction_date,
            max(so.transaction_date) as last_transaction_date,
            count(*) as times_used
        from `tabSales Order` so
        inner join `tabSales Order Item` soi on soi.parent = so.name
        where so.docstatus = 1
            and so.customer = %(customer)s
            and so.company = %(company)s
            and so.currency = %(currency)s
            and soi.item_code = %(item_code)s
            and ifnull(soi.uom, '') = %(uom)s
            and soi.rate = %(rate)s
        """,
        {
            "company": company,
            "currency": currency or "",
            "customer": customer,
            "item_code": item_code,
            "rate": rate,
            "uom": uom or "",
        },
        as_dict=True,
    )[0]

    name = _get_erpnext_rate_history_name(customer, company, item_code, uom, currency, rate)
    if not cint(summary.times_used):
        _delete_doc_if_exists("Customer Item Rate History", name)
        return None

    item_history = _sync_erpnext_customer_item_history(customer, company, item_code)

    latest = frappe.db.sql(
        """
        select soi.item_name
        from `tabSales Order` so
        inner join `tabSales Order Item` soi on soi.parent = so.name
        where so.docstatus = 1
            and so.customer = %(customer)s
            and so.company = %(company)s
            and so.currency = %(currency)s
            and soi.item_code = %(item_code)s
            and ifnull(soi.uom, '') = %(uom)s
            and soi.rate = %(rate)s
        order by so.transaction_date desc, so.name desc, soi.idx desc
        limit 1
        """,
        {
            "company": company,
            "currency": currency or "",
            "customer": customer,
            "item_code": item_code,
            "rate": rate,
            "uom": uom or "",
        },
        as_dict=True,
    )[0]

    data = {
        "company": company,
        "currency": currency,
        "customer": customer,
        "customer_item_history": item_history,
        "first_transaction_date": summary.first_transaction_date,
        "item": item_code,
        "item_name": latest.item_name,
        "rate": rate,
        "rate_key": _make_rate_key(customer, company, item_code, uom, currency, rate),
        "source_system": "ERPNext",
        "last_transaction_date": summary.last_transaction_date,
        "times_used": cint(summary.times_used),
        "uom": uom,
    }

    return _upsert_history_doc("Customer Item Rate History", name, data)


def _upsert_history_doc(doctype, name, data):
    if name:
        doc = frappe.get_doc(doctype, name)
        doc.update(data)
        doc.save(ignore_permissions=True)
        return doc.name

    doc = frappe.get_doc({"doctype": doctype, **data})
    doc.insert(ignore_permissions=True)
    return doc.name


def _delete_doc_if_exists(doctype, name):
    if name and frappe.db.exists(doctype, name):
        frappe.delete_doc(doctype, name, ignore_permissions=True)


def _get_erpnext_history_name(doctype, customer, company, item_code):
    return frappe.db.get_value(
        doctype,
        {
            "company": company,
            "customer": customer,
            "item": item_code,
            "source_system": "ERPNext",
        },
        "name",
    )


def _get_erpnext_rate_history_name(customer, company, item_code, uom, currency, rate):
    return frappe.db.get_value(
        "Customer Item Rate History",
        {
            "company": company,
            "currency": currency or "",
            "customer": customer,
            "item": item_code,
            "rate": rate,
            "source_system": "ERPNext",
            "uom": uom or "",
        },
        "name",
    )


def _make_history_key(doctype, customer, company, item_code):
    return "{0}::{1}".format(
        "ERPNext",
        _hash_key(doctype, customer, company, item_code),
    )


def _make_rate_key(customer, company, item_code, uom, currency, rate):
    return "{0}::{1}".format(
        "ERPNext",
        _hash_key(
            "Customer Item Rate History",
            customer,
            company,
            item_code,
            uom or "",
            currency or "",
            "{0:.6f}".format(flt(rate)),
        ),
    )


def _hash_key(*parts):
    raw_key = "||".join(frappe.as_unicode(part) for part in parts)
    return hashlib.sha1(raw_key.encode("utf-8")).hexdigest()
