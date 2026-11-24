# Process Card Foundation

## Scope and schema

This foundation adds two DocTypes in the QCMC Logics module:

- **Process Card**: one workstation and one production shift, with company, optional site, shift date, ERPNext HRMS Shift Type, explicit start/end datetimes, status, remarks, and native creator/modified audit fields. Naming series is `PC-.YYYY.-.#####`.
- **Process Card Job**: child table linking a Job Card and showing its Work Order, operation, and production item. It stores no quantities.

Relations are many-to-many over time: a Process Card has multiple Job Cards, and the same Job Card can be linked from multiple non-overlapping shift cards. Job Cards remain independent of shift ownership.

`site` is a Data field for compatibility with the Navigator's Production Site. When it links to a Production Site record, the company and workstation Plant Floor membership are validated. Legacy cards may still use the Workstation's Plant Floor value directly. Workstation/company consistency uses the Plant Floor company when available, plus each linked Work Order company.

## Validation and status

The controller requires an enabled Workstation, a positive shift window (overnight shifts use the next date for `shift_end`), distinct Job Card links, existing non-cancelled Job Cards, and submitted Work Orders. It verifies the operation against the Work Order and checks Workstation/Company consistency. It deliberately does not reserve or copy production quantities.

Draft, In Progress, For Approval, Approved, and Cancelled are statuses. New cards start as Draft. The current transitions allow operational progress to For Approval, a send-back to In Progress, cancellation, and approval from For Approval. Approval is limited to Manufacturing Manager or System Manager. Approved cards cannot be edited through ordinary save; no Job Card is submitted or closed on approval. Manufacturing User, Manufacturing Manager, and System Manager are existing roles used for read/write access; no new role is introduced.

Shift conflicts are serialized by locking the Workstation row, then checking intersecting windows in the transaction. Draft, In Progress, For Approval, and Approved windows block overlaps. Cancelled cards do not.

## Task 01 and existing customizations

Task 01's output-only Job Card Time Log work remains separate and untouched by this change. Existing shift-based Job Card creation, partial-output synchronization, custom Job Card quantity validation, and final-operation-only Manufacture Stock Entry eligibility remain in place. A later integration task can associate Process Cards with output checkpoint entry while preserving Job Card independence.

## Development installation

From the bench, install/update only on a disposable development site:

```sh
bench --site <dev-site> migrate
bench --site <dev-site> clear-cache
```

The migration synchronizes the two DocType schemas and controller metadata; it is not a production deployment instruction. No migration was run for this task.

## Integration points / next task

- Add a controlled Process Card API/UI for draft creation and status changes.
- The Process Card Workbench reads and associates existing Job Cards through the `jobs` child table; the relation itself is the explicit Process Card shift assignment. Job Card dates are displayed but are not used to infer shift membership.
- Workbench APIs check Process Card, Workstation, Job Card, Work Order, Company, and layout permissions before returning or changing linked records. Association updates lock the Process Card row and use the controller's validation before save.
- Define site/Plant Floor ownership mapping if the business needs a formal site Link.
- Add explicit permission-level and concurrency integration tests on the disposable development site.
- Connect output checkpoints to a selected Process Card without changing native Job Card Time Log semantics.
