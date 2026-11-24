# Dynamic Reorder Management — local development
## Deployment gate
This source is not production-approved. Do not activate automatic updating until
local migration, integration tests, demand reconciliation and permission tests pass.
No new Material Request engine is introduced. ERPNext continues to handle projected
quantity and deficiency. Do not modify core ERPNext.

## Local verification
From the existing WSL bench:
  cd /home/qcmc_admin/frappe-bench
  git -C apps/qcmc_logic status --short
  git -C apps/qcmc_logic diff --stat
  ./env/bin/python -m unittest discover -s apps/qcmc_logic/qcmc_logic/tests -p 'test_dynamic_reorder*.py'
Run with qcmc_logic installed in the bench virtual environment. Inspect changes
before migration. After approval and backup of the development site only:
  bench --site erp.qcstyro.local migrate
  bench --site erp.qcstyro.local clear-cache
  bench build --app qcmc_logic
Restart only if required and explicitly approved.

## Preview
Log in as Administrator. Open Dynamic Reorder Management. Create a policy,
select the actual Finished Goods Inventory Type and enable that policy. Create
explicit company/item-group/warehouse mappings. Create an item override to confirm
production mode and remove its exclusion. Leave master settings preview-only.
Use Preview Recommendations on the settings form; open each history record.
No Item Reorder values or stock movements are changed during preview.
Review actual customer stock movements and returns against ERPNext stock ledger.
Check the monthly gross/return/net quantities and all calculation inputs in details.

## Application
Keep master enabled and preview-only until approved. Only after review, turn
preview-only off for a controlled manual application. Automatic update flags at
master and policy level remain off until the initial integration test is complete.
Apply one history record at a time. Existing reorder values must match the preview.
Fixed overrides, grouped rows and missing/duplicate rows are excluded.
ERPNext standard requests can exceed configured ROQ due to deficiency; this is
not a strict order-to-max engine.

## Rollback
Open an applied history record and use Rollback. If values have since changed
or a later application exists, the service rejects rollback. Disabling the master
switch stops monthly processing but does not revert prior changes or material requests.

## Outstanding validation
Standard report directory creation and registration, standard DocType migration
strategy (current installer uses custom records), grouped warehouse demand,
missing-row creation, manufacturing request-type authorization, duplicate stock
movement reconciliation, abnormal demand handling, bulk approval, delegated
QCMC permissions, scheduler locking/transaction behavior, performance and
full Frappe tests remain incomplete. The other four categories are not active
or fully implemented. Do not deploy to ERP Dev or Production.
