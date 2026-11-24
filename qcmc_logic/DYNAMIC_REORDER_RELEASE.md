# Dynamic Reorder Management — release runbook
Status: local validation; production release requires explicit approval.
Scope: qcmc_logic only. Finished Goods only. Do not replace ERPNext's standard replenishment engine.

## Release gates
- Review git status and diff in apps/qcmc_logic; isolate release changes from unrelated work. Record exact reviewed commit and installed Frappe/ERPNext versions.
- Run pure tests, lifecycle, scheduler, boundary, timezone, material request, readiness, scope and both load checks on local only. Re-run approval integration after lock changes.
- Verify global search, actual first-of-month scheduler execution, permission checks and reconcile demand against posted sales and returns.
- Resolve or formally accept scheduler limitations below. Obtain inventory owner sign-off.
- Test backup restoration on an isolated staging site; never run local-only test scripts on production.
- Do not use git reset --hard, bench update, or copy local site database to production.

## Production procedure (operator, approved maintenance window)
1. Confirm production bench location, site name, release commit, dependency versions, available storage and rollback owner. Disable module master if already installed; leave automatic updates and new-row creation disabled.
2. Run bench --site erp.qcstyro.com backup --with-files. Verify backup artifacts, securely preserve site configuration/encryption key and app commit references. Test restoration in staging before release.
3. Deploy only reviewed qcmc_logic release commit via approved source-control procedure; do not deploy unrelated dirty files.
4. Run bench --site erp.qcstyro.com migrate; bench build --app qcmc_logic; bench --site erp.qcstyro.com clear-cache. Restart services using the site's established process during maintenance. Stop on any error.
5. Verify six DocTypes, workspace, analysis report, access restrictions and scheduler registration. Confirm master enabled only when ready, Preview Only checked, Automatic Update Enabled unchecked, Allow New Reorder Rows unchecked. Policy approval required; automatic flags off.
6. Configure explicitly approved production policies/mappings/overrides, reconcile real demand and balances, save a small preview. Do not copy local test policies or histories. Verify no Item Reorder changes or new Material Requests attributable to preview.
7. Monitor scheduler logs at first day 02:00–02:59 Asia/Manila. Confirm correct date, unique history keys, errors and timings. Do not change site timezone.
8. Obtain business sign-off before controlled manual approval. Standard ERPNext reorder can create real submitted Material Requests after thresholds are set; coordinate with purchasing/production. Do not enable automatic updates without separate approval.

## Rollback
Disable automatic updates/master immediately. Preserve logs and history. For individual applied recommendations use guarded Rollback only if current values match and no later application exists. This does not cancel Material Requests already created; review them separately.
For failed software release restore reviewed prior code and compatible database/files only under approved outage and recovery plan. Database restore can discard intervening transactions; reconcile and obtain authorization before restoring. Do not assume reversing code undoes schema migrations.

## Known limitations
- Local load tests are bounded to 1,000 items; simulated demand tests do not measure real demand-heavy SQL workload.
- Scheduler only runs first day 02:00–02:59 Manila; missed window requires controlled manual preview. Failed history rows already recorded are skipped on duplicate monthly runs; review Error Log and generate a fresh manual preview. Redis lock and completion marker are not durable across all outages.
- Access is Administrator-only until delegated permissions are validated.
- Actual production scheduler execution, production restore rehearsal and global search interaction remain pending.
- Other inventory categories are not enabled.
