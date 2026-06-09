import frappe


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
