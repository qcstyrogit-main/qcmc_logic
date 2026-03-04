import frappe
from frappe.utils import cint


def _existing_fields(doctype, fields):
    meta = frappe.get_meta(doctype)
    return [f for f in fields if meta.get_field(f)]

def _ensure_name_field(fields):
    if "name" not in fields:
        return ["name", *fields]
    return fields

def _ensure_can_read_location(doc=None):
    if not frappe.has_permission("Location", "read", doc=doc):
        frappe.throw("Not permitted", frappe.PermissionError)


def _ensure_can_read_address(doc=None):
    if not frappe.has_permission("Address", "read", doc=doc):
        frappe.throw("Not permitted", frappe.PermissionError)

def _ensure_can_create_address(doc=None):
    if not frappe.has_permission("Address", "create", doc=doc):
        frappe.throw("Not permitted", frappe.PermissionError)


def _ensure_can_create_location(doc=None):
    if not frappe.has_permission("Location", "create", doc=doc):
        frappe.throw("Not permitted", frappe.PermissionError)


def _ensure_can_write_location(doc=None):
    if not frappe.has_permission("Location", "write", doc=doc):
        frappe.throw("Not permitted", frappe.PermissionError)


@frappe.whitelist()
def list_locations(limit=20, start=0, search=None, is_group=None, is_container=None, custom_is_customer=None):
    """
    List locations with optional search and filters.

    Params:
      limit, start: pagination
      search: matches name or location_name (contains)
      is_group, is_container, custom_is_customer: optional filters (0/1)
    """
    _ensure_can_read_location()

    limit = cint(limit) if limit is not None else 20
    start = cint(start) if start is not None else 0
    limit = max(1, min(limit, 500))
    start = max(0, start)

    meta = frappe.get_meta("Location")
    filters = {}

    if is_group is not None and meta.get_field("is_group"):
        filters["is_group"] = cint(is_group)
    if is_container is not None and meta.get_field("is_container"):
        filters["is_container"] = cint(is_container)
    if custom_is_customer is not None and meta.get_field("custom_is_customer"):
        filters["custom_is_customer"] = cint(custom_is_customer)

    or_filters = None
    if search:
        or_filters = []
        if meta.get_field("name"):
            or_filters.append(["Location", "name", "like", f"%{search}%"])
        if meta.get_field("location_name"):
            or_filters.append(["Location", "location_name", "like", f"%{search}%"])

    fields = _existing_fields(
        "Location",
        [
            "name",
            "location_name",
            "is_group",
            "is_container",
            "custom_is_customer",
            "latitude",
            "longitude",
            "area",
            "custom_search",
            "location",
        ],
    )
    fields = _ensure_name_field(fields)

    items = frappe.get_all(
        "Location",
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


@frappe.whitelist()
def list_locations_by_customer(
    customer=None,
    limit=20,
    start=0,
    search=None,
    is_group=None,
    is_container=None,
    custom_is_customer=None,
):
    """
    List locations that are linked to a Customer via Address -> Links table.

    Params:
      customer: Customer ID (name)
      search: optional search to match Customer ID or Customer Name (contains)
      limit, start: pagination
      is_group, is_container, custom_is_customer: optional Location filters (0/1)
    """
    _ensure_can_read_location()
    _ensure_can_read_address()

    limit = cint(limit) if limit is not None else 20
    start = cint(start) if start is not None else 0
    limit = max(1, min(limit, 500))
    start = max(0, start)

    customer_names = []
    if customer:
        customer_names = [customer]
    elif search:
        customer_meta = frappe.get_meta("Customer")
        customer_filters = []
        if customer_meta.get_field("name"):
            customer_filters.append(["Customer", "name", "like", f"%{search}%"])
        if customer_meta.get_field("customer_name"):
            customer_filters.append(["Customer", "customer_name", "like", f"%{search}%"])
        if customer_filters:
            matches = frappe.get_all(
                "Customer",
                or_filters=customer_filters,
                fields=["name"],
                limit_page_length=500,
            )
            customer_names = [c.name for c in matches if getattr(c, "name", None)]

    if not customer_names:
        return {"count": 0, "start": start, "limit": limit, "items": []}

    link_rows = frappe.get_all(
        "Dynamic Link",
        filters={
            "link_doctype": "Customer",
            "link_name": ["in", customer_names],
            "parenttype": "Address",
        },
        fields=["parent"],
        limit_page_length=0,
    )
    address_names = [row.parent for row in link_rows if getattr(row, "parent", None)]

    if not address_names:
        return {"count": 0, "start": start, "limit": limit, "items": []}

    address_rows = frappe.get_all(
        "Address",
        filters={"name": ["in", address_names]},
        fields=["name", "custom_location", "address_type"],
        limit_page_length=0,
    )

    location_keys = [
        row.custom_location
        for row in address_rows
        if getattr(row, "custom_location", None)
    ]

    if not location_keys:
        return {"count": 0, "start": start, "limit": limit, "items": []}

    meta = frappe.get_meta("Location")
    unique_keys = list(set(location_keys))
    filters = {}

    if is_group is not None and meta.get_field("is_group"):
        filters["is_group"] = cint(is_group)
    if is_container is not None and meta.get_field("is_container"):
        filters["is_container"] = cint(is_container)
    if custom_is_customer is not None and meta.get_field("custom_is_customer"):
        filters["custom_is_customer"] = cint(custom_is_customer)

    or_filters = []
    # Match custom_location values to either Location.name or Location.location_name.
    if meta.get_field("name"):
        or_filters.append(["Location", "name", "in", unique_keys])
    if meta.get_field("location_name"):
        or_filters.append(["Location", "location_name", "in", unique_keys])
    if search:
        if meta.get_field("name"):
            or_filters.append(["Location", "name", "like", f"%{search}%"])
        if meta.get_field("location_name"):
            or_filters.append(["Location", "location_name", "like", f"%{search}%"])
    if not or_filters:
        return {"count": 0, "start": start, "limit": limit, "items": []}

    fields = _existing_fields(
        "Location",
        [
            "name",
            "location_name",
            "is_group",
            "is_container",
            "custom_is_customer",
            "latitude",
            "longitude",
            "area",
            "custom_search",
            "location",
        ],
    )
    fields = _ensure_name_field(fields)

    items = frappe.get_all(
        "Location",
        filters=filters,
        or_filters=or_filters,
        fields=fields or ["name"],
        order_by="modified desc",
        limit_page_length=0,
    )

    # Map addresses to locations so we can expose Address ID + Type.
    location_by_name = {loc.name: loc for loc in items if getattr(loc, "name", None)}
    location_by_title = {}
    for loc in items:
        title = getattr(loc, "location_name", None)
        if isinstance(title, str) and title.strip():
            location_by_title[title.strip().lower()] = loc

    resolved_items = []
    for addr in address_rows:
        key = getattr(addr, "custom_location", None)
        if not key:
            continue
        loc = location_by_name.get(key)
        if not loc and isinstance(key, str):
            loc = location_by_title.get(key.strip().lower())
        if not loc:
            continue
        row = dict(loc)
        row["address_id"] = getattr(addr, "name", None)
        row["address_type"] = getattr(addr, "address_type", None)
        resolved_items.append(row)

    total_count = len(resolved_items)
    paged = resolved_items[start : start + limit]

    return {
        "count": total_count,
        "start": start,
        "limit": limit,
        "items": paged,
    }


@frappe.whitelist()
def get_location(name):
    """Return a single location by name (requires read permission)."""
    if not name:
        frappe.throw("Location name is required")

    doc = frappe.get_doc("Location", name)
    _ensure_can_read_location(doc=doc)

    fields = _existing_fields(
        "Location",
        [
            "name",
            "location_name",
            "is_group",
            "is_container",
            "custom_is_customer",
            "latitude",
            "longitude",
            "area",
            "custom_search",
            "location",
        ],
    )

    data = {f: getattr(doc, f, None) for f in fields}
    return data


@frappe.whitelist()
def create_location(data):
    """
    Create a new Location.

    data: dict or JSON string containing Location fields
    """
    data = frappe.parse_json(data)
    if not isinstance(data, dict):
        frappe.throw("Invalid data payload")

    data.setdefault("doctype", "Location")
    doc = frappe.get_doc(data)
    _ensure_can_create_location(doc=doc)
    doc.insert()

    return {"name": doc.name}


@frappe.whitelist()
def update_location(name, data):
    """
    Update an existing Location.

    name: Location name (ID)
    data: dict or JSON string with fields to update
    """
    if not name:
        frappe.throw("Location name is required")

    data = frappe.parse_json(data)
    if not isinstance(data, dict):
        frappe.throw("Invalid data payload")

    doc = frappe.get_doc("Location", name)
    _ensure_can_write_location(doc=doc)

    # Prevent changing doctype/name via payload
    data.pop("doctype", None)
    data.pop("name", None)

    doc.update(data)
    doc.save()

    return {"name": doc.name}


def _build_location_geojson(latitude=None, longitude=None):
    if latitude is None or longitude is None:
        return {"type": "FeatureCollection", "features": []}
    try:
        lat = float(latitude)
        lng = float(longitude)
    except Exception:
        return {"type": "FeatureCollection", "features": []}
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Point",
                    "coordinates": [lng, lat],
                },
            }
        ],
    }


@frappe.whitelist()
def create_customer_address(data):
    """
    Create Address linked to Customer and Location.

    Required in data:
      customer (Customer ID or name)
      address_title
      address_type
      custom_location (Location name to use/display)

    Optional:
      email_id, address_line2, city, country, latitude, longitude
    """
    data = frappe.parse_json(data)
    if not isinstance(data, dict):
        frappe.throw("Invalid data payload")

    _ensure_can_create_address()
    _ensure_can_read_location()

    customer_input = (data.get("customer") or "").strip()
    if not customer_input:
        frappe.throw("Customer is required")

    customer_name = None
    customer_title = None
    try:
        cust = frappe.get_doc("Customer", customer_input)
        customer_name = cust.name
        customer_title = cust.customer_name or cust.name
    except Exception:
        matches = frappe.get_all(
            "Customer",
            or_filters=[
                ["Customer", "name", "=", customer_input],
                ["Customer", "customer_name", "=", customer_input],
                ["Customer", "name", "like", f"%{customer_input}%"],
                ["Customer", "customer_name", "like", f"%{customer_input}%"],
            ],
            fields=["name", "customer_name"],
            limit_page_length=2,
        )
        if matches:
            customer_name = matches[0].name
            customer_title = matches[0].customer_name or matches[0].name
            if len(matches) > 1:
                frappe.throw("Customer search is ambiguous. Please enter the exact Customer ID.")

    if not customer_name:
        frappe.throw("Customer not found")

    location_label = (data.get("custom_location") or data.get("location_name") or "").strip()
    if not location_label:
        frappe.throw("Location name is required")

    location_doc = None
    try:
        location_doc = frappe.get_doc("Location", location_label)
    except Exception:
        location_doc = None

    if not location_doc:
        location_geojson = _build_location_geojson(
            data.get("latitude"), data.get("longitude")
        )
        location_doc = frappe.get_doc(
            {
                "doctype": "Location",
                "location_name": location_label,
                "custom_is_customer": 1,
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "location": frappe.as_json(location_geojson),
            }
        )
        _ensure_can_create_location(location_doc)
        location_doc.insert()

    address_title = (data.get("address_title") or location_label or "Customer Address").strip()
    address_type = (data.get("address_type") or "Shipping").strip()
    address_line2 = (data.get("address_line2") or "").strip()
    address_line1 = (data.get("address_line1") or "").strip()
    if not address_line1:
        address_line1 = address_line2 or address_title or location_label
        address_line1 = (address_line1 or "").strip()
    if not address_line1:
        frappe.throw("Address Line 1 is required")

    address_doc = frappe.get_doc(
        {
            "doctype": "Address",
            "address_title": address_title,
            "address_type": address_type,
            "address_line1": address_line1,
            "address_line2": address_line2,
            "city": data.get("city"),
            "country": data.get("country"),
            "email_id": data.get("email_id"),
            "custom_location": location_doc.name,
            "links": [
                {
                    "link_doctype": "Customer",
                    "link_name": customer_name,
                    "link_title": customer_title or customer_name,
                }
            ],
        }
    )
    address_doc.insert()

    return {
        "address_id": address_doc.name,
        "location_name": location_doc.name,
        "customer": customer_name,
    }


@frappe.whitelist()
def create_location_then_address(data):
    """
    Create Location first, then Address linked to Customer and Location.

    Required in data:
      customer (Customer ID or name)
      location_name (used for Location)
      address_type
      address_line1

    Optional:
      address_title, email_id, address_line2, city, country, latitude, longitude
    """
    data = frappe.parse_json(data)
    if not isinstance(data, dict):
        frappe.throw("Invalid data payload")

    _ensure_can_create_location()
    _ensure_can_create_address()

    location_label = (data.get("location_name") or "").strip()
    if not location_label:
        frappe.throw("Location name is required")

    location_doc = None
    try:
        location_doc = frappe.get_doc("Location", location_label)
    except Exception:
        location_doc = None

    if not location_doc:
        location_geojson = _build_location_geojson(
            data.get("latitude"), data.get("longitude")
        )
        location_doc = frappe.get_doc(
            {
                "doctype": "Location",
                "location_name": location_label,
                "custom_is_customer": 1,
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "location": frappe.as_json(location_geojson),
            }
        )
        location_doc.insert()

    # Reuse address creation logic by passing custom_location
    data["custom_location"] = location_doc.name
    return create_customer_address(data)
