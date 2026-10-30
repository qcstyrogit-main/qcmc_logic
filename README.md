## QCMC Logics

Company Business Rules and Logics

### User Transaction Dashboard

Open **User Transaction Dashboard** through Desk search or visit
`/app/user-transaction-dashboard` as a System Manager. Select **Date From** and
**Date To** to see employees/users as rows and transaction DocTypes as columns,
with row/column totals and summary cards. The default range is the current
month through today and data loads automatically. Changing a date refreshes the dashboard; **Refresh** reloads
the counts for the selected dates.

The filter bar above the cards contains visible date fields and searchable
**Modules**, **Displayed DocTypes** and **Displayed Users** selectors. Empty
selections show all available values. Use Modules to narrow columns by their
ERPNext module, and Displayed DocTypes to choose individual transaction columns.
Use Displayed Users to choose the employees/accounts included in the matrix.
**Activity View** defaults to **With Activity**, showing users and DocTypes with
created documents. Choose **Without Activity** for eligible users who created
nothing, or **All** to include both groups and permission-relevant zero columns.
Explicitly selected DocTypes remain visible even when they have no activity.

The **Using**, **Not Using**, **Usage Rate** and **Total Transactions** cards
summarize the selected date/module/DocType/user scope regardless of Activity View.
Eligible users are enabled System Users with current DocType-level **Create**
permission in that scope. Read-only users do not inflate Not Using. Usage Rate
is Using divided by eligible users, or a dash if there are none. Current Create
access follows Frappe's effective roles and custom DocType permissions; it does
not evaluate document-specific warehouse/company restrictions or imply activity
from reading, editing, submitting, or logging in.

Grid cells show **0** for Create access without activity and **—** for no current
Create access. Positive counts remain visible even after access or account state
changes. Rows outside the eligible population with retained counts are labeled
**Historical activity** and excluded from the usage-rate denominator. Transaction
cards retain those counts; table footer totals apply to the displayed rows.

Counts include draft, submitted and cancelled documents by their original
creator and creation time, including the entire final day. The dashboard covers
persisted, top-level submittable DocTypes, including custom transactions;
master records, child rows, Single and virtual DocTypes are excluded. Employee
names use the linked user account, falling back to the user's full name or ID.
Users and DocTypes with zero activity are available through Activity View. Deleted documents are
excluded; retained documents from deleted user accounts still appear under
their original user ID. Both the page and its data endpoint require System Manager access.
The existing User Transaction Activity report remains available.

Deploy with the normal app migration, or sync this Page alone using
`bench --site erp.qcstyro.local reload-doc qcmc_logics page user_transaction_dashboard`
and clear the site's cache. This Page uses its standard script; no asset build
or additional dependencies are required.

### Resizable List Columns

On desktop ERP List pages, drag the right edge of a column header to resize it.
Widths are saved in each user's personal settings separately for each DocType.
Double-click the edge to fit the header and longest loaded value. Keyboard users can focus
the divider and use arrow keys (Shift for larger steps); Home resets the width.
Report grids and the mobile list layout retain their existing behavior.

Form tables such as **Items** also support dragging their header dividers and
double-clicking to fit their loaded values. Their widths are saved separately for each user,
parent DocType and table field, without changing transaction data or the column chooser.
On long desktop lists and tables with overflowing columns, a synchronized
horizontal scrollbar stays at the bottom of the visible table or list panel,
including lists with an independently scrolling inner result area.

### Document Details Sidebar

On saved desktop forms, the panel icon at the bottom of the details sidebar collapses
or restores the right-hand Assign, Attachments, Tags and Share panel. Single-click
the panel border to toggle it; a narrow rail keeps the bottom icon accessible when collapsed. Hiding it
expands the form area and lets sections and tables use its available width with
normal field padding. The preference is remembered for each user in this browser;
new documents and mobile layouts retain their native sidebar behavior.
The collapsed rail includes Assign, Attachments, Tags and Share icons with tooltips.
Selecting an icon opens its native action directly while the panel stays collapsed.
Tags uses a popup containing the existing editor; unavailable actions are omitted.
Rename, Print, Favorite and Info shortcuts are also available. Rename and Print
follow native availability rules. Info shows the document name, last editor,
last edit time, creator and creation time without expanding the sidebar.

### ERP Login Notices

Announcement details include discussions with replies and native `@` mentions.
Comments use avatars, rounded bubbles, nested replies and newest/oldest sorting.
A fixed inline composer supports emoji and Ctrl+Enter to post, with a reply target
and Cancel action. Realtime refreshes preserve unsent drafts. Editing uses the same
inline composer with Save and Cancel, restoring any pending comment/reply draft afterwards.
Reply automatically inserts a highlighted native mention of the comment author
without showing `@`. Changing or cancelling the reply preserves typed draft text.
Clicking a posted user mention opens a small profile popup with only Name,
Department, Position (Employee designation), and Email. Missing details show a dash.
Announcement mention notifications and their email-delivery failure alerts open
the announcement popup directly, including older notifications. The bell shows
the current user's unread count (99+ above 99), updated on realtime events,
reconnect/focus, and native read actions. Email failures use the notification
template's Open Document destination; unrelated notification routes are preserved.
Notification clicks open only the requested detail and close back to the Desk.
Clicking a mention notification marks that selected record read, scrolls to its
comment and highlights the bubble in blue. New saved mentions carry a verified
Comment ID through notification/email links. Legacy notifications use a unique
matching comment when possible; deleted or ambiguous targets open the announcement
without guessing another comment. Large banner images loading later preserve the
target position, and reduced-motion preferences disable the animated highlight.
The navbar bell stays visible when its menu closes. The list and badge refresh
together on realtime events, with a 15-second recovery check for missed events.
The bell list and read actions are personal to the logged-in user, including
Administrator. Read changes sync to that user's other tabs; another user's read
state is unaffected. Use separate browser profiles for simultaneous accounts,
since tabs in the same browser profile share the authentication cookie.
Authors can edit or delete their own comments; System Managers can moderate.
Deleting a parent keeps its replies, labeled as replies to a deleted comment.
Cards show the number of comments including replies. Threads and card counts
update in realtime after committed discussion changes, including changes from
the form timeline. Reconnect/focus checks recover missed updates; no Refresh
button is needed. Standard Frappe Comment records are reused, including form timeline
comments, and mention notifications follow Frappe's enabled-user mention settings.
Announcement mention notifications link directly to the popup, including for
employees without access to the announcement administration form.

For this WSL development tunnel, `scripts/qcmc-realtime-proxy.service` forwards
Socket.IO to port 9000 with the fixed Frappe site header. The Windows Tailscale
`/socket.io` route points to this local proxy on port 9001. The site setting
`qcmc_realtime_same_origin` lets the development browser use the HTTPS tunnel
instead of trying to connect directly to port 9000. Standard production nginx
setups already supply this routing and do not need the local proxy.

For production deployment, include all new app files in the commit, back up the
site, and apply the usual Bench migration, asset build, cache clear and process
restart for the target site. Verify the deployment on the same Frappe/ERPNext
versions and check Socket.IO plus background workers. Do not install this
development machine's Tailscale route or hardcoded proxy service on production.
Smoke-test two separate accounts: each bell must contain only its recipient's
notifications, reading one must leave the other's unread count unchanged, and
a new mention should update the recipient's list and open a single announcement.

After ERP Desk login, a popup shows active published Announcements and the
current month's birthdays and work anniversaries for active Employees.
Work anniversaries use Date of Joining and show the years of service reached
that month, excluding employees who joined in the current year. Birthday
years and ages are omitted.
Today's birthday and anniversary celebrants appear first, with a **Celebrating
today** label and an animated cake. Reduced-motion preferences show a still cake.

The popup has a Close button. A browser storage marker prevents it from
reopening on refresh during the same login session. A new login shows it
again. Announcements follow their existing publication dates and priority.
They appear as three compact cards per row on desktop, with fewer columns on
smaller screens. Each card shows a thumbnail, title and short preview;
**Read more** opens the complete image and formatted announcement.
Cards show the number of unique logged-in users who opened **Read more**.
Each user counts once per announcement across repeat opens, logins and devices.
View tracking starts when this feature is deployed; earlier reads are not counted.

Use the compact **News & Celebrations** button at the bottom left on the main
Desk screen to reopen the popup. Dashboards, workspaces and transaction pages
show a compact button above Search in the left sidebar, keeping controls clear.
Collapsed sidebars show the sparkle icon; older layouts without this sidebar use
the top toolbar. Both button styles support keyboard focus.
For employees with an enabled Tweet account, **Send greeting** opens a
**Send message** popup with an editable multiline birthday or anniversary
message. **Send** delivers it privately through Tweet without navigating away;
**Cancel** returns to the celebrations. Employees without a Tweet account remain
listed.

### Scanner Mobile Authentication Deployment

Persistent scanner device sessions are database-backed and store only SHA-256
token hashes. Deploy them in this order:

1. Deploy the backend and run `bench --site erp.qcstyro.local migrate` with
   `qcmc_mobile_token_rotation_enabled` absent or set to `0`.
2. Deploy the scanner frontend version that saves the `mobile_token` returned
   by every successful `resume_session` response.
3. After that frontend is confirmed in use, enable periodic rotation with
   `bench --site erp.qcstyro.local set-config qcmc_mobile_token_rotation_enabled 1`.

Devices holding the former Redis-only token must perform one normal login after
this deployment. Keep the ERP site behind HTTPS with trusted proxy headers and
secure cookies; production login and resume endpoints reject insecure transport.
Disabling rotation does not disable persistent login or silent SID renewal—it
only prevents replacement-token issuance until the frontend is ready.

### Fixture Workflow

For normal code-reviewed changes, prefer the patch-first workflow:

```bash
bench --site erp.qcstyro.local migrate
python3 apps/qcmc_logic/scripts/clean_fixtures.py
git diff
```

Use this when changes were made in the repository through code, fixtures, and
patches. `migrate` applies patches and imports fixtures into the site;
`clean_fixtures.py` normalizes and validates the repo fixtures without running
`bench export-fixtures`.

You only need `bench export-fixtures` when you intentionally changed metadata
inside the Frappe UI, such as Customize Form, Property Setter, Print Format,
Report, Workflow, or another fixture-backed record, and need to bring that
database change back into the repository.

See `docs/developer_fixture_workflow.md` for the full team workflow and the
rules for when patches, direct fixture edits, and export-fixtures should be used.

Use the wrapper instead of running `bench export-fixtures` directly:

```bash
python3 apps/qcmc_logic/scripts/export_fixtures_clean.py --site erp.qcstyro.local
git diff
```

This runs `bench export-fixtures`, normalizes exported JSON, fixes safe validation
issues, and validates the result.

To export only this app's fixtures, add `--app qcmc_logic`:

```bash
python3 apps/qcmc_logic/scripts/export_fixtures_clean.py --site erp.qcstyro.local --app qcmc_logic
```

If you already ran `bench export-fixtures` manually, use:

```bash
python3 apps/qcmc_logic/scripts/export_fixtures_clean.py --skip-export
git diff
```

The manual order is:

```bash
bench export-fixtures
python3 apps/qcmc_logic/scripts/normalize_fixtures.py
python3 apps/qcmc_logic/scripts/fix_fixture_validation_errors.py
python3 apps/qcmc_logic/scripts/validate_fixtures.py
python3 apps/qcmc_logic/scripts/audit_doctype_fixtures.py
python3 apps/qcmc_logic/scripts/audit_property_setters.py
git diff
```

`normalize_fixtures.py` removes volatile metadata such as timestamps, owners,
assignment tags, and DocType migration hashes, then sorts top-level fixture
records by stable identity so timestamp-only, migration-hash-only, and
order-only fixture exports do not create noisy diffs. After normalization, it
prints a warning when meaningful fixture changes remain.

`fix_fixture_validation_errors.py` fixes safe validation errors, currently
`Custom Field` records whose `name` does not match `{dt}-{fieldname}`.

`validate_fixtures.py` catches import-breaking `Custom Field` mistakes, including
records whose `name` does not match `{dt}-{fieldname}`.

`audit_doctype_fixtures.py` catches custom DocTypes from unexpected app modules
and duplicate DocField names inside exported DocType fixtures. This prevents
cross-app fixture ownership problems, such as LMS or ZKTeco DocTypes being
exported by qcmc_logic, and catches child-table field mix-ups before migration.

`audit_property_setters.py` catches Property Setter records whose `name` points
to one DocType or field while `doc_type`, `field_name`, or `property` points to
another. This prevents merge drift like `Address-main-search_fields` being
attached to a different DocType.

When reviewing `qcmc_logic/fixtures/doctype.json`, stop if an unrelated module
appears. One app should own each custom DocType fixture.

Install the local pre-commit hook once per clone:

```bash
python3 apps/qcmc_logic/scripts/install_git_hooks.py
```

The hook runs `validate_fixtures.py`, `audit_doctype_fixtures.py`, and
`audit_property_setters.py` before each commit.

### Fixture Merge Conflicts

When `git pull --rebase` or merge reports conflicts in `qcmc_logic/fixtures/*.json`,
preview what the safe fixture resolver can fix:

```bash
python3 apps/qcmc_logic/scripts/resolve_fixture_conflicts.py --dry-run
```

Then resolve and stage the fixture JSON conflicts:

```bash
python3 apps/qcmc_logic/scripts/resolve_fixture_conflicts.py
python3 apps/qcmc_logic/scripts/validate_fixtures.py
git diff
```

If you are already inside `apps/qcmc_logic`, use the shorter paths:

```bash
python3 scripts/resolve_fixture_conflicts.py --dry-run
python3 scripts/resolve_fixture_conflicts.py
```

The resolver auto-merges safe JSON fixture cases, such as both branches changing
different fixture records or different fields on the same record. If both
branches changed the same field differently, it stops and prints the exact record
and field that needs human review. Non-fixture conflicts still need manual
resolution.

See `docs/fixture_conflict_commands.md` for the full command runbook and what
each command is for.

#### License

mit
### For faster export fixtures
```bash
alias export-fixtures='python3 apps/qcmc_logic/scripts/export_fixtures_clean.py'
alias clean-fixtures='python3 apps/qcmc_logic/scripts/clean_fixtures.py'
alias clean-fixtures='python3 scripts/clean_fixtures.py'
```
usage: export_fixtures_clean.py [-h] [--skip-export] [--site SITE] [--app APP]


```bash
export-fixtures --site erp.qcstyro.local 
clean-fixtures
```bench --site 


### config test Git PUSH
