# Maintenance Job Order roles and workflow

The existing Maintenance Job module is `Maintenance Job Order`. Its custom
DocType JSON is in `qcmc_logic/fixtures/doctype.json`; its controller hooks and
migration setup are in `qcmc_logic/customs/maintenance_job_order.py`; its client
script is `qcmc_logic/public/js/maintenance_job_order.js`.

Existing fields are reused: `section`, `work_instruction` (the closest existing
field to “work done”), and `breakdown_code`. There is no separate location field;
location is derived from the section. `section` previously linked to
`Job Request Section`, which is a role-profile mapping rather than a section
master. It now uses a Select with the six requested values. Historical stored
values remain in the options and are not rewritten. Case variants of supported
sections are accepted. Other historical values require a deliberate data repair
before those records can follow a section route. The section is immutable after
creation to prevent changing approval routes.

The idempotent patch `setup_maintenance_job_section_workflows` installs all 11
roles, workflow states/actions, six section routes in the existing workflow, and permissions.
Existing before/after-migrate hooks also reconcile the configuration after fixture
sync. Old workflows are deactivated, not deleted.

`Maintenance Job Order Approval` is updated in place and is the only active
workflow for this DocType. Its transitions have section conditions for all six
routes. No separate section workflows or “Maintenance Job Order flow” are created.
Controller validation enforces the section's state owner on saves and transitions.
The existing workflow API override delegates Maintenance Job Orders to a handler
that preserves legacy submitted `docstatus`. New jobs retain `docstatus=0` through
all four business states. These state names do not trigger Frappe submission.
Legacy records retain their document status.

All listed roles can read/write at DocType level; only Draft owners can create.
Controller rules restrict actual writing to the owner of the current section and
state. No DocType role has delete or cancel permission. The new roles also receive
read/select access to Breakdown List for the existing link field. Existing unrelated
permissions are retained; the controller rules apply to those users too, including
Administrator unless assigned the required business role.

Approved saves allow only `work_instruction` and `breakdown_code`, for matching
location Maintenance users. Entering Approved and leaving Approved permit only
the workflow-state change; entering is authorized by the Submitted owner and
leaving by the matching Maintenance role. Neither transition permits simultaneous
business-field edits. Framework-managed modified timestamps are excluded from
business-field comparisons. Child-table content is also compared.

## Deployment and automated checks

Run from the bench directory on the target site:

```sh
bench --site <site> migrate
bench build --app qcmc_logic
bench --site <site> clear-cache
```

Run focused isolated controller checks from the app directory:

```sh
python3 -m unittest discover -s qcmc_logic/tests -p test_maintenance_job_controls.py
node --check qcmc_logic/public/js/maintenance_job_order.js
```

The isolated tests exercise all six routes, state owners, forward transitions,
wrong-location roles, Approved permitted/forbidden changes, section swaps,
skipped states, and legacy submitted Approved edits. The setup was applied to `erp.qcstyro.local` and repeated successfully. Full migrate and
browser/API verification are still required; these tests do not simulate Frappe's
entire persistence layer.

## Manual checklist

Use separate test users with only the roles required for each step. Run the
complete Draft → Submitted → Approved → Active flow for every row:

| Section | Draft editor / Submit | Submitted editor / Approve | Approved editor / Activate | Active editor |
| --- | --- | --- | --- | --- |
| GUYONG - PRODUCTION | Production Encoder - SMB | Production Foreman - SMB | Maintenance - SMB | Maintenance - SMB |
| STA CLARA - PRODUCTION | Production Encoder - STCLA | Production Foreman - STCLA | Maintenance - STCLA | Maintenance - STCLA |
| MC - PRODUCTION | Production Foreman - MC | Production Foreman - MC | Maintenance - MC | Maintenance - MC |
| MC - RM | RM - MC | RM - MC | Maintenance - MC | Maintenance - MC |
| GUYONG - RM | RM - SMB | RM - SMB | Maintenance - SMB | Maintenance - SMB |
| STA CLARA - RM | RM - STCLA | RM - STCLA | Maintenance - STCLA | Maintenance - STCLA |

For each row:

- [ ] Draft owner can create/save/Submit; other roles cannot create for that section.
- [ ] Submitted owner can save/Approve; Draft owner cannot edit or advance unless also assigned that role.
- [ ] Approved matching Maintenance user can save work instruction and breakdown code.
- [ ] Every other Approved field is read-only, including section, dates, item, company, and requested by.
- [ ] API saves changing any other Approved field raise PermissionError; verify section changes and child-table edits where present.
- [ ] Both other-location Maintenance roles see every Approved field read-only and cannot save or Activate via API.
- [ ] Production/RM users cannot edit either Approved exception field or Activate via UI/API.
- [ ] Matching Maintenance user can Activate without modifying other fields; Active edits require that same location's Maintenance role.
- [ ] Reverse transitions, state skipping, direct submission/cancellation, and changing section after creation are rejected.
- [ ] A user holding a wrong-location Maintenance role plus a Production/RM role remains blocked in Approved.

Migration checks:

- [ ] All 11 roles exist, with no duplicates; roles/workflow configuration remains stable after a second migrate.
- [ ] `Maintenance Job Order Approval` is the only active workflow, with 18 section-conditioned transitions; other pre-existing workflows remain present but inactive.
- [ ] Existing record values/custom fields remain intact. Test a legacy `docstatus=1` Approved record: matching Maintenance can edit the two exception fields and Activate without changing docstatus.
- [ ] Existing historical sections remain visible; unsupported historical values are identified for data repair.
- [ ] No role has Maintenance Job Order delete permission.
