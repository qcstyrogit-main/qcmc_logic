# Stock Entry Scanner API - Quick Reference Guide

## TL;DR: What Changed

**Old behavior**: Same Job Card → only one Draft allowed  
**New behavior**: Same Job Card → unlimited independent Drafts via different request_ids

## API Changes

### Before
```javascript
POST /api/method/qcmc_logic.api.stock_entry_scanner.create_manufacture_receive_draft
{
  "job_card_id": "PO-JOB00001",
  "custom_reference_document": "PULL-OUT-001",
  "quantity": 10000,
  "device_id": "Scanner-1"
  // request_id was optional
}
```

### After
```javascript
POST /api/method/qcmc_logic.api.stock_entry_scanner.create_manufacture_receive_draft
{
  "job_card_id": "PO-JOB00001",
  "custom_reference_document": "PULL-OUT-001",
  "quantity": 10000,
  "request_id": "550e8400-e29b-41d4-a716-446655440000", // ← NOW REQUIRED
  "device_id": "Scanner-1"
}
```

## Response Format

### Successful New Request
```json
{
  "success": true,
  "stock_entry_id": "MAT-STE-00001",
  "docstatus": 0,
  "status": "Draft",
  "existing_draft": false,
  "duplicate_request": false,
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "job_card_id": "PO-JOB00001",
  "work_order_id": "MFG-WO-00001",
  "custom_reference_document": "PULL-OUT-001",
  "finished_items": [ ... ],
  "putaway_allocations": [],
  "allocation_count": 0
}
```

### Idempotent Retry (Same request_id)
```json
{
  "success": true,
  "stock_entry_id": "MAT-STE-00001",
  "docstatus": 0,
  "status": "Draft",
  "existing_draft": true,
  "duplicate_request": true,  // ← FLAG: This is a cached replay
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "job_card_id": "PO-JOB00001",
  "work_order_id": "MFG-WO-00001",
  "custom_reference_document": "PULL-OUT-001",
  "finished_items": [ ... ],
  "putaway_allocations": [],
  "allocation_count": 0
}
```

### Error: Request ID Mismatch
```json
{
  "success": false,
  "error_code": "DUPLICATE_TRANSACTION",
  "message": "This request ID was already used with different content."
}
```

## Idempotency Rules

### Rule 1: Same Request = Same Result
```
request_id: uuid-1
payload: {job_card: JC-1, quantity: 10000, ...}
→ Creates STE-001
→ Retrying with SAME uuid-1 and SAME payload
→ Returns STE-001 with duplicate_request: true
→ Does NOT create STE-002
```

### Rule 2: Different Request = Different Draft
```
request_id: uuid-1, job_card: JC-1, pull_out: PULL-001
→ Creates STE-001

request_id: uuid-2, job_card: JC-1, pull_out: PULL-002
→ Creates STE-002 (DIFFERENT DRAFT!)

Both STE-001 and STE-002 can coexist in same handover batch
```

### Rule 3: Payload Mismatch = Error
```
request_id: uuid-1, quantity: 10000
→ Creates STE-001

request_id: uuid-1, quantity: 5000  (DIFFERENT PAYLOAD)
→ Error: DUPLICATE_TRANSACTION
→ Cannot reuse uuid-1 with different data
```

## Implementation Checklist for Scanner Apps

- [x] Generate UUID for each request (v4 format)
- [x] Include request_id in every API call
- [x] Store request_id locally (for retry logic)
- [x] Retry with SAME request_id if network fails
- [x] Use NEW request_id for new operations
- [x] Check duplicate_request flag in response
- [x] Handle DUPLICATE_TRANSACTION error
- [x] Display duplicate_request=true as "cached result, no new entry created"
- [x] Display duplicate_request=false as "new draft created"

## Example Scanner Flow

```javascript
// User initiates Pull Out for Job Card JC-1 (first pull: 10,000)
const request_id_1 = generateUUID();
const response1 = await api.createDraft({
  job_card_id: "PO-JOB00001",
  custom_reference_document: "PULL-OUT-001",
  quantity: 10000,
  request_id: request_id_1
});
// Response: STE-001, duplicate_request: false
showNotification("Draft created: " + response1.stock_entry_id);

// Network fails, user presses Retry
const response1_retry = await api.createDraft({
  job_card_id: "PO-JOB00001",
  custom_reference_document: "PULL-OUT-001",
  quantity: 10000,
  request_id: request_id_1  // ← SAME UUID (idempotent)
});
// Response: STE-001, duplicate_request: true
showNotification("Retry successful: " + response1_retry.stock_entry_id);

// Same Job Card, different pull (second pull: 5,000)
const request_id_2 = generateUUID();
const response2 = await api.createDraft({
  job_card_id: "PO-JOB00001",
  custom_reference_document: "PULL-OUT-002",
  quantity: 5000,
  request_id: request_id_2  // ← DIFFERENT UUID (new operation)
});
// Response: STE-002, duplicate_request: false
showNotification("Second draft created: " + response2.stock_entry_id);

// Now JC-1 has TWO independent drafts:
// - STE-001 (10,000 units from PULL-OUT-001)
// - STE-002 (5,000 units from PULL-OUT-002)
// Both can be added to same handover batch
```

## Stable Error Codes

| Code | HTTP | Meaning | Action |
|------|------|---------|--------|
| `REQUEST_ID_REQUIRED` | 400 | Missing request_id | Generate UUID |
| `JOB_CARD_NOT_FOUND` | 400 | Job Card doesn't exist | Check ID |
| `JOB_CARD_NOT_ELIGIBLE` | 400 | Can't receive from this card | Check status |
| `INVALID_QUANTITY` | 400 | Qty is 0, negative, or non-numeric | Enter valid qty |
| `QUANTITY_EXCEEDS_RECEIVABLE` | 400 | Qty exceeds remaining | Reduce quantity |
| `PULL_OUT_SLIP_REQUIRED` | 400 | Missing custom_reference_document | Scan pull slip |
| `PERMISSION_DENIED` | 403 | User not authorized | Check warehouse access |
| `DUPLICATE_TRANSACTION` | 400 | request_id + different payload | Use new UUID or same payload |
| `STOCK_ENTRY_NOT_DRAFT` | 500 | System error | Contact admin |
| `ERP_VALIDATION_FAILED` | 400 | Other validation error | Check message |

## Testing Scenarios

### Test 1: Create First Draft
```python
def test_first_draft():
    uuid1 = "550e8400-e29b-41d4-a716-446655440001"
    resp = create_manufacture_receive_draft(
        job_card_id="JC-1",
        custom_reference_document="PULL-1",
        quantity=1000,
        request_id=uuid1
    )
    assert resp["success"] == True
    assert resp["stock_entry_id"] == "STE-1"
    assert resp["duplicate_request"] == False
    assert resp["docstatus"] == 0
```

### Test 2: Idempotent Retry
```python
def test_retry():
    uuid1 = "550e8400-e29b-41d4-a716-446655440001"
    # First request
    resp1 = create_manufacture_receive_draft(..., request_id=uuid1)
    ste1 = resp1["stock_entry_id"]
    
    # Retry with SAME request_id
    resp2 = create_manufacture_receive_draft(..., request_id=uuid1)
    ste2 = resp2["stock_entry_id"]
    
    assert ste1 == ste2  # Same draft
    assert resp2["duplicate_request"] == True  # Cached
```

### Test 3: Multiple Drafts
```python
def test_multiple_drafts():
    # First pull
    uuid1 = "550e8400-e29b-41d4-a716-446655440001"
    resp1 = create_manufacture_receive_draft(
        job_card_id="JC-1",
        custom_reference_document="PULL-1",
        quantity=1000,
        request_id=uuid1
    )
    ste1 = resp1["stock_entry_id"]  # e.g., "STE-1"
    
    # Second pull (DIFFERENT UUID)
    uuid2 = "550e8400-e29b-41d4-a716-446655440002"
    resp2 = create_manufacture_receive_draft(
        job_card_id="JC-1",  # SAME Job Card
        custom_reference_document="PULL-2",
        quantity=500,
        request_id=uuid2  # DIFFERENT UUID
    )
    ste2 = resp2["stock_entry_id"]  # e.g., "STE-2"
    
    assert ste1 != ste2  # Different drafts!
    assert resp2["duplicate_request"] == False
```

### Test 4: Conflict Detection
```python
def test_conflict():
    uuid1 = "550e8400-e29b-41d4-a716-446655440001"
    
    # First request
    resp1 = create_manufacture_receive_draft(
        job_card_id="JC-1",
        quantity=1000,
        request_id=uuid1
    )
    assert resp1["success"] == True
    
    # Retry with SAME request_id but DIFFERENT quantity
    resp2 = create_manufacture_receive_draft(
        job_card_id="JC-1",
        quantity=500,  # DIFFERENT!
        request_id=uuid1
    )
    
    assert resp2["success"] == False
    assert resp2["error_code"] == "DUPLICATE_TRANSACTION"
```

## Handover Integration

### Multiple Drafts in One Batch
```python
# Create two drafts for same Job Card
uuid1 = "..."
ste1_response = create_manufacture_receive_draft(
    job_card_id="JC-1",
    custom_reference_document="PULL-1",
    quantity=10000,
    request_id=uuid1
)
stock_entry_1 = ste1_response["stock_entry_id"]  # STE-001

uuid2 = "..."
ste2_response = create_manufacture_receive_draft(
    job_card_id="JC-1",
    custom_reference_document="PULL-2",
    quantity=5000,
    request_id=uuid2
)
stock_entry_2 = ste2_response["stock_entry_id"]  # STE-002

# Add BOTH to same handover batch
from qcmc_logic.api.warehouse_handover import add_stock_entry

batch_uuid_1 = "..."
batch_resp_1 = add_stock_entry(
    stock_entry_id=stock_entry_1,
    request_id=batch_uuid_1
)
batch_id = batch_resp_1["batch_id"]  # e.g., "BATCH-001"

batch_uuid_2 = "..."
batch_resp_2 = add_stock_entry(
    stock_entry_id=stock_entry_2,
    request_id=batch_uuid_2,
    batch_id=batch_id  # Add to SAME batch
)

# Result: BATCH-001 now contains both STE-001 and STE-002
# They are shown as separate source entries, not combined
```

## FAQ

**Q: Why request_id now required?**  
A: Proper idempotency requires identifying each HTTP request uniquely. request_id serves as the deduplication key.

**Q: Can I reuse request_id?**  
A: Only for the SAME operation with the SAME payload. Using the same UUID with different data raises DUPLICATE_TRANSACTION.

**Q: What if I lose the request_id?**  
A: Generate a new UUID for the retry. This creates a new draft instead of retrieving the cached one. Use carefully.

**Q: How long is request_id stored?**  
A: Indefinitely (or until archived). Backend keeps full audit trail in Warehouse Workflow Request table.

**Q: Can I merge two drafts later?**  
A: No. Each draft is independent. You can add both to a handover batch (shown separately), but they remain distinct Stock Entries.

**Q: What about network timeouts?**  
A: Always retry with the SAME request_id. Backend detects this and returns cached result without creating duplicate.

**Q: What if my scanner loses power mid-request?**  
A: If the create succeeded, Warehouse Workflow Request has the record. Next request with same request_id returns cached result. If create failed, try with same UUID—if backend doesn't have record, it creates new draft.
