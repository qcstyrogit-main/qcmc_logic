import frappe
from frappe.utils import flt


@frappe.whitelist()
def is_global_warehouse_access_enabled():
    meta = frappe.get_meta("Stock Settings")
    if not meta.has_field("custom_enable_global_warehouse_access"):
        return False

    return bool(
        frappe.utils.cint(
            frappe.db.get_single_value(
                "Stock Settings",
                "custom_enable_global_warehouse_access",
            )
        )
    )


@frappe.whitelist()
def get_user_allowed_warehouses(user=None, require_transact=False):
    """Fetch warehouses from Warehouse Access for the given user.

    Rows in Allowed Warehouse grant selection access by default. When
    require_transact is true, only rows with allow_transact checked are returned.
    """
    if not user:
        user = frappe.session.user

    access_doc = frappe.get_all(
        "Warehouse Access",
        filters={"user": user},
        fields=["name"]
    )

    if not access_doc:
        return []

    filters = {"parent": ["in", [d.name for d in access_doc]]}
    if frappe.utils.cint(require_transact):
        filters["allow_transact"] = 1

    allowed = frappe.get_all(
        "Allowed Warehouse",
        filters=filters,
        pluck="warehouse"
    )

    return allowed

@frappe.whitelist()
def check_warehouse_access(user, warehouse, require_transact=False):
    allowed = get_user_allowed_warehouses(user, require_transact=require_transact)
    return warehouse in allowed


@frappe.whitelist()
def get_default_warehouse_for_user(user=None, require_transact=False):
    allowed = get_user_allowed_warehouses(user, require_transact=require_transact)
    return allowed[0] if len(allowed) == 1 else None


def _get_warehouse_company(warehouse):
    if not warehouse:
        return None
    return frappe.db.get_value("Warehouse", warehouse, "company")


def _get_warehouse_type(warehouse):
    if not warehouse:
        return None
    return frappe.db.get_value("Warehouse", warehouse, "warehouse_type")


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_allowed_warehouse_query(doctype, txt, searchfield, start, page_len, filters):
    """Generic Warehouse link query backed by Warehouse Access."""
    if isinstance(filters, str):
        filters = frappe.parse_json(filters)

    filters = frappe._dict(filters or {})
    user = filters.get("user") or frappe.session.user
    require_transact = frappe.utils.cint(filters.get("require_transact"))
    allowed_warehouses = get_user_allowed_warehouses(user, require_transact=require_transact)
    if not allowed_warehouses:
        return []

    return frappe.db.sql(
        f"""
        select w.name, w.warehouse_name
        from `tabWarehouse` w
        where w.is_group = 0
            and w.name in %(allowed_warehouses)s
            and w.`{searchfield}` like %(txt)s
        order by w.name
        limit %(start)s, %(page_len)s
        """,
        {
            "allowed_warehouses": tuple(allowed_warehouses),
            "txt": f"%{txt}%",
            "start": start,
            "page_len": page_len,
        },
    )


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_source_warehouse_query(doctype, txt, searchfield, start, page_len, filters):
    """Link query for Warehouse Transfer source warehouses.

    Source warehouses are limited to Warehouse Access rows where the current
    user is allowed to transact, matching the server-side transfer validation.
    """
    if isinstance(filters, str):
        filters = frappe.parse_json(filters)

    filters = frappe._dict(filters or {})
    user = filters.get("user") or frappe.session.user
    allowed_warehouses = get_user_allowed_warehouses(user, require_transact=True)
    if not allowed_warehouses:
        return []

    return frappe.db.sql(
        f"""
        select w.name, w.warehouse_name
        from `tabWarehouse` w
        where w.is_group = 0
            and w.name in %(allowed_warehouses)s
            and w.`{searchfield}` like %(txt)s
        order by w.name
        limit %(start)s, %(page_len)s
        """,
        {
            "allowed_warehouses": tuple(allowed_warehouses),
            "txt": f"%{txt}%",
            "start": start,
            "page_len": page_len,
        },
    )


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_target_warehouse_query(doctype, txt, searchfield, start, page_len, filters):
    """Link query for Warehouse Transfer target warehouses.

    Target selection is based on transfer rules only. Warehouse Access is used
    later to validate who can create from the source or receive at the target.
    """
    if isinstance(filters, str):
        filters = frappe.parse_json(filters)

    filters = frappe._dict(filters or {})
    source_warehouse = filters.get("source_warehouse")
    transfer_type = filters.get("transfer_type")

    if not source_warehouse or not transfer_type:
        return []

    conditions = [
        "w.is_group = 0",
        f"w.`{searchfield}` like %(txt)s",
    ]
    values = {
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len,
    }

    source_company = _get_warehouse_company(source_warehouse)
    source_warehouse_type = _get_warehouse_type(source_warehouse)
    conditions.append("w.name != %(source_warehouse)s")
    values["source_warehouse"] = source_warehouse

    if transfer_type == "Intercompany Warehouse Transfer":
        if source_company:
            conditions.append("w.company != %(source_company)s")
            values["source_company"] = source_company
        if source_warehouse_type:
            conditions.append("w.warehouse_type = %(source_warehouse_type)s")
            values["source_warehouse_type"] = source_warehouse_type
        conditions.append("ifnull(w.custom_is_province, 0) = 0")
    elif transfer_type == "Warehouse Transfer":
        if source_company:
            conditions.append("w.company = %(source_company)s")
            values["source_company"] = source_company
        if source_warehouse_type:
            conditions.append("w.warehouse_type = %(source_warehouse_type)s")
            values["source_warehouse_type"] = source_warehouse_type
        conditions.append("ifnull(w.custom_is_province, 0) = 0")
    elif transfer_type == "Provincial Warehouse Transfer":
        conditions.append("ifnull(w.custom_is_province, 0) = 1")

    return frappe.db.sql(
        f"""
        select w.name, w.warehouse_name
        from `tabWarehouse` w
        where {" and ".join(conditions)}
        order by w.name
        limit %(start)s, %(page_len)s
        """,
        values,
    )


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_possible_material_request_query(doctype, txt, searchfield, start, page_len, filters):
    filters = frappe._dict(filters or {})
    source_warehouse = filters.get("source_warehouse")
    target_warehouse = filters.get("target_warehouse")
    values = {
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len,
    }
    conditions = [
        "mr.docstatus = 1",
        "mr.material_request_type = 'Material Transfer'",
        f"mr.`{searchfield}` like %(txt)s",
    ]

    if source_warehouse:
        conditions.append("(mr.set_from_warehouse = %(source_warehouse)s or mr.set_from_warehouse is null or mr.set_from_warehouse = '')")
        values["source_warehouse"] = source_warehouse
    if target_warehouse:
        conditions.append("(mr.set_warehouse = %(target_warehouse)s or mr.set_warehouse is null or mr.set_warehouse = '')")
        values["target_warehouse"] = target_warehouse

    return frappe.db.sql(
        f"""
        select mr.name, mr.transaction_date, mr.company
        from `tabMaterial Request` mr
        where {" and ".join(conditions)}
        order by mr.transaction_date desc, mr.modified desc
        limit %(start)s, %(page_len)s
        """,
        values,
    )


@frappe.whitelist()
def get_material_request_transfer_items(material_request):
    if not material_request:
        frappe.throw("Material Request is required.")

    mr = frappe.db.get_value(
        "Material Request",
        material_request,
        ["docstatus", "material_request_type"],
        as_dict=True,
    )
    if not mr:
        frappe.throw(f"Material Request {material_request} does not exist.")
    if mr.docstatus != 1:
        frappe.throw(f"Material Request {material_request} must be submitted.")
    if mr.material_request_type != "Material Transfer":
        frappe.throw(f"Material Request {material_request} must be a Material Transfer request.")

    item_fields = ["name", "item_code", "item_name", "stock_uom", "qty", "warehouse"]
    if frappe.get_meta("Material Request Item").has_field("from_warehouse"):
        item_fields.append("from_warehouse")

    return frappe.get_all(
        "Material Request Item",
        filters={"parent": material_request},
        fields=item_fields,
        order_by="idx",
    )


def _get_material_request_warehouses(material_request):
    mr = frappe.db.get_value(
        "Material Request",
        material_request,
        ["set_from_warehouse", "set_warehouse"],
        as_dict=True,
    ) or {}
    if mr.set_from_warehouse or mr.set_warehouse:
        return mr.set_from_warehouse, mr.set_warehouse

    item_fields = ["warehouse"]
    if frappe.get_meta("Material Request Item").has_field("from_warehouse"):
        item_fields.insert(0, "from_warehouse")

    item_warehouses = frappe.get_all(
        "Material Request Item",
        filters={"parent": material_request},
        fields=item_fields,
        order_by="idx",
    )
    for row in item_warehouses:
        from_warehouse = row.get("from_warehouse")
        if from_warehouse or row.warehouse:
            return from_warehouse, row.warehouse

    return None, None


def _validate_transfer_picker_context(transfer_type, source_warehouse, target_warehouse):
    if not transfer_type or not source_warehouse or not target_warehouse:
        frappe.throw("Select Transfer Type, Source Warehouse, and Target Warehouse first.")

    source_company = _get_warehouse_company(source_warehouse)
    target_company = _get_warehouse_company(target_warehouse)

    if source_warehouse == target_warehouse:
        frappe.throw("Source Warehouse and Target Warehouse cannot be the same.")
    source_warehouse_type = _get_warehouse_type(source_warehouse)
    target_warehouse_type = _get_warehouse_type(target_warehouse)
    target_is_province = frappe.utils.cint(
        frappe.db.get_value("Warehouse", target_warehouse, "custom_is_province")
    )

    if transfer_type == "Warehouse Transfer":
        if source_company != target_company:
            frappe.throw("Warehouse Transfer requires source and target warehouses from the same company.")
        if source_warehouse_type != target_warehouse_type:
            frappe.throw("Warehouse Transfer requires source and target warehouses with the same warehouse type.")
        if target_is_province:
            frappe.throw("Warehouse Transfer cannot use a provincial target warehouse.")
    elif transfer_type == "Intercompany Warehouse Transfer":
        if source_company == target_company:
            frappe.throw("Intercompany Warehouse Transfer requires warehouses from different companies.")
        if source_warehouse_type != target_warehouse_type:
            frappe.throw("Intercompany Warehouse Transfer requires source and target warehouses with the same warehouse type.")
        if target_is_province:
            frappe.throw("Intercompany Warehouse Transfer cannot use a provincial target warehouse.")
    elif transfer_type == "Provincial Warehouse Transfer":
        if not target_is_province:
            frappe.throw("Provincial Warehouse Transfer requires a provincial target warehouse.")


@frappe.whitelist()
def get_possible_material_transfer_requests(transfer_type=None, source_warehouse=None, target_warehouse=None):
    _validate_transfer_picker_context(transfer_type, source_warehouse, target_warehouse)

    filters = {
        "docstatus": 1,
        "material_request_type": "Material Transfer",
    }

    requests = frappe.get_all(
        "Material Request",
        filters=filters,
        fields=["name", "transaction_date", "company", "set_from_warehouse", "set_warehouse"],
        order_by="transaction_date desc, modified desc",
        limit_page_length=100,
    )

    possible = []
    for mr in requests:
        source, target = _get_material_request_warehouses(mr.name)
        if source != source_warehouse:
            continue
        if target != target_warehouse:
            continue

        mr.source_warehouse = source
        mr.target_warehouse = target
        possible.append(mr)

    return possible


@frappe.whitelist()
def get_material_transfer_requests_for_warehouse_transfer(
    material_requests,
    transfer_type=None,
    source_warehouse=None,
    target_warehouse=None,
):
    if isinstance(material_requests, str):
        material_requests = frappe.parse_json(material_requests)

    if not material_requests:
        frappe.throw("Select at least one Material Request.")

    _validate_transfer_picker_context(transfer_type, source_warehouse, target_warehouse)

    rows = []

    for material_request in material_requests:
        mr = frappe.db.get_value(
            "Material Request",
            material_request,
            ["docstatus", "material_request_type", "company"],
            as_dict=True,
        )
        if not mr:
            frappe.throw(f"Material Request {material_request} does not exist.")
        if mr.docstatus != 1:
            frappe.throw(f"Material Request {material_request} must be submitted.")
        if mr.material_request_type != "Material Transfer":
            frappe.throw(f"Material Request {material_request} must be a Material Transfer request.")

        mr_source, mr_target = _get_material_request_warehouses(material_request)
        if mr_source != source_warehouse or mr_target != target_warehouse:
            frappe.throw(
                f"Material Request {material_request} does not match the selected source and target warehouses."
            )

        for item in get_material_request_transfer_items(material_request):
            rows.append({
                "item_code": item.item_code,
                "item_name": item.item_name,
                "uom": item.stock_uom,
                "issued_qty": item.qty,
                "received_qty": 0,
                "reference_doc": "",
                "material_request": material_request,
                "material_request_item": item.name,
            })

    return {
        "source_warehouse": source_warehouse,
        "target_warehouse": target_warehouse,
        "items": rows,
    }


@frappe.whitelist()
def make_stock_entry_from_material_request(source_name, target_doc=None):
    mr_type = frappe.db.get_value("Material Request", source_name, "material_request_type")
    if mr_type == "Material Transfer":
        return make_warehouse_transfer_from_material_request(source_name, target_doc=target_doc)

    from erpnext.stock.doctype.material_request.material_request import make_stock_entry

    return make_stock_entry(source_name, target_doc=target_doc)


@frappe.whitelist()
def make_warehouse_transfer_from_material_request(source_name, target_doc=None):
    if not source_name:
        frappe.throw("Material Request is required.")

    mr = frappe.get_doc("Material Request", source_name)
    if mr.docstatus != 1:
        frappe.throw(f"Material Request {source_name} must be submitted.")
    if mr.material_request_type != "Material Transfer":
        frappe.throw(f"Material Request {source_name} must be a Material Transfer request.")

    source_warehouse, target_warehouse = _get_material_request_warehouses(source_name)
    if not source_warehouse or not target_warehouse:
        frappe.throw("Material Request must have source and target warehouses.")

    transfer_type = _get_transfer_type_for_warehouses(source_warehouse, target_warehouse)
    _validate_transfer_picker_context(transfer_type, source_warehouse, target_warehouse)

    target = frappe.get_doc(frappe.parse_json(target_doc)) if target_doc else frappe.new_doc("Warehouse Transfer")
    target.transfer_type = transfer_type
    target.source_warehouse = source_warehouse
    target.target_warehouse = target_warehouse
    target.source_company = _get_warehouse_company(source_warehouse)
    target.target_company = _get_warehouse_company(target_warehouse)
    target.date_transferred = getattr(mr, "schedule_date", None) or getattr(mr, "transaction_date", None)
    target.transfer_status = "Draft"

    target.set("transfer_items", [])
    for item in get_material_request_transfer_items(source_name):
        row_source = item.get("from_warehouse") or source_warehouse
        row_target = item.get("warehouse") or target_warehouse
        if row_source != source_warehouse or row_target != target_warehouse:
            frappe.throw(
                f"Material Request {source_name} item {item.item_code} does not match the selected warehouses."
            )

        remaining_qty = flt(item.qty or 0)
        if remaining_qty <= 0:
            continue

        row = target.append("transfer_items", {})
        row.item_code = item.item_code
        row.item_name = item.item_name
        row.uom = item.stock_uom
        row.issued_qty = remaining_qty
        row.received_qty = 0
        row.reference_doc = ""
        row.material_request = source_name
        row.material_request_item = item.name
    if not target.get("transfer_items"):
        frappe.throw(f"Material Request {source_name} has no transferable items.")

    return target


@frappe.whitelist()
def make_machine_shop_repairs_and_project(source_name, target_doc=None):
    msjr = frappe.get_doc("Machine Shop Job Request", source_name)

    target = frappe.get_doc(frappe.parse_json(target_doc)) if target_doc else frappe.new_doc("Machine Shop Repairs and Project")
    target.msjr_no = source_name
    target.asset = msjr.asset_name
    target.subject = msjr.work_instruction
    target.date_posted = frappe.utils.today()

    return target


def _get_transfer_type_for_warehouses(source_warehouse, target_warehouse):
    source_company = _get_warehouse_company(source_warehouse)
    target_company = _get_warehouse_company(target_warehouse)
    target_is_province = frappe.utils.cint(
        frappe.db.get_value("Warehouse", target_warehouse, "custom_is_province")
    )

    if target_is_province:
        return "Provincial Warehouse Transfer"
    if source_company != target_company:
        return "Intercompany Warehouse Transfer"
    return "Warehouse Transfer"


@frappe.whitelist()
def check_duplicate_customer_po(customer, po_no, current_name=None):
    """
    Return a list of Sales Orders for the same Customer with the same PO No.
    Excludes the current document if provided.
    """
    if not customer or not po_no:
        return []

    filters = {
        "customer": customer,
        "po_no": po_no,
        "docstatus": ["<", 2],  # exclude cancelled
    }
    if current_name:
        filters["name"] = ["!=", current_name]

    duplicates = frappe.get_all(
        "Sales Order",
        filters=filters,
        fields=["name"],
        limit=20,
        order_by="modified desc",
    )
    return [d.name for d in duplicates]
