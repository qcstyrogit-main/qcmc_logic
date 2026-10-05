"""Shared identities for Physical Count rows and Inventory Tag groups."""


def _value(row, fieldname):
    if hasattr(row, "get"):
        return row.get(fieldname)
    return getattr(row, fieldname, None)


def normalize_inventory_tag(value):
    """Normalize the optional tag without changing case or internal whitespace."""
    return str(value or "").strip()


def physical_count_location_key(row):
    """Return the ERP inventory identity shared by all tags at one location."""
    return (
        _value(row, "item_code") or "",
        _value(row, "warehouse") or "",
        _value(row, "location")
        or _value(row, "inventory_location")
        or _value(row, "inventory_location_id")
        or "",
        _value(row, "batch_no") or "",
        _value(row, "serial_no") or "",
        _value(row, "uom") or "",
    )


def physical_count_group_key(row):
    """Return the full review-group identity, including Inventory Tag."""
    return physical_count_location_key(row) + (
        normalize_inventory_tag(_value(row, "inventory_tag")),
    )


def latest_physical_count_groups(rows):
    """Return the latest audit snapshot for every Inventory Tag group."""
    latest = {}
    for position, row in enumerate(rows or []):
        key = physical_count_group_key(row)
        timestamp = str(_value(row, "submitted_at") or _value(row, "counted_at") or "")
        rank = (timestamp, int(_value(row, "idx") or 0), position)
        if key not in latest or rank >= latest[key][0]:
            latest[key] = (rank, row)
    return {key: ranked_row[1] for key, ranked_row in latest.items()}
