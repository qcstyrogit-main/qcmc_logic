# Previously approved Purchase requests

In the Material Request list, enable **Include requests I previously approved**
to add Purchase requests on which you completed an approval stage. Disable it to
return to the usual owner/current-stage list. Other filters remain active, and
the choice is saved only for the current user. Reload Desk after deployment to
load the new checkbox.

Previous approval permits opening a request even after it leaves your stage;
it does not grant editing, submission, cancellation, deletion or amendment.
Existing DocType, warehouse and territory permissions remain required. If another
current role already permits an action, that independent role continues to apply.
The option adds approval history to the list; it does not remove current requests.

`custom_pr_previous_approvers` is a hidden, read-only, no-copy JSON list maintained
by the Material Request controller. Valid approval/evaluation transitions and PPIC
forwarding add the acting user once. Draft routing, Receive, Submit, ordinary saves
and cancellations do not add users. Client attempts to change membership are
rejected, including on submitted documents and cancellation. New copies/amendments
start without inherited approval membership. Normal versions and workflow comments
continue to provide the detailed audit trail.

The deployment patch recovers older approvals only from server Version records
showing a transition out of an approval stage. It does not infer membership from
editable comments, current roles, Request By text, or imported ownership. Older
requests with no reliable audit evidence cannot be recovered automatically.

The checkbox uses a personal user default; it does not change workflow states or
business data. List counts use uncached accurate counts to reflect preference
changes. The checkbox occupies its own toolbar row. The legacy MR ID client script
is disabled because moving the last row column on each refresh breaks header
alignment when returning to the list; ERPNext retains its normal ID column.

Validation:

```sh
./env/bin/python -m unittest \
  qcmc_logic.tests.test_purchase_request_history \
  qcmc_logic.tests.test_material_request_list_permissions
node apps/qcmc_logic/qcmc_logic/tests/test_material_request_list_ui.js
```

Apply `qcmc_logic.patches.add_purchase_request_approval_history` for a targeted
deployment. It creates the field, backfills verified membership, preserves the
existing list script's refresh behavior, and clears metadata caches. Matching
fixtures and the Material Request list hook preserve the configuration on migration.
