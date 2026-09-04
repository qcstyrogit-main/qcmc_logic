# Assign Checker QR - Scanner App Integration (Quick Reference)

## 🎯 What Changed?

**Before**: Checker authenticates with Employee QR  
**Now**: Checker scans Assign Checker QR (recommended) OR Employee QR (still works)

## 📱 Scanner App Code

### Simple Implementation

```javascript
// When checker verification screen loads
async function verifyCheckerQR(batchId, scannedQR) {
  try {
    const response = await api.post(
      '/api/method/qcmc_logic.api.warehouse_handover.confirm_checker',
      {
        batch_id: batchId,
        checker_qr: scannedQR,           // ← Scanned QR data (unchanged)
        request_id: generateUUID(),      // ← New UUID for each scan
        device_id: 'Scanner-1'
      }
    );

    if (response.success) {
      // ✅ Checker verified
      showSuccess(`Verified by ${response.checker}`);
      proceedToPicker();
    } else {
      // ❌ Error
      showError(response.error_code + ': ' + response.message);
    }
  } catch (error) {
    showError('Network error: ' + error.message);
  }
}
```

## 🔄 QR Formats (Both Supported)

### Assign Checker QR (NEW - Recommended)
```json
{
  "type": "assign_checker",
  "version": 1,
  "assign_checker_id": "ASSIGN-CHECKER-00001",
  "name": "John Doe"
}
```
**Source**: Assign Checker doctype "Generate QR Code" button
**Use case**: Pre-assigned checker role for warehouse

### Employee QR (Legacy - Still Works)
```json
{
  "employee_id": "EMP-00001"
}
```
**Source**: Employee doctype
**Use case**: Backward compatibility

**Your app**: Just send the raw scanned data. Backend auto-detects type.

## ✅ What Scanner App Must Do

- [x] Scan QR code (existing functionality - no change)
- [x] Send raw QR payload to `confirm_checker` endpoint (existing - no change)
- [x] Generate new UUID for each `request_id` (NEW - required)
- [x] Display response status (existing - works same)
- [x] Handle error codes (existing - same + new `CHECKER_NOT_AUTHORIZED` variants)

## ❌ What Scanner App Must NOT Do

- [ ] Parse the QR payload type (backend does this)
- [ ] Look up Employee records (backend does this)
- [ ] Validate checker permissions (backend does this)
- [ ] Cache checker data (backend handles idempotency)

## 📋 API Signature (No Change)

```
confirm_checker(
  batch_id,        // Required
  checker_qr,      // Required (raw QR data)
  request_id,      // Required (UUID)
  device_id,       // Optional
  mobile_token     // Optional
)
```

**Response** (identical for both QR types):
```json
{
  "success": true,
  "batch_id": "BATCH-001",
  "status": "CHECKED",
  "checker": "EMP-00001",
  "checked_at": "2026-09-04T10:30:00.000Z",
  "duplicate_request": false
}
```

## 🚀 Rollout Checklist

- [ ] No code changes needed for QR scanning logic
- [ ] Test with Assign Checker QR (new)
- [ ] Verify Employee QR still works (legacy)
- [ ] Test error handling (CHECKER_NOT_AUTHORIZED)
- [ ] Verify request_id idempotency (retry same UUID)
- [ ] Deploy to production

## 🔧 Troubleshooting

| Issue | Fix |
|-------|-----|
| "CHECKER_NOT_AUTHORIZED" | Check QR code is valid & checker is active |
| QR won't scan | Check QR label not damaged |
| Request times out | Check network connection |
| "request_id_required" | Bug in scanner app - ensure UUID is sent |
| Different checker confirmed | Check multiple checkers scanned - expected behavior |

## 📞 Support

- Backend API: `/api/method/qcmc_logic.api.warehouse_handover.confirm_checker`
- Full docs: [ASSIGN_CHECKER_INTEGRATION.md](./ASSIGN_CHECKER_INTEGRATION.md)
- Test suite: `test_warehouse_handover.py`

---

**TL;DR**: Assign Checker QR is now supported. Scanner app code doesn't need to change. Backend handles both new and legacy QR formats automatically. ✅
