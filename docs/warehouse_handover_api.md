# Finished Goods Handover and Warehouse Allocation API

All endpoints return `{ "success": false, "error_code": "...", "message": "..." }`
for business validation failures. Scanner calls may authenticate with the existing
`mobile_token`; browser/session clients use their authenticated Frappe session.

Every mutation requires a UUID `request_id`. Repeating the same identifier and
payload returns the original response with `duplicate_request: true`. Reusing it
for different content returns `DUPLICATE_TRANSACTION`.

## Idempotency Guarantees

The backend maintains a persistent record of each `request_id` with its payload
hash and response. The workflow protects against:

- **Network retries**: Same `request_id` + payload always returns the cached result
- **Duplicate detection**: Same `request_id` + different payload returns `DUPLICATE_TRANSACTION`
- **Multiple operations per batch**: Different `request_id` values create independent Stock Entries,
  even for the same Job Card, allowing multiple receiving transactions to coexist

## Workflow

1. `qcmc_logic.api.stock_entry_scanner.create_manufacture_receive_draft`
   records a Draft Manufacture Stock Entry. It does not evaluate Putaway Rules
   and always returns empty `putaway_allocations`. Uses `request_id` as the
   idempotency key. The same Job Card may have multiple Draft Stock Entries
   created by different `request_id` values.
2. `qcmc_logic.api.warehouse_handover.add_stock_entry` creates or extends the
   active handover batch. Permits multiple Stock Entries from the same Job Card
   to be added independently.
3. `qcmc_logic.api.warehouse_handover.generate_handover_qr_payload` issues a
   server token that expires after 24 hours.
4. A user with `Warehouse Checker` calls `get_checker_review`, optionally
   `update_checked_quantities`, then `confirm_checker` using their Assign Checker QR
   or Employee QR.
5. A user with `Warehouse Picker` calls `get_picker_context`, then
   `qcmc_logic.api.warehouse_allocation.create_draft`. Putaway Rules run here,
   and nowhere earlier in this workflow.
6. The Picker calls `verify_location`, `change_location`, or `adjust_quantity`.
7. `complete` succeeds only when every row is `VERIFIED`. It writes final
   locations and quantities to the still-Draft source Stock Entry; it does not
   submit any accounting or stock document.

## Endpoint request fields

### Receiving

`create_manufacture_receive_draft(job_card_id, custom_reference_document,
quantity, request_id, device_id, mobile_token)`

**Required parameters:**
- `job_card_id`: valid Job Card document name
- `custom_reference_document`: Pull Out Slip or receiving transaction identifier
- `request_id`: UUID for idempotency (must be provided, no fallback)
- `mobile_token`: authentication token (unless using Frappe session auth)

**Optional parameters:**
- `quantity`: specific receivable quantity (defaults to full remaining if omitted)
- `device_id`: scanner device identifier for audit trail

**Response includes:**
- `stock_entry_id`: newly created Draft Stock Entry document name
- `job_card_id`: echoed from request
- `work_order_id`: extracted from Job Card
- `custom_reference_document`: echoed from request (Pull Out Slip)
- `finished_items`: receivable item rows
- `putaway_allocations`: always empty (evaluates during allocation, not receiving)
- `docstatus`: 0 (always Draft)
- `status`: "Draft"
- `request_id`: echoed from request
- `duplicate_request`: true if this is an idempotent replay; false if new
- `existing_draft`: always false for new Drafts (true only for internal reuse, deprecated)

**Stable error codes:**
- `REQUEST_ID_REQUIRED`: request_id missing or empty
- `JOB_CARD_NOT_FOUND`: Job Card document not found
- `JOB_CARD_NOT_ELIGIBLE`: Job Card ineligible for manufacture receiving
- `INVALID_QUANTITY`: quantity is zero, negative, or non-numeric
- `QUANTITY_EXCEEDS_RECEIVABLE`: quantity exceeds ERPNext manufacturing rules
- `PULL_OUT_SLIP_REQUIRED`: custom_reference_document missing
- `PERMISSION_DENIED`: user not authorized
- `DUPLICATE_TRANSACTION`: request_id reused with different payload
- `ERP_VALIDATION_FAILED`: other ERPNext validation failures

### Handover

- `add_stock_entry(stock_entry_id, request_id, batch_id?, device_id?, mobile_token?)`
- `generate_handover_qr_payload(batch_id, request_id?, mobile_token?)`
- `get_checker_review(batch_id, token, mobile_token?)`
- `update_checked_quantities(batch_id, request_id, rows, device_id?, mobile_token?)`
- `confirm_checker(batch_id, checker_qr, request_id, device_id?, mobile_token?)`
- `get_picker_context(batch_id, token, mobile_token?)`

`rows` for a Checker correction contains `stock_entry_id`, `stock_entry_row`,
`item_code`, `verified_quantity`, ERP Stock UOM in `uom`, correction `reason`,
and `expected_modified` returned by the review endpoint.

### Allocation

- `create_draft(batch_id, handover_token, transaction_type, warehouse,
  posting_date, posting_time, request_id, additional_details?, device_id?, mobile_token?)`
- `verify_location(warehouse_allocation, allocation_id, scanned_location_id,
  item_code, actual_quantity, transaction_id, device_id?, timestamp?, mobile_token?)`
- `change_location(warehouse_allocation, allocation_id, new_location_id,
  actual_quantity, reason, transaction_id, device_id?, mobile_token?)`
- `adjust_quantity(warehouse_allocation, allocation_id, actual_quantity,
  reason, transaction_id, device_id?, mobile_token?)`
- `complete(warehouse_allocation, request_id, device_id?, mobile_token?)`

## Checker Verification (Assign Checker QR Integration)

### Overview

Checkers can authenticate using either:
1. **Assign Checker QR** (recommended): Pre-printed QR codes for each checker with assigned name
2. **Employee QR** (legacy): Employee document QR codes

### Assign Checker QR Workflow

1. **Setup**:
   - Create "Assign Checker" record for each warehouse checker
   - Link to Employee (or enter name manually)
   - Generate QR code from the record
   - Print and distribute to checker

2. **Scanner Integration**:
   - Checker scans QR code
   - Scanner sends QR payload to `confirm_checker` endpoint
   - Backend validates and confirms batch

### QR Payload Formats

**Assign Checker QR**:
```json
{
  "type": "assign_checker",
  "version": 1,
  "assign_checker_id": "ASSIGN-CHECKER-00001",
  "name": "John Doe"
}
```

**Employee QR** (legacy):
```json
{
  "employee_id": "EMP-00001"
}
```

### confirm_checker Endpoint

```
POST /api/method/qcmc_logic.api.warehouse_handover.confirm_checker

{
  "batch_id": "BATCH-001",
  "checker_qr": "{...json payload...}",
  "request_id": "550e8400-...",
  "device_id": "Scanner-1"
}
```

**Response**:
```json
{
  "success": true,
  "batch_id": "BATCH-001",
  "status": "CHECKED",
  "checker": "CHK-001",
  "checked_at": "2026-09-04T10:30:00",
  "duplicate_request": false
}
```

**Error codes**:
- `CHECKER_NOT_AUTHORIZED`: QR invalid or checker not active
- `SOURCE_DOCUMENT_CHANGED`: Stock Entry modified after review
- `DUPLICATE_TRANSACTION`: request_id reused with different payload

## Scanner application changes

The scanner must store the handover `batch_id` and backend-issued `token`, pass
UUID identifiers for all mutations, and treat returned document names and
allocation IDs as opaque identifiers. It must not calculate Putaway suggestions
locally. Checker and Picker screens should handle the stable error codes and
refresh on `SOURCE_DOCUMENT_CHANGED`.

### Checker QR Scanning

The scanner must:
1. Scan Assign Checker QR (or legacy Employee QR)
2. Extract JSON payload
3. Send raw QR value to `confirm_checker(batch_id, checker_qr, request_id)`
4. Backend automatically resolves QR type (Assign Checker vs Employee)
