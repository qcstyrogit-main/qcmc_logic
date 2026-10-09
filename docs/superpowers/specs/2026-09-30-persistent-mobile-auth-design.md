# Persistent Mobile Authentication Design

## Purpose

Provide durable, per-device authentication for the QCMC scanner application without storing passwords or making Frappe SIDs permanent. A valid mobile device token silently creates a normal short-lived Frappe session after SID expiration. Device credentials remain independently revocable and stop working immediately when their user is disabled.

## Existing Behavior

`qcmc_logic.api.login_scan.login` authenticates a username and password through Frappe, creates a normal SID, and places a 256-bit opaque token in Redis for 30 days. `resume_session` resolves that Redis token and creates another Frappe session. Shared scanner APIs independently resolve the same Redis key through helpers in `stock_reconciliation.py`.

This has four problems:

1. Redis expiry forces routine re-login.
2. Tokens cannot be managed or revoked per device persistently.
3. Token state and device ownership are not auditable.
4. Authentication behavior is duplicated between login and scanner modules.

## Architecture

Authentication is split into three responsibilities:

1. `login_scan.py` exposes login, resume, logout, and administrator revocation APIs.
2. A dedicated mobile-auth service owns token generation, hashing, validation, rotation, revocation, rate limiting, and safe request-user context.
3. Persistent DocTypes store device families and hash-only token generations.

Normal Frappe username/password authentication remains authoritative for initial login. Mobile tokens are refresh credentials only; they do not replace Frappe authorization, roles, warehouse access, or normal SID expiry.

## Data Model

### Mobile Device Session

One record represents one revocable device/token family.

Fields:

- `name`: generated identifier
- `token_family`: unique random family identifier
- `user`: required Link to User, indexed
- `employee`: optional Link to Employee
- `device_id`: optional scanner-provided stable device identifier, indexed
- `device_name`: optional display name
- `created_at`: required Datetime
- `last_used_at`: required Datetime
- `revoked`: Check
- `revoked_at`: optional Datetime
- `revoked_by`: optional Link to User
- `revocation_reason`: optional Small Text

Only System Manager may list/read device-family records in Desk. Authentication code accesses records with explicit permission bypass. The family contains no plaintext credential.

### Mobile Device Token

One record represents one token generation within a device family. A family can temporarily have multiple active sibling generations when concurrent grace retries occur.

Fields:

- `name`: generated identifier
- `device_session`: required Link to Mobile Device Session, indexed
- `token_hash`: required 64-character SHA-256 hex digest, unique and indexed
- `issued_at`: required Datetime
- `last_used_at`: required Datetime
- `status`: `Active`, `Grace`, or `Revoked`
- `grace_expires_at`: optional Datetime
- `predecessor`: optional Link to Mobile Device Token
- `replaced_by`: optional Link to the first replacement token
- `revoked_at`: optional Datetime

No role receives standard read/list/export permission for this DocType. The raw token is never persisted, cached, logged, or included in exceptions.

Frappe migration creates both DocTypes. A patch explicitly creates an additional database index supporting family/status lookups if metadata-generated indexes are insufficient. `token_hash` remains uniquely constrained.

## Token Format and Storage

- Generate every token with `secrets.token_urlsafe(32)`, providing at least 256 bits of entropy.
- Return the opaque token only in the successful response that issues it.
- Store `sha256(token.encode()).hexdigest()`.
- Perform lookup by the unique digest. Where equality checks occur outside indexed lookup, use `secrets.compare_digest`.
- Never include request payloads, query strings, headers, tokens, or passwords in authentication error logs.

## Initial Login

Endpoint:

```text
qcmc_logic.api.login_scan.login
```

Compatible parameters:

```json
{
  "username": "user@example.com",
  "password": "password",
  "device_id": "S2",
  "device_name": "Warehouse Scanner 2"
}
```

`device_id` and `device_name` are optional to preserve existing clients. The endpoint:

1. Enforces the credential-endpoint rate limit.
2. Authenticates with Frappe's normal `LoginManager.authenticate` and `post_login` flow.
3. Resolves the linked Employee, if any.
4. Creates a new Mobile Device Session family and first active token.
5. Returns the existing login response fields, valid SID/CSRF values, and `mobile_token`.

Logging in again creates a separate device family. It does not revoke other devices. No password is retained after Frappe authentication.

## Session Resume

Endpoint:

```text
qcmc_logic.api.login_scan.resume_session
```

The endpoint accepts `mobile_token` from the POST JSON body or POST form body. The current backend has no dedicated mobile-token header contract, so this change does not invent one. It does not read mobile credentials from URL query parameters. It optionally accepts device metadata for display updates but never transfers a token to a different device family.

Within a database transaction it:

1. Hashes the supplied token.
2. Locks the matching Mobile Device Token and parent Mobile Device Session rows.
3. Rejects a missing, unknown, revoked, or expired-grace token.
4. Rejects a revoked device family.
5. reads the linked User directly and rejects a missing or disabled user.
6. Validates and updates token state and last-used timestamps while holding row locks for the shortest possible transaction, then commits and releases those locks before Frappe session creation.
7. Creates a fresh normal Frappe session using `LoginManager.login_as` only after token/session row changes are safely committed.
8. Performs a second short, locked validation of the device family and User after session creation.
9. If revocation or user disablement occurred between validation and session creation, immediately deletes the newly created SID and returns the corresponding terminal authentication error.
10. Returns SID, CSRF token, user details, employee details, and the token the client must retain only after the second validation succeeds.

Every successful resume creates or renews a normal Frappe SID, even when the incoming SID remains valid. SID expiry therefore becomes invisible to the scanner app.

## Rotation and Retry Semantics

Rotation age is 30 days. Grace duration is 10 minutes.

### Current token younger than 30 days

- Keep it active.
- Return the same supplied value as `mobile_token`.
- Update last-used timestamps.

### Current token at least 30 days old

- Change the incoming token from Active to Grace.
- Set `grace_expires_at` once to server time plus 10 minutes.
- Generate and store a new Active replacement in the same family.
- Return the new raw value as `mobile_token`.
- Never extend the predecessor's grace expiry.

### Grace predecessor used during retry

The server stores only hashes and cannot reproduce a replacement token whose response was lost. Therefore a valid grace predecessor creates a new Active sibling token in the same family and returns it. Existing active siblings remain valid, so concurrent responses cannot invalidate each other. The grace predecessor retains its original fixed expiry and does not become active again.

At most five active recovery siblings may be created from one grace predecessor during its grace window. Grace recovery attempts are separately rate-limited per token family and request IP. Exceeding either limit returns `MOBILE_TOKEN_RECOVERY_LIMIT` without creating a token or extending grace.

This behavior guarantees that a bounded number of retries after a lost rotation response can recover without plaintext-token storage. Family revocation invalidates all active siblings and grace predecessors atomically in one transaction.

Old inactive token records may be removed by a scheduled cleanup only after their grace window and an audit retention period. Active sibling credentials remain valid until their own rotation, logout, device-family revocation, user-wide revocation, or user disablement.

## Shared Scanner Authentication

All scanner endpoints use one service function to resolve a mobile token from the database. The legacy Redis resolver in `login_scan.py` and duplicate resolver in `stock_reconciliation.py` are removed.

Business endpoints do not call `LoginManager.login_as`, create a SID, save User, update `tabUser`, or commit during authentication. They set request-local user context for permissions and restore the original context before Frappe's deferred session updater runs. This preserves the prior deadlock fix.

When a custom scanner request supplies `mobile_token`, the endpoint validates that token even when the request already has a valid authenticated SID. It must not bypass token validation merely because `frappe.session.user` is not Guest. A revoked family, revoked token, expired token, or disabled User therefore takes effect immediately on custom scanner APIs.

Device revocation is immediate for refresh credentials and custom scanner APIs. Previously issued SIDs retain normal Frappe expiry on unrelated standard Frappe endpoints; this design does not track device-family-to-SID relationships or globally invalidate those SIDs.

Only `login` and `resume_session` intentionally create Frappe sessions. Scanner business endpoints continue accepting an already authenticated SID or a valid mobile token.

## Logout and Revocation

### Mobile logout

`qcmc_logic.api.login_scan.logout(mobile_token=None)`:

1. Resolves the supplied token when present.
2. Revokes its entire Mobile Device Session family, including all active siblings and grace predecessors.
3. Invalidates the current Frappe SID when present.
4. Returns success when the token/session was already revoked or absent, making logout idempotent.

### Administrator APIs

- `revoke_device_session(device_session)` revokes one family.
- `revoke_all_mobile_sessions(user)` revokes every family belonging to the user.

Both APIs require System Manager and record actor, time, and reason where supplied.

User disablement does not rely on a hook: every token validation checks `User.enabled` directly and denies all families immediately. A User `on_update` hook may additionally mark families revoked for administrative clarity, but correctness does not depend on it.

## Error Contract

Authentication failures use HTTP 401 and preserve a JSON object with `success: false`, stable `error_code`, and a safe message:

- `MOBILE_TOKEN_MISSING`
- `MOBILE_TOKEN_INVALID`
- `MOBILE_TOKEN_REVOKED`
- `MOBILE_TOKEN_EXPIRED`
- `MOBILE_TOKEN_RECOVERY_LIMIT`
- `USER_DISABLED`

Rate-limit failures use HTTP 429 and `AUTH_RATE_LIMITED`. Administrator permission failures use HTTP 403. Temporary database, session-creation, and backend failures use HTTP 503 with `AUTH_TEMPORARILY_UNAVAILABLE`; they are never translated into invalid/revoked credential errors. Internal failures log only sanitized context plus a traceback that cannot contain the supplied token or password.

## Rate Limiting and Transport Security

- Login attempts are limited by request IP and a SHA-256 digest of normalized username.
- Invalid resume attempts are limited by request IP and a short prefix of the already one-way token digest.
- Grace-recovery attempts are limited independently by request IP and token family, in addition to the five-sibling database limit.
- Counters use Redis with atomic increments and bounded TTLs.
- Successful resume requests are not aggressively limited because warehouse scanners may recover concurrently; a broad abuse ceiling still applies.
- Responses include retry timing where available.
- Credential endpoints reject insecure transport in production based on trusted proxy/scheme configuration. Local developer hosts remain usable.
- Deployment must retain Frappe secure-cookie and trusted reverse-proxy HTTPS configuration. No non-expiring SID or global authentication bypass is introduced.

## Response Compatibility

Login retains:

- `success`
- `message`
- `sid`
- `csrf_token`
- `mobile_token`
- existing nested user/employee details

Resume retains `success`, `sid`, `csrf_token`, and the existing string-valued `user` field. It adds employee/profile data under an additive `user_details` object shaped like login's existing nested `user` object; it does not change the type or meaning of any existing field. It always returns `mobile_token`: unchanged before rotation, replacement after rotation or grace recovery. Other additive fields may include `token_rotated`, `device_session`, and `token_grace_expires_at`.

The current scanner frontend saves only resumed `sid` and `csrf_token`; it does not yet persist a replacement `mobile_token`. Backend rotation is therefore controlled by the site configuration key `qcmc_mobile_token_rotation_enabled`, whose absent/default value is false. It remains disabled until the compatible frontend is deployed. While disabled, successful resume returns the unchanged incoming token and still renews the Frappe SID. Tests cover both disabled and enabled rotation modes.

Frontend behavior required:

1. Continue storing `mobile_token` securely on the device.
2. Replace the stored value whenever a successful login or resume response includes `mobile_token`. This frontend behavior is a deployment prerequisite for enabling backend rotation.
3. On ordinary SID expiration, call `resume_session` silently and retry the original request after updating SID/CSRF values.
4. Show the login screen only for the machine-readable terminal authentication errors.

Existing clients that already replace `mobile_token` from responses require no contract-breaking changes. Device ID/name support is additive.

## Legacy Migration

Existing Redis tokens cannot be migrated because only a digest-to-user cache entry exists and no durable device metadata or raw token is available. Deployment removes reliance on those keys. A scanner holding a legacy token receives `MOBILE_TOKEN_INVALID` once and performs a normal password login to establish its persistent device family.

No user password or historical plaintext token is migrated.

## Testing

Tests use real DocType persistence where practical and isolate Frappe session creation at framework boundaries. They prove:

1. Login returns a cryptographically generated mobile token and expected legacy fields.
2. The raw token is absent from every persisted device/token field.
3. An expired/missing SID is silently replaced using a valid token.
4. Resume succeeds after a simulated long inactivity period because device families do not have routine expiry.
5. Tokens younger than 30 days remain unchanged.
6. Rotation remains disabled by default/configuration until the compatible frontend is deployed.
7. With rotation enabled, tokens at least 30 days old rotate and receive exactly 10 minutes of predecessor grace.
8. Grace use creates a valid sibling replacement without extending grace.
9. A grace predecessor creates no more than five active recovery siblings, and excess attempts return `MOBILE_TOKEN_RECOVERY_LIMIT`.
10. Concurrent/retried resume calls leave each returned sibling usable within that bound.
11. Logout revokes active siblings and grace predecessors atomically and is idempotent.
12. Revoked tokens cannot resume.
13. Disabled users cannot resume, regardless of stored token status.
14. Device-family revocation does not affect another device for the same user.
15. Revoke-all invalidates every family for that user.
16. Shared scanner endpoints authenticate through persistent tokens without saving User or creating sessions inside business transactions.
17. Token row locks are released before `LoginManager.login_as`; tests detect unexpected session commits while locks are held.
18. Revocation forced between initial validation and `login_as` causes the newly created SID to be deleted and a terminal revoked-token error to be returned.
19. User disablement forced between initial validation and `login_as` causes the newly created SID to be deleted and `USER_DISABLED` to be returned.
20. A supplied token is validated by custom scanner APIs even when the SID is already authenticated.
21. Login, invalid-resume, and grace-recovery rate limits return stable errors.
22. Query-string mobile tokens are ignored.
23. Temporary backend failures return `AUTH_TEMPORARILY_UNAVAILABLE`, not credential errors.
24. Authentication logs and exception paths contain no raw password or token.

The focused authentication suite must pass before broader scanner and application tests. Existing unrelated suite failures are reported separately rather than hidden.

## Deployment

1. Deploy DocType metadata and indexes with `bench migrate`.
2. Restart Frappe web and worker processes so all scanner modules use the centralized resolver.
3. Confirm reverse-proxy HTTPS and secure-cookie settings.
4. Release the backend with rotation disabled.
5. Deploy a frontend version that always persists a returned replacement `mobile_token`.
6. Enable backend rotation only after that frontend is confirmed deployed.
7. Expect one normal login for devices carrying legacy Redis tokens.

## Non-Goals

- Permanent or globally extended Frappe SIDs
- Password storage or automatic password replay
- Cross-device token sharing
- OAuth/JWT replacement for the existing scanner application
- Changes to warehouse authorization or scanner business rules
