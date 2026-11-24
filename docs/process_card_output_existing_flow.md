# Existing production output flow before Process Card Workbench integration

## Task 01 storage and API

Task 01 adds `save_output_checkpoint` in `qcmc_logic/api/job_card_time_log.py`. It locks an existing Job Card, validates a positive `completed_qty`, rejects overlapping time intervals, appends an employee-less row to ERPNext's native `Job Card.time_logs`, and saves the Job Card through Frappe's document API. The exact interval is the retry identity: a retry with the same quantity is idempotent, while a different quantity for the same interval is rejected. The existing implementation does not provide an edit/correction endpoint, rejected quantity, Process Card association, or correction audit history.

## ERPNext quantity handling and QCMC synchronization

ERPNext v16 `JobCard.validate_time_logs` recalculates `total_completed_qty` from every native Time Log row's `completed_qty` and performs native time-log/workstation overlap validation. The existing Task 01 endpoint therefore changes the official Job Card completed quantity when it records a positive output row. The `Job Card.on_update` hook then calls `sync_non_final_operation_progress` in `qcmc_logic/customs/job_card.py`, which synchronizes those official totals to non-final Work Order operations. Task 01 must remain available for this established posting path.

## Process Card relationship and current Workbench

A Process Card's `jobs` child table explicitly links Job Cards; no membership can be inferred from shift, date, or Workstation alone. `get_process_card_context` loads the Process Card under its permission checks and returns the linked Job Cards' native status, target, official completed quantity, item, Work Order, and operation. The page currently displays those links and a Production Output placeholder. There is no Process Card checkpoint API or output-specific UI yet.

## Integration boundary for Task 06

Operational checkpoint good/rejected quantities must not be written into native `completed_qty`, because doing so enters the existing official ERPNext output path and Work Order synchronization. The safe minimal extension reuses the existing Job Card Time Log child rows and their interval validation, but stores operational quantities in separate QCMC custom fields on those same rows. Operational rows keep native `completed_qty` at zero. This preserves Task 01's legacy positive-`completed_qty` posting path while allowing the Process Card Workbench to maintain operational output and correction history without changing official Job Card or Work Order totals. No checkpoint rows are inferred or reassigned to a Process Card; each operational row carries an explicit Process Card link.
