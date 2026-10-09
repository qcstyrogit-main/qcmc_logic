# Persistent Mobile Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build persistent, hash-only, per-device scanner credentials that silently renew normal Frappe sessions and remain independently revocable.

**Architecture:** Two restricted DocTypes represent a device family and its token generations. A focused `mobile_auth` service owns token lifecycle, rate limiting, locking, and request-token extraction; `login_scan` owns HTTP response compatibility and Frappe session creation, while scanner business APIs only establish request-local user context.

**Tech Stack:** Python 3, Frappe/ERPNext DocTypes and database API, MariaDB row locks, Redis counters, `secrets`, `hashlib`, Frappe integration tests.

**Spec:** `docs/superpowers/specs/2026-09-30-persistent-mobile-auth-design.md`

## Global Constraints

- Generate opaque credentials with `secrets.token_urlsafe(32)` and persist only SHA-256 hashes.
- Never persist or log plaintext mobile tokens or passwords.
- Use constant-time comparison for any token-derived equality check performed outside the unique indexed hash lookup.
- Accept mobile tokens from POST JSON/form bodies only; do not read URL query parameters and do not add a new header contract.
- Keep Frappe SID expiry unchanged; every successful resume creates a fresh normal SID.
- Keep `qcmc_mobile_token_rotation_enabled` false by default until the compatible frontend is deployed.
- With rotation enabled, rotate after 30 days and preserve a fixed, non-extendable 10-minute predecessor grace window.
- Permit at most five active grace-recovery siblings per predecessor and rate-limit recovery attempts.
- Revoke every token generation in a device family atomically on logout/device revocation.
- Do not change scanner business permissions or remove existing response fields.
- Distinguish terminal credential errors, disabled users, rate limits, and temporary backend failures.
- Do not hold mobile-token row locks while `LoginManager.login_as` creates/commits a Frappe session.
- Re-lock and revalidate the device family and User after `LoginManager.login_as`; destroy the new SID if revocation or disablement won the race.
- Validate a supplied token on every custom scanner API even when the request already has an authenticated SID.
- Device revocation is immediate for custom scanner APIs and refresh credentials; unrelated standard Frappe endpoints keep previously issued SIDs until normal expiry.

## Review Focus

- A token supplied simultaneously in a query string and POST body must use only the body value and must never authenticate from the query value; pin in Task 3.
- A session failure after token rotation commit must return a temporary error while the fixed grace predecessor still permits recovery; pin in Task 3.
- Two concurrent grace retries near the five-sibling boundary must never create a sixth recovery sibling; pin in Task 2.
- A disabled/deleted User linked to an otherwise active token must not be translated into an invalid-token error; pin in Task 2.
- Logout racing with resume must serialize on the family lock so no post-revocation token becomes usable; pin in Task 4.

---

### Task 1: Persistent Device and Token Schema

**Files:**
- Create: `qcmc_logic/qcmc_logics/doctype/mobile_device_session/__init__.py`
- Create: `qcmc_logic/qcmc_logics/doctype/mobile_device_session/mobile_device_session.json`
- Create: `qcmc_logic/qcmc_logics/doctype/mobile_device_session/mobile_device_session.py`
- Create: `qcmc_logic/qcmc_logics/doctype/mobile_device_token/__init__.py`
- Create: `qcmc_logic/qcmc_logics/doctype/mobile_device_token/mobile_device_token.json`
- Create: `qcmc_logic/qcmc_logics/doctype/mobile_device_token/mobile_device_token.py`
- Create: `qcmc_logic/patches/add_mobile_device_session_indexes.py`
- Modify: `qcmc_logic/patches.txt`
- Create: `qcmc_logic/tests/test_mobile_auth.py`

**Interfaces:**
- Produces: DocTypes `Mobile Device Session` and `Mobile Device Token` with the exact fields and permissions defined by the spec.
- Produces: `qcmc_logic.patches.add_mobile_device_session_indexes.execute() -> None` for family/status and user/revoked indexes.

- [ ] **Step 1: Write failing schema and permission tests**

Add `TestMobileAuthSchema` tests asserting `token_hash` is required and unique, token records have no standard read/list permissions, only System Manager can read device-session records, and expected family/status indexes exist after migration setup.

- [ ] **Step 2: Run the schema tests and verify RED**

Run: `bench --site erp.qcstyro.local execute qcmc_logic.tests.test_mobile_auth.run_mobile_auth_tests`

Expected: FAIL because the DocTypes do not exist.

- [ ] **Step 3: Add both DocTypes and index patch**

Implement the schema from the spec. Keep token metadata hidden/read-only, omit token permissions, add only System Manager permissions to device sessions, and register the idempotent index patch in `patches.txt`.

- [ ] **Step 4: Migrate and verify GREEN**

Run: `bench --site erp.qcstyro.local migrate`

Run: `bench --site erp.qcstyro.local execute qcmc_logic.tests.test_mobile_auth.run_mobile_auth_tests`

Expected: schema tests PASS.

- [ ] **Step 5: Commit**

```bash
git add qcmc_logic/qcmc_logics/doctype/mobile_device_session qcmc_logic/qcmc_logics/doctype/mobile_device_token qcmc_logic/patches/add_mobile_device_session_indexes.py qcmc_logic/patches.txt qcmc_logic/tests/test_mobile_auth.py
git commit -m "feat: add persistent mobile device session schema"
```

### Task 2: Token Lifecycle Service

**Files:**
- Create: `qcmc_logic/api/mobile_auth.py`
- Modify: `qcmc_logic/tests/test_mobile_auth.py`

**Interfaces:**
- Produces: `issue_device_token(user: str, employee: str | None = None, device_id: str | None = None, device_name: str | None = None) -> MobileTokenResult`.
- Produces: `validate_device_token(raw_token: str, *, allow_rotation: bool) -> MobileTokenResult`.
- Produces: `resolve_device_token_user(raw_token: str) -> str | None` for business endpoints without session creation.
- Produces: `revoke_device_family(device_session: str, actor: str | None = None, reason: str | None = None) -> bool`.
- Produces: `revoke_all_user_families(user: str, actor: str | None = None, reason: str | None = None) -> int`.
- Produces stable exceptions carrying `error_code`, safe message, and HTTP status without the raw credential.

- [ ] **Step 1: Write failing issue/storage tests**

Test that issuance uses a 32-byte URL-safe secret, returns plaintext once, persists only its SHA-256 digest, associates user/employee/device metadata, and never places plaintext in any database field.

- [ ] **Step 2: Run tests and verify RED**

Run the focused runner and expect missing service failures.

- [ ] **Step 3: Implement minimal issuance and active-token validation**

Use `secrets.token_urlsafe(32)`, `hashlib.sha256`, direct indexed digest lookup, explicit enabled-User lookup, and direct timestamp updates. Do not use Redis as credential storage.

- [ ] **Step 4: Verify issuance tests GREEN**

Run the focused runner and expect the issuance/storage tests to pass.

- [ ] **Step 5: Write failing rotation, grace, concurrency, and revocation tests**

Add tests for rotation disabled by default; unchanged token before 30 days; rotation at 30 days; exactly 10-minute immutable grace; grace recovery siblings; five-sibling maximum under concurrent locked attempts; separate device families; family and user-wide revocation; disabled and deleted users; and logout/resume lock serialization.

- [ ] **Step 6: Run tests and verify RED**

Expected failures identify missing lifecycle transitions and locking.

- [ ] **Step 7: Implement lifecycle state machine and short row-lock transactions**

Lock token then family consistently with `SELECT ... FOR UPDATE`; check family/user state; count recovery siblings under the same lock; create at most five; never update `grace_expires_at` after first assignment; atomically revoke all family generations. Read `qcmc_mobile_token_rotation_enabled` with false as the default.

- [ ] **Step 8: Add bounded Redis rate counters**

Implement login, invalid-resume, grace-recovery, and broad successful-resume counters using only IP plus non-reversible username/token/family digests in keys. Return stable 429 errors and never include raw inputs in keys or logs.

- [ ] **Step 9: Run focused lifecycle tests GREEN**

Run the focused runner; expect all service tests to pass.

- [ ] **Step 10: Commit**

```bash
git add qcmc_logic/api/mobile_auth.py qcmc_logic/tests/test_mobile_auth.py
git commit -m "feat: add persistent mobile token lifecycle"
```

### Task 3: Compatible Login and Resume APIs

**Files:**
- Modify: `qcmc_logic/api/login_scan.py`
- Modify: `qcmc_logic/tests/test_mobile_auth.py`

**Interfaces:**
- Consumes: Task 2 issuance, validation, rate-limit, and safe exception interfaces.
- Produces: `login(username, password, device_id=None, device_name=None)` with existing fields plus persistent `mobile_token`.
- Produces: `resume_session(mobile_token=None, device_id=None, device_name=None)` returning fresh `sid`, `csrf_token`, the existing string-valued `user`, additive `user_details`, and always `mobile_token`.
- Produces: body-only `_get_mobile_token_arg(explicit=None) -> str` that ignores URL query credentials.

- [ ] **Step 1: Write failing login and response-compatibility tests**

Assert normal Frappe password authentication, persistent token issuance, unchanged existing user/employee fields, optional device metadata, rate limiting, and no password/token leakage through sanitized error handling.

- [ ] **Step 2: Run tests and verify RED**

Expected: Redis issuance and old signatures violate assertions.

- [ ] **Step 3: Implement persistent login with existing response shape**

Remove Redis token issuance. Keep `LoginManager.authenticate/post_login`, then issue the device token and return all existing fields unchanged.

- [ ] **Step 4: Verify login tests GREEN**

Run the focused runner.

- [ ] **Step 5: Write failing resume/session-boundary tests**

Assert POST JSON and form extraction; query-only token rejection; body value winning over a simultaneous query value; fresh SID on every success; unchanged string-valued `user`; additive `user_details`; unchanged token while rotation is disabled; replacement token when enabled; long-inactivity recovery; disabled-user distinction; invalid/revoked/expired distinctions; production HTTP rejection with local-development allowance; and `AUTH_TEMPORARILY_UNAVAILABLE` for database/session failures.

Instrument tests so any `frappe.db.commit` invoked by `LoginManager.login_as` while the token/family lock marker is active fails. Also assert a post-rotation session failure leaves the fixed grace predecessor recoverable. Force family revocation and User disablement separately after initial validation but before/during `login_as`; assert the second locked check deletes the newly created SID and returns `MOBILE_TOKEN_REVOKED` or `USER_DISABLED` without a successful SID response.

- [ ] **Step 6: Run tests and verify RED**

Expected: old resume path and token extraction fail.

- [ ] **Step 7: Implement body-only resume and session sequencing**

Finish token transaction and clear its lock scope before calling `LoginManager.login_as`. After session creation, perform a second short locked family/User validation. If it fails, delete the new SID before returning the terminal error. Always return the token to retain only after revalidation succeeds. Map only known terminal states to 401; map unexpected database/session failures to 503 without exposing request values.

- [ ] **Step 8: Run focused API tests GREEN**

Run the focused runner; expect all login/resume tests to pass.

- [ ] **Step 9: Commit**

```bash
git add qcmc_logic/api/login_scan.py qcmc_logic/tests/test_mobile_auth.py
git commit -m "feat: persist and renew scanner authentication"
```

### Task 4: Logout and Administrator Revocation APIs

**Files:**
- Modify: `qcmc_logic/api/login_scan.py`
- Modify: `qcmc_logic/api/mobile_auth.py`
- Modify: `qcmc_logic/tests/test_mobile_auth.py`

**Interfaces:**
- Consumes: Task 2 family revocation functions.
- Produces: `logout(mobile_token=None) -> dict` with idempotent success and current SID invalidation.
- Produces: `revoke_device_session(device_session, reason=None) -> dict` restricted to System Manager.
- Produces: `revoke_all_mobile_sessions(user, reason=None) -> dict` restricted to System Manager.

- [ ] **Step 1: Write failing logout/admin tests**

Assert repeated logout success, atomic invalidation of active/grace/sibling generations, SID deletion, one-device isolation, revoke-all behavior, System Manager enforcement, and the post-`login_as` revocation/disablement race behavior defined in Task 3. Confirm locks are not held during `login_as`.

- [ ] **Step 2: Run tests and verify RED**

Expected: endpoints are absent.

- [ ] **Step 3: Implement logout and administrator endpoints**

Resolve body token safely, revoke the family in one transaction, then invalidate the current Frappe SID. Treat already missing/revoked credentials as successful logout; keep administrator APIs strict and audited.

- [ ] **Step 4: Run focused tests GREEN**

Run the focused runner.

- [ ] **Step 5: Commit**

```bash
git add qcmc_logic/api/login_scan.py qcmc_logic/api/mobile_auth.py qcmc_logic/tests/test_mobile_auth.py
git commit -m "feat: revoke scanner device sessions"
```

### Task 5: Migrate Shared Scanner Authentication

**Files:**
- Modify: `qcmc_logic/api/stock_reconciliation.py`
- Modify: `qcmc_logic/api/location_transfer.py`
- Modify: `qcmc_logic/tests/test_stock_reconciliation_increment.py`
- Modify: `qcmc_logic/tests/test_mobile_auth.py`
- Test as consumers: `qcmc_logic/api/stock_entry_scanner.py`, `qcmc_logic/api/warehouse_workflow.py`, `qcmc_logic/api/storage_location_putaway.py`, `qcmc_logic/api/reconciliation_context.py`

**Interfaces:**
- Consumes: `resolve_device_token_user` and body-only token extraction from Task 2/3.
- Preserves: `_authenticate_request_user(mobile_token=None) -> str | None` for existing scanner imports.
- Preserves all scanner authorization and response contracts.

- [ ] **Step 1: Write failing shared-auth regression tests**

Assert persistent tokens authenticate Physical Count and representative shared scanner consumers; query tokens are ignored; revoked/disabled tokens fail; a supplied token is validated even when a valid SID already authenticated the request; no `LoginManager`, User save/update, session creation, or authentication commit occurs inside business transactions; original request user is restored before deferred session update. Also prove that a revoked family immediately blocks custom scanner APIs while the same pre-existing SID remains governed by normal Frappe expiry outside those APIs.

- [ ] **Step 2: Run focused scanner tests and verify RED**

Run mobile-auth and Stock Reconciliation focused runners.

- [ ] **Step 3: Replace duplicate Redis resolvers with centralized persistent resolution**

Keep the compatibility helper in `stock_reconciliation.py`, but delegate extraction/validation to `mobile_auth.py`. Update Location Transfer's direct resolver use. Do not alter warehouse or document permission checks.

- [ ] **Step 4: Run focused scanner tests GREEN**

Run:

```bash
bench --site erp.qcstyro.local execute qcmc_logic.tests.test_mobile_auth.run_mobile_auth_tests
bench --site erp.qcstyro.local execute qcmc_logic.tests.test_stock_reconciliation_increment.run_stock_reconciliation_increment_tests
```

Expected: both runners PASS.

- [ ] **Step 5: Commit**

```bash
git add qcmc_logic/api/stock_reconciliation.py qcmc_logic/api/location_transfer.py qcmc_logic/tests/test_stock_reconciliation_increment.py qcmc_logic/tests/test_mobile_auth.py
git commit -m "refactor: centralize scanner mobile authentication"
```

### Task 6: Deployment Guardrails and Full Verification

**Files:**
- Modify: `docs/superpowers/specs/2026-09-30-persistent-mobile-auth-design.md` only if implementation reveals a contract correction
- Modify: `README.md` or existing deployment documentation if present
- Verify: all files changed in Tasks 1–5

**Interfaces:**
- Produces deployment instructions naming `qcmc_mobile_token_rotation_enabled` and the frontend prerequisite.

- [ ] **Step 1: Document deployment order and configuration**

State that migration/backend deploy occurs with rotation absent/false, the frontend must persist resumed `mobile_token`, and only then may the site config key be enabled. Document one-time legacy-token login and HTTPS/proxy requirements.

- [ ] **Step 2: Run focused authentication and scanner suites**

Run mobile-auth, Stock Reconciliation, Stock Entry Scanner, Manufacturing Scanner, and Location Transfer tests using their dedicated runners or module commands. Require zero failures.

- [ ] **Step 3: Run migration/fixture/static verification**

Run:

```bash
bench --site erp.qcstyro.local migrate
/home/qcmc_admin/frappe-bench/env/bin/python -m compileall -q qcmc_logic/api qcmc_logic/qcmc_logics/doctype/mobile_device_session qcmc_logic/qcmc_logics/doctype/mobile_device_token
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 4: Run broader backend tests**

Run:

```bash
bench --site erp.qcstyro.local run-tests --app qcmc_logic
```

Expected: PASS. If blocked by a pre-existing unrelated collection/import failure, capture the exact traceback and separately prove every affected focused suite passes.

- [ ] **Step 5: Review security invariants from the final diff**

Search for plaintext token persistence/logging, Redis credential storage, query extraction, `User.save`, `tabUser` updates, and `LoginManager` usage inside business authentication. Confirm only login/resume create Frappe sessions.

- [ ] **Step 6: Commit final documentation/verification adjustments**

```bash
git add README.md docs/superpowers/specs/2026-09-30-persistent-mobile-auth-design.md
git commit -m "docs: add scanner authentication deployment steps"
```

Skip this commit when no documentation file changed.
