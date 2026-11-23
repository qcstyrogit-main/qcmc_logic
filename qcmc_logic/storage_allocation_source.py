"""Generic source links shared by WRR and scanner allocations."""


def source_reference(doc):
    sources = set()
    if doc.get("purchase_receipt"):
        sources.add(("Purchase Receipt", doc.get("purchase_receipt")))
    elif doc.get("warehouse_transfer"):
        sources.add(("Warehouse Transfer", doc.get("warehouse_transfer")))
    elif doc.get("delivery_note"):
        sources.add(("Delivery Note", doc.get("delivery_note")))
    elif doc.get("stock_entry"):
        sources.add(("Stock Entry", doc.get("stock_entry")))
    else:
        for table, type_field, name_field in (
            ("locations", "source_doctype", "source_document"),
            ("references", "reference_doctype", "reference_name"),
        ):
            for row in doc.get(table) or []:
                if row.get(type_field) and row.get(name_field):
                    sources.add((row.get(type_field), row.get(name_field)))
        if not sources and doc.get("handover"):
            sources.add(("Scanner Warehouse Handover", doc.get("handover")))

    types = {doctype for doctype, name in sources}
    return dict(
        source_doctype=next(iter(types)) if len(types) == 1 else None,
        source_document=next(iter(sources))[1] if len(sources) == 1 else None,
        source_document_count=len(sources),
    )
