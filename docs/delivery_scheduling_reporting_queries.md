# Delivery Scheduling V2 reporting queries

These MariaDB queries are read-only reconciliation references for a verified site. They are not user-facing permission-aware reports; run them only through an authorized administrator session. Do not infer legacy promise baselines from rows marked `Unreconciled`.

## Schedule commitments, movement history, and Sales finalization

```sql
SELECT
    s.sales_order,
    s.sales_order_item,
    s.name AS schedule,
    s.original_delivery_date AS sales_schedule_date,
    s.original_qty AS sales_original_qty,
    s.quantity_changes,
    s.current_total,
    s.delivery_date AS current_schedule_date,
    s.original_promise_date,
    s.original_promise_qty,
    s.source_schedule,
    s.source_date,
    s.sales_proposed_qty,
    s.logistics_committed_qty,
    s.final_qty,
    s.confirmation_status,
    s.history_status
FROM `tabSO Delivery Schedule` s
WHERE s.sales_order = %(sales_order)s
ORDER BY s.sales_order_item, s.original_promise_date, s.name;
```

```sql
SELECT
    m.sales_order,
    m.sales_order_item,
    m.transaction_id,
    m.operation_type,
    m.source_schedule,
    src.delivery_date AS source_current_date,
    m.destination_schedule,
    dst.delivery_date AS destination_current_date,
    m.quantity,
    m.promise_commitment,
    m.promise_date,
    m.promise_qty,
    m.source_before,
    m.source_after,
    m.destination_before,
    m.destination_after,
    m.related_delivery_note,
    m.related_dn_item,
    m.authorized_by,
    m.authorized_at,
    m.reason
FROM `tabDelivery Schedule Movement` m
LEFT JOIN `tabSO Delivery Schedule` src ON src.name = m.source_schedule
LEFT JOIN `tabSO Delivery Schedule` dst ON dst.name = m.destination_schedule
WHERE m.sales_order = %(sales_order)s
ORDER BY m.authorized_at, m.name;
```

`promise_commitment` keeps different original commitments distinct even when they share a promise date. Movement `promise_qty` is attributed quantity for that original commitment, not necessarily the row's total quantity.

## Draft and submitted Delivery Note allocations

```sql
SELECT
    dn.name AS delivery_note,
    dn.docstatus,
    dn.workflow_state,
    dn.custom_dr_number,
    dn.posting_date AS actual_or_planned_date,
    dni.name AS delivery_note_item,
    dni.against_sales_order AS sales_order,
    dni.so_detail AS sales_order_item,
    dni.custom_so_delivery_schedule AS schedule,
    s.original_promise_date,
    s.delivery_date AS scheduled_date,
    dni.item_code,
    dni.qty,
    dni.rate,
    dni.amount,
    dni.base_amount,
    dn.total_taxes_and_charges,
    dn.grand_total,
    CASE
      WHEN dn.docstatus = 1 THEN 'Submitted delivery; posting_date is actual document date'
      WHEN dn.docstatus = 2 THEN 'Canceled document; not actual delivered quantity'
      ELSE 'Draft allocation only; posting_date is planned, not actual delivery'
    END AS evidence_status
FROM `tabDelivery Note` dn
JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
LEFT JOIN `tabSO Delivery Schedule` s ON s.name = dni.custom_so_delivery_schedule
WHERE dni.against_sales_order = %(sales_order)s
ORDER BY dni.so_detail, s.original_promise_date, dn.creation, dni.idx;
```

## Unfulfilled quantity and canceled DN quantity

```sql
SELECT
    soi.parent AS sales_order,
    soi.name AS sales_order_item,
    soi.item_code,
    soi.qty AS ordered_qty,
    soi.delivered_qty AS sales_order_delivered_qty,
    COALESCE(SUM(CASE WHEN dn.docstatus = 1 AND IFNULL(dn.is_return, 0) = 0
                      THEN dni.qty ELSE 0 END), 0) AS submitted_nonreturn_dn_qty,
    COALESCE(SUM(CASE WHEN dn.docstatus = 2 THEN dni.qty ELSE 0 END), 0) AS canceled_dn_qty,
    GREATEST(0, soi.qty - soi.delivered_qty) AS open_sales_order_qty
FROM `tabSales Order Item` soi
LEFT JOIN `tabDelivery Note Item` dni ON dni.against_sales_order = soi.parent AND dni.so_detail = soi.name
LEFT JOIN `tabDelivery Note` dn ON dn.name = dni.parent
WHERE soi.parent = %(sales_order)s
GROUP BY soi.parent, soi.name, soi.item_code, soi.qty, soi.delivered_qty
ORDER BY soi.idx;
```

For schedule-level unfulfilled demand, reconcile `current_total` against submitted linked DN item quantities and active (`docstatus = 0`) draft allocations. Exclude canceled DNs from current demand; show their count and quantity separately as historical evidence. Do not count a draft's date or quantity as an actual delivery. Submitted non-return DNs are document evidence; reconcile with the SO's delivered quantity and returns before presenting net fulfillment as final.

## Interpretation limits

- `history_status = 'Unreconciled'` means original commitments and promise attribution are not proven; exclude such rows from V2 acceptance and OTIF conclusions.
- `delivery_date` is the current operational schedule date. Use `original_delivery_date` / `original_qty` and movement promise attribution for the original Sales commitment.
- `final_qty` is Sales authorization for DN creation, not a delivered quantity.
- `docstatus = 0` DN rows are draft allocations. `docstatus = 1` is submitted document evidence. `docstatus = 2` is canceled history and must not be presented as fulfillment.
- This file does not define net return accounting or service-level OTIF aggregation; those require the approved return/replacement policy and an agreed attribution rule.
