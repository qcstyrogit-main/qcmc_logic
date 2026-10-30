---
title: QCMC Logic initial verified knowledge population
status: proposed-for-submission
verification_status: verified-development-source
approval_status: not-approved
deployment_status: not-verified
source_branch: develop
source_commit: 27459e303c906e09686245500b437499a7a6acbd
graphify_release: 27459e303c906e09686245500b437499a7a6acbd
---

# QCMC Logic initial verified knowledge population

## Scope and reconciliation

This record describes committed development behavior at develop commit 27459e3, inspected on 2026-10-19. It does not establish production deployment or business-owner approval. Graphify was queried against its matching develop release, containing 4,656 nodes. The local shared-vault mount has no INDEX.md, so no direct vault edit was made. ICM team-memory recall returned only an unrelated unverified integration-test memory. Git has no reported earlier seed commit dbc3050.

The record excludes credentials, tokens, and transaction data. The staged source document is deduplicated by feature area, while retaining source paths and test evidence.

## Architecture and shared controls

hooks.py is the app integration point: document events, form/list JavaScript, list and document permissions, controller/method overrides, fixtures, and scheduler jobs. The app has custom DocTypes under qcmc_logics/doctype, custom reports under qcmc_logics/report and fixtures, APIs under api, rules under customs, controller replacements under overrides, and migrations under patches.txt and patches/.

The global validation hooks run warehouse-access, warehouse-type, inventory-group, and territory checks for every document. This makes these rules dependencies of transaction types across stock, sales, purchasing, and manufacturing.

Evidence: qcmc_logic/hooks.py:10-22, 193-339, 345-423, 608-622; qcmc_logic/utils.py; qcmc_logic/fixtures/*.json; qcmc_logic/patches.txt.

## Warehouse Transfer and goods in transit

Purpose: transfer stock between warehouses or companies while preserving transfer state, source/target stock ledgers, receiving constraints, and intercompany accounting.

Implementation: hooks.py attaches validate_transfer_type_rules, on_submit, on_update_after_submit, on_cancel, and on_trash from customs/warehouse_transfer_events.py to Warehouse Transfer. The controller validates transfer type, required locations, Material Request and Pick List references, source access, and receiving updates. For intercompany transfers it creates source/target Stock Entries and GL entries; mapping comes from Intercompany Expense Mapping. Cancellation reverses stock and GL effects and marks the transfer cancelled. The form controller is public/js/warehouse_transfer.js.

Relationships: Warehouse Transfer -> warehouse_transfer_events.py -> Stock Entry / Stock Ledger Entry / Journal Entry / Intercompany Expense Mapping; Warehouse Transfer -> Pick List through overrides/pick_list.py; Warehouse Transfer -> Warehouse Access through customs/permissions.py and utils.get_user_allowed_warehouses.

Evidence: hooks.py:24-30; customs/warehouse_transfer_events.py; overrides/pick_list.py; public/js/warehouse_transfer.js; tests/test_warehouse_transfer_cancellation.py; tests/test_warehouse_transfer_province.py. Graphify query "warehouse transfer" identifies the event module and submit, receiving, stock, GL, and cancellation functions.

Open questions: the intended business meaning of each transfer type and the production completeness of intercompany mappings require business/deployment evidence.

## Warehouse access, inventory classification, and storage locations

Purpose: limit warehouse transactions and item movement to a user or role profile's allowed warehouse, inventory group, type, and territory scope.

Implementation: customs/warehouse_access_permissions.py, customs/inventory_group_access_permissions.py, and customs/territory_access_permissions.py are global validation hooks. hooks.py supplies query and has_permission handlers for Delivery Note, Sales Order/Invoice, purchasing documents, Pick List, Stock Entry, Stock Reconciliation, Warehouse Transfer, Work Order, and Job Card. Warehouse Access and Inventory Group Access validate default assignments in doctype/warehouse_access and doctype/inventory_group_access. Storage Location, scanner APIs, a dimension-aware Putaway Rule override, and warehouse-capacity override govern storage-location movement and capacity.

Relationships: User/Role Profile -> Warehouse Access -> allowed warehouse; Inventory Group Access -> transaction validation; Putaway Rule -> Storage Location / Inventory Dimension; Stock Reconciliation -> warehouse transaction permission.

Evidence: hooks.py:13-22, 268-339; utils.py:get_user_allowed_warehouses; overrides/putaway_rule_dimension.py; overrides/warehouse_capacity_dashboard.py; api/storage_location_putaway.py; tests/test_warehouse_access_rollout.py; tests/test_storage_location_paths.py.

## Physical Count and Stock Reconciliation

Purpose: capture physical counts by location and inventory tag, reconcile them to authoritative ERP stock/UOM data, and audit adjustments.

Implementation: Stock Reconciliation is replaced by overrides/stock_reconciliation.py; api/stock_reconciliation.py manages count sessions/results and reconciliation context. Physical Count Submission, Physical Count Scan Transaction, and QCMC Physical Count Result support scans and submissions. Recent changes aggregate inventory-tag groups, preserve exact identities, reject stale-client conditions, and ensure target quantity does not fall below counted quantity when a location baseline is stale.

Evidence: overrides/stock_reconciliation.py; api/stock_reconciliation.py; public/js/stock_reconciliation.js; qcmc_logics/doctype/physical_count_*; tests/test_stock_reconciliation_increment.py; tests/test_stock_reconciliation_ui.js; commits fcee167 through e2d0f71.

## Sales, delivery planning, and Delivery Note restrictions

Purpose: apply customer defaults and territory mapping, retain customer-item history, prevent accidental duplicate delivery actions, schedule/confirm deliveries, and restrict Delivery Note visibility/access.

Implementation: Sales Order validation sets customer account manager and customer/company default warehouse; submit/cancel maintain customer-item history. Delivery Note and Sales Invoice obtain customer warehouse and mapped territory before validation. customs/delivery_note_warning.py detects Sales-Order delivery warnings and public/js/delivery_note.js requires a user choice before save/submit continues. Overrides customize Delivery Note delivery-trip and sales-invoice creation.

Delivery planning uses Sales Order Delivery Scheduling, Delivery Note Printing, and Delivery Schedule Confirmation reports plus the Delivery Schedule Workbench page. The confirmation report saves logistics remarks, adjusts quantities, applies warehouse scope, validates sales/logistics review, and gates DR-printing actions.

Delivery Note list queries use permissions.delivery_note_permission_query; document access uses permissions.sales_transaction_has_permission. The permission module contains Delivery Note/Delivery Note Item SQL checks, including qualifying FOB-customer delivery conditions. These shared rules also scope Sales Order and Sales Invoice.

Relationships: Customer -> customer warehouse defaults -> Sales Order / Delivery Note / Sales Invoice; Sales Order -> Delivery Note -> delivery scheduling reports; Warehouse Access -> Delivery Schedule Confirmation; Delivery Note -> sales/territory permission query.

Evidence: hooks.py:37-60, 195-204, 253-254, 293, 319; customs/sales_order.py; customs/customer_warehouse_defaults.py; customs/sales_transaction_territory.py; customs/delivery_note_warning.py; customs/permissions.py:353 and 756-834; api/delivery_note.py; qcmc_logics/report/delivery_schedule_confirmation; qcmc_logics/report/sales_order_delivery_scheduling; qcmc_logics/report/delivery_note_printing; qcmc_logics/page/delivery_schedule_workbench; tests/test_delivery_note_warning.py; tests/test_delivery_note_invoice.py; tests/test_delivery_scheduling_reports.py.

Open question: no committed source uses the exact label "Sales Order Credit Approval." The Graphify search matched Delivery Note and unrelated text, not a dedicated credit-approval workflow. Confirm the intended rule or its fixture before declaring it implemented.

## Purchasing and Accounting

Purchase Request replaces Frappe workflow application with customs/purchase_request_workflow.apply_workflow. Workflow fixtures and patches implement stockroom/QC approval routes, reason capture, rejection-to-cancellation migration, and approval-state changes. Purchase Receipt has a replacement controller, validation event, and make-purchase-invoice override.

Payment Entry uses overrides/payment_entry.CustomPaymentEntry plus access filters and migration fields for AR/AP series, CWT deductions, underpayment type, and intercompany collection. Warehouse Transfer consumes Intercompany Expense Mapping for intercompany GL creation. This verifies technical behavior, not the business accounting policy or production configuration.

Evidence: hooks.py:45-47, 242, 274, 279, 298, 323; customs/purchase_request_workflow.py; overrides/purchase_receipt.py; overrides/payment_entry.py; patches/add_stockroom_qc_purchase_request_workflow.py; patches/replace_purchase_reject_with_cancel.py; patches/add_intercompany_collection_payment_fields.py; patches/add_payment_entry_underpayment_breakdown.py; patches/add_cwt_rate_defaults.py; tests/test_purchase_request_workflow.py.

## Manufacturing, Roll Production, and production scanners

Purpose: normalize BOM numeric data; calculate SOH/operation time, roll required kilograms, component rates, and roll formulation; apply requirements to Work Orders; synchronize Job Card progress; and restrict manufacturing documents by warehouse/company.

Implementation: the BOM before_validate hook chains normalize_bom_numeric_fields, apply_bom_soph_and_operation_time, apply_roll_required_kg, fetch_missing_component_rates, and apply_roll_formulation_rules. Work Order validation checks BOM/company compatibility and roll formulation. Stock Entry sets actual-weight UOM and warehouse code, validates final Job Card time logs before submit, then updates them on submit/cancel. Job Card lifecycle events synchronize non-final-operation progress. Work Order and Job Card have warehouse permission handlers.

Weekly Production Plan and its child tables model production, extrusion, secondary items, and detail rows. Recent commits update roll-code use and calculate daily-volume quantities from plan hours. Scanner, manufacture-receive, handover, material-transfer, and warehouse-workflow DocTypes/APIs add controlled scans and audit records.

Evidence: hooks.py:61-108, 333-339; customs/bom_*.py; customs/work_order_formulation.py; customs/manufacturing_warehouse_access.py; customs/stock_entry.py; customs/job_card.py; overrides/work_order.py; overrides/job_card.py; qcmc_logics/doctype/weekly_production_plan; qcmc_logics/doctype/manufacture_receive_*; qcmc_logics/doctype/scanner_warehouse_handover*; api/manufacturing_scanner.py; api/warehouse_handover.py; api/warehouse_workflow.py; tests/test_bom_soph.py; tests/test_stock_entry_events.py; tests/test_work_order_job_card.py; tests/test_weekly_production_plan.py; tests/test_manufacturing_scanner.py; tests/test_warehouse_handover.py; commits a3fb97d, 2e375e6, 3754eb2, cd64551.

## HR, payroll, machine shop, and reports

Salary Slip validation applies attendance lateness, employer contributions, HMO deductions, declared income tax, and loan-component rows; HMO and income-tax routines also run before save/submit. Attendance and Overtime Slip normalize overtime. HMO Rate Plan and Employee HMO Enrollment validate their inputs. Payroll Entry, Salary Structure Assignment, staffing plans, and Job Requisition controllers/permissions are customized.

Machine Shop Job Request, Maintenance Job Order, Machine Shop Repairs and Project, Daily Job Schedule/Report, and Job Card Downtime each have validation or lifecycle handling. Workflow fixtures are the source of truth for their transitions.

Custom Script Reports include Booklet Monitoring, Employee Attendance Viewer, User Transaction Activity, Delivery Note Printing, Delivery Schedule Confirmation, and Sales Order Delivery Scheduling. Fixture exports contain query reports, print formats, list-view settings, server/client scripts, roles, permissions, workflows, property setters, custom fields, DocTypes, email templates, and translations.

Evidence: hooks.py:109-169, 268-339; customs/salary_slip_*.py; customs/attendance_overtime.py; customs/overtime_slip.py; customs/hmo_*.py; customs/machine_shop_*.py; customs/daily_job_*.py; fixtures/workflow.json; qcmc_logics/report; tests/test_daily_job_report.py; tests/test_machine_shop_job_request.py; qcmc_logics/report/user_transaction_activity/test_user_transaction_activity.py.

## Integrations, print formats, schedulers, and migrations

QZ/LX-310 raw printing is implemented by api/lx310_print.py, form JavaScript, and add_lx310_raw_print_client_script. Aika GPS and Delivery Trip OSRM are external integrations. OAuth/Frappe Assistant Core, LMS, notifications, and print/query-report methods are overridden in hooks.py. Scheduler hooks run daily attendance-schedule work and hourly/daily utilities. Patches include metadata repair and migrations for storage locations, inventory dimensions, warehouse-transfer fields, physical counts, permissions, and workflow state.

Evidence: hooks.py:240-265, 345-423, 608-622; api/lx310_print.py; integrations/aika_gps.py; api/delivery_trip_route.py; patches.txt; patches/.

## Status and required follow-up

All statements are Verified against committed development source and the named tests where present. None are Approved because no business-owner approval evidence was found. None are Deployed because no deployed environment was inspected.

Obsidian mount/index access and direct Graphify/ICM write procedures are unavailable to the current account. The supported knowledge wrapper requires a reviewer-approved submission. This is the staged, deduplicated record for that submission; after explicit approval it should be submitted under the central module selected by the vault maintainer, and the returned commit must be recorded.

