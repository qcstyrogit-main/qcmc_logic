import frappe
from frappe.utils import cint


def _existing_fields(doctype, fields):
    meta = frappe.get_meta(doctype)
    return [f for f in fields if meta.get_field(f)]


def _ensure_name_field(fields):
    if "name" not in fields:
        return ["name", *fields]
    return fields


def _ensure_can_read_customer(doc=None):
    if not frappe.has_permission("Customer", "read", doc=doc):
        frappe.throw("Not permitted", frappe.PermissionError)


@frappe.whitelist(allow_guest=True)
def list_customers(limit=20, start=0, search=None, customer_group=None, territory=None, include_disabled=0):
    """
    List customers with optional search and filters.

    Params:
      limit, start: pagination
      search: matches customer name or customer_name (contains)
      customer_group, territory: optional filters
      include_disabled: 1 to include disabled customers
    """
    _ensure_can_read_customer()

    limit = cint(limit) if limit is not None else 20
    start = cint(start) if start is not None else 0
    limit = max(1, min(limit, 500))
    start = max(0, start)

    meta = frappe.get_meta("Customer")
    filters = {}

    if customer_group and meta.get_field("customer_group"):
        filters["customer_group"] = customer_group
    if territory and meta.get_field("territory"):
        filters["territory"] = territory
    if not cint(include_disabled) and meta.get_field("disabled"):
        filters["disabled"] = 0

    or_filters = None
    if search:
        or_filters = []
        if meta.get_field("name"):
            or_filters.append(["Customer", "name", "like", f"%{search}%"])
        if meta.get_field("customer_name"):
            or_filters.append(["Customer", "customer_name", "like", f"%{search}%"])

    fields = _existing_fields(
        "Customer",
        [
            "name",
            "customer_name",
            "customer_group",
            "territory",
            "customer_type",
            "tax_id",
            "mobile_no",
            "email_id",
            "disabled",
            "custom_sales_manager",
        ],
    )
    fields = _ensure_name_field(fields)

    items = frappe.get_all(
        "Customer",
        filters=filters,
        or_filters=or_filters,
        fields=fields or ["name"],
        order_by="modified desc",
        limit_start=start,
        limit_page_length=limit,
    )

    return {
        "count": len(items),
        "start": start,
        "limit": limit,
        "items": items,
    }


@frappe.whitelist(allow_guest=True)
def get_customer(name):
    """Return a single customer by name (requires read permission)."""
    if not name:
        frappe.throw("Customer name is required")

    doc = frappe.get_doc("Customer", name)
    _ensure_can_read_customer(doc=doc)

    fields = _existing_fields(
        "Customer",
        [
            "name",
            "customer_name",
            "customer_group",
            "territory",
            "customer_type",
            "tax_id",
            "mobile_no",
            "email_id",
            "disabled",
            "custom_sales_manager",
        ],
    )
    fields = _ensure_name_field(fields)

    data = {f: getattr(doc, f, None) for f in fields}
    return data


def _ensure_can_create_customer(doc=None):
    if not frappe.has_permission("Customer", "create", doc=doc):
        frappe.throw("Not permitted", frappe.PermissionError)


def _ensure_can_write_customer(doc=None):
    if not frappe.has_permission("Customer", "write", doc=doc):
        frappe.throw("Not permitted", frappe.PermissionError)


@frappe.whitelist(allow_guest=True)
def create_customer(data):
    """
    Create a new Customer.

    data: dict or JSON string containing Customer fields (and optional child tables)
    """
    data = frappe.parse_json(data)
    if not isinstance(data, dict):
        frappe.throw("Invalid data payload")

    data.setdefault("doctype", "Customer")
    doc = frappe.get_doc(data)
    _ensure_can_create_customer(doc=doc)
    doc.insert()

    return {"name": doc.name}


@frappe.whitelist(allow_guest=True)
def update_customer(name, data):
    """
    Update an existing Customer.

    name: Customer name (ID)
    data: dict or JSON string with fields to update (and optional child tables)
    """
    if not name:
        frappe.throw("Customer name is required")

    data = frappe.parse_json(data)
    if not isinstance(data, dict):
        frappe.throw("Invalid data payload")

    doc = frappe.get_doc("Customer", name)
    _ensure_can_write_customer(doc=doc)

    # Prevent changing doctype/name via payload
    data.pop("doctype", None)
    data.pop("name", None)

    doc.update(data)
    doc.save()

    return {"name": doc.name}
