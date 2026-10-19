# Delivery confirmation critical fixes

Proposed engineering knowledge; module: Selling / Delivery. Not submitted to shared knowledge.

## Findings and implementation

- Releasing a Delivery Note requires decisions for exactly all its current items, including items hidden by warehouse/date filters. Each item needs a valid Logistics reason. Partial selection is rejected before document mutation.
- Deferred quantity is original affected DN item quantity minus approved quantity. Subtract that difference from the source SO schedule and add it to the destination. Do not replace the source schedule quantity with the approved DN quantity: other drafts and delivered quantities may share that schedule.
- Workbench autosaves are serialized. Refresh, filter reload, Open Report, and Proceed wait for saves. Failed saves retain browser edits and block those actions until reload. Document locks and modified timestamps detect concurrent changes; successful saves propagate the new timestamp to the other visible rows of that DN.

## Evidence

- qcmc_logic/qcmc_logics/report/delivery_schedule_confirmation/delivery_schedule_confirmation.py
- qcmc_logic/qcmc_logics/page/delivery_schedule_workbench/delivery_schedule_workbench.py
- qcmc_logic/qcmc_logics/page/delivery_schedule_workbench/delivery_schedule_workbench.js

Validation: 25 scheduling Python tests and three JavaScript autosave tests passed on 2026-10-19. JavaScript syntax and git whitespace checks passed. No schema changes.

Limitations: no interactive browser verification or real concurrent-user load test. Existing whole-DR movement and final-quantity override behavior remain separate follow-ups. After a failed save users must copy unsaved values before reloading. Shared knowledge/memory services were unavailable (missing mount and SSH configuration permission error).
