import frappe
from frappe import _
from frappe.utils import flt, fmt_money

def validate(doc, method=None):
    # frappe.throw("🔥 QCMC HOOK IS FIRING")
    return


def warn_duplicate_invoice_references(doc, method=None):
    if doc.get("is_return") or not doc.get("items"):
        return

    references = _get_item_references(doc)
    if not references:
        return

    matches = _get_duplicate_invoice_reference_matches(doc, references)
    if not matches:
        return

    frappe.msgprint(
        title=_("Possible Duplicate Billing"),
        indicator="orange",
        message=_duplicate_invoice_warning_message(doc, matches),
    )


def _get_item_references(doc):
    references = []
    seen = set()
    for row in doc.get("items") or []:
        pairs = (
            ("sales_order", "so_detail", row.get("sales_order"), row.get("so_detail")),
            ("delivery_note", "dn_detail", row.get("delivery_note"), row.get("dn_detail")),
        )
        for ref_doctype, detail_field, ref_name, detail_name in pairs:
            if not ref_name and not detail_name:
                continue

            key = (ref_doctype, detail_field, ref_name or "", detail_name or "")
            if key in seen:
                continue

            seen.add(key)
            references.append(
                frappe._dict(
                    ref_doctype=ref_doctype,
                    detail_field=detail_field,
                    ref_name=ref_name,
                    detail_name=detail_name,
                )
            )

    return references


def _get_duplicate_invoice_reference_matches(doc, references):
    conditions = []
    values = {
        "current_invoice": doc.get("name") or "",
    }

    for index, reference in enumerate(references):
        condition_parts = []
        if reference.ref_name:
            ref_key = f"ref_name_{index}"
            condition_parts.append(f"sii.{reference.ref_doctype} = %({ref_key})s")
            values[ref_key] = reference.ref_name
        if reference.detail_name:
            detail_key = f"detail_name_{index}"
            condition_parts.append(f"sii.{reference.detail_field} = %({detail_key})s")
            values[detail_key] = reference.detail_name
        if condition_parts:
            conditions.append("(" + " and ".join(condition_parts) + ")")

    if not conditions:
        return []

    rows = frappe.db.sql(
        f"""
        select
            si.name,
            si.docstatus,
            si.currency,
            si.grand_total,
            sii.sales_order,
            sii.delivery_note
        from `tabSales Invoice Item` sii
        inner join `tabSales Invoice` si on si.name = sii.parent
        where si.docstatus in (0, 1)
            and ifnull(si.is_return, 0) = 0
            and si.name != %(current_invoice)s
            and ({' or '.join(conditions)})
        order by si.docstatus, si.posting_date desc, si.name
        """,
        values,
        as_dict=True,
    )

    invoices = {}
    for row in rows:
        invoice = invoices.setdefault(
            row.name,
            frappe._dict(
                name=row.name,
                docstatus=row.docstatus,
                currency=row.currency,
                grand_total=row.grand_total,
                sales_orders=[],
                delivery_notes=[],
            ),
        )
        if row.sales_order and row.sales_order not in invoice.sales_orders:
            invoice.sales_orders.append(row.sales_order)
        if row.delivery_note and row.delivery_note not in invoice.delivery_notes:
            invoice.delivery_notes.append(row.delivery_note)

    return list(invoices.values())


def _duplicate_invoice_warning_message(doc, matches):
    rows = []
    for match in matches:
        status = _("Submitted") if match.docstatus == 1 else _("Draft")
        shared_refs = _format_shared_references(match)
        total = fmt_money(match.grand_total, currency=match.currency)
        possible_duplicate = (
            " - <strong>{0}</strong>".format(_("Possible duplicate"))
            if _same_currency_and_total(doc, match)
            else ""
        )
        rows.append(
            """
            <tr>
                <td>{invoice}</td>
                <td>{status}</td>
                <td>{total}</td>
                <td>{shared_refs}{possible_duplicate}</td>
            </tr>
            """.format(
                invoice=frappe.get_desk_link("Sales Invoice", match.name),
                status=status,
                total=total,
                shared_refs=shared_refs,
                possible_duplicate=possible_duplicate,
            )
        )

    return """
        <p>{warning}</p>
        <table class="table table-bordered table-sm">
            <thead>
                <tr>
                    <th>{invoice_label}</th>
                    <th>{status_label}</th>
                    <th>{total_label}</th>
                    <th>{shared_label}</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
    """.format(
        warning=_(
            "Saving this Sales Invoice may result in duplicate billing or overbilling. "
            "Please review these existing non-cancelled Sales Invoices that share item-level "
            "Sales Order or Delivery Note references."
        ),
        invoice_label=_("Existing Invoice"),
        status_label=_("Status"),
        total_label=_("Total"),
        shared_label=_("Shared Reference"),
        rows="".join(rows),
    )


def _format_shared_references(match):
    references = []
    references.extend(
        _("Sales Order {0}").format(frappe.bold(sales_order))
        for sales_order in match.sales_orders
    )
    references.extend(
        _("Delivery Note {0}").format(frappe.bold(delivery_note))
        for delivery_note in match.delivery_notes
    )
    return ", ".join(references)


def _same_currency_and_total(doc, match):
    return (
        (doc.get("currency") or "") == (match.currency or "")
        and flt(doc.get("grand_total")) == flt(match.grand_total)
    )
