# Purchase Request evaluations

The Purchase Request workflow runs on Material Request (`material_request_type = Purchase`).
PR Type is `custom_request_type`. Evaluation approval hands the request to `To Receive`;
Purchasing still performs Receive, then Submit. Evaluation states have docstatus 0.

## Routing

MIS requests approved from Pending QC PM Approval, Pending MC PM Approval,
Pending Logistics Manager Approval, Pending Approval (Asset Management Head), or
Pending Machine Shop Supervisor Approval enter Pending Network Admin Evaluation.
Only Network Admin can approve this evaluation.

Office Supplies & Equipment requests approved from those states **except Pending
Approval** enter Pending Asset Management Evaluation. Only Asset Management User
can approve this evaluation.

Other type/source combinations retain their routes, including the existing
Draft → Pending MIS Supervisor Approval route outside provincial routing below. Company and initial PPIC conditions
remain in effect. Approvers can cancel evaluations with the existing mandatory
reason and terminal read-only behavior. No return/reject routes are introduced.

## Enforcement and history

Three read-only, no-copy fields record the required stage, evaluator, and approval
time. The server sets them. Requests cannot change routing headers during a
targeted manager approval or evaluation, skip evaluation, or edit evaluated item
details afterward. Save evaluator item changes before approving. Derived
fulfilment quantities remain editable by downstream purchasing operations.
Standard workflow comments and document versions retain manager/evaluator history.
The existing print format's To Receive approver becomes the evaluator on these routes.

Roles need the usual document and warehouse access. Role overlap permits the same
person to perform manager and evaluation actions if they hold both roles, but does
not permit skipping a stage. No roles or notification settings are changed.

Pending requests enter evaluations when their manager next approves. Existing
requests already past the manager stage are grandfathered: no document states,
docstatus values, or historical approvals are rewritten. Historical Submitted
labels with docstatus 0 require a separate repair decision.

Partner conversion cannot bypass a pending required evaluation. When converting
an evaluated request, the new company request starts as Draft without inherited
approval evidence. Existing unrelated conversion routes retain their behavior.

## Deployment and checks

The idempotent patch `qcmc_logic.patches.add_purchase_request_evaluations` creates
the three fields, two state masters, and conditional workflow transitions. It does
not migrate business documents. Matching fixtures preserve configuration on later
migrations. Apply this patch alone when unrelated local changes must not deploy.

Run:

```sh
./env/bin/python -m unittest \
  qcmc_logic.tests.test_purchase_request_evaluations \
  qcmc_logic.tests.test_purchase_request_workflow \
  qcmc_logic.tests.test_material_request_list_permissions
```

Verify in the UI with designated users: each manager source for both types;
company restrictions; non-target routing; evaluator roles/warehouse access;
cancellation reason; history; Purchasing Receive/Submit; and Partner PR conversion.

## Provincial creators

New Material Requests record the authenticated creator in
`custom_pr_original_creator` and whether their effective roles include Provincial
Stock User in `custom_pr_provincial_creator`. Both fields are server-maintained and
no-copy. Administrator has all effective roles and therefore qualifies on new PRs.
Editable Request By text does not determine routing. Classification is captured
even on non-Purchase documents to prevent type-change bypasses, but only Purchase
requests receive provincial routing. Existing PRs are not backfilled.

A provincial creator uses **Submit for Approval** from Draft:

| PR Type | Destination | Approver |
| --- | --- | --- |
| MIS | Pending Network Admin Evaluation | Network Admin |
| Office Supplies & Equipment | Pending Asset Management Evaluation | Asset Management User |
| Motorpool | Pending Logistics Manager Approval | Logistics Manager |

All three approvals lead to To Receive. Other Draft routes are excluded for these
three provincial combinations even when the creator has multiple roles. Other
types and non-provincial routes retain existing conditions. Only the original
creator with the current Provincial Stock User role can submit the Draft.
Subsequent evaluation/Logistics actions use the stored classification and the
approver's designated role, not their provincial membership. Removing a creator's
role does not reroute an existing request; it prevents that creator's Draft action.

Provincial Stock User receives owner-only read, write, create and print access.
Controller permissions limit this new access to Purchase requests and Draft
editing; independent pre-existing role grants and warehouse restrictions remain.
No submit/cancel/amend/delete grants are added to this requester role.

Routing identity and request type cannot change after leaving Draft. Save Draft
type edits before using the workflow action. Direct submit cannot skip evaluation
or Logistics approval. Pending provincial requests cannot be converted to Partner
PRs; submitted approved requests produce a fresh Draft with newly captured creator
classification and no inherited evaluations.

Cross-company Partner PR conversion still performs ERPNext's accounting-dimension
validation. Existing source-company cost centers/defaults can prevent conversion
to another company; this enhancement does not remap accounting dimensions.

The idempotent patch `qcmc_logic.patches.add_provincial_purchase_request_routes`
adds two fields, three transitions, a Draft role row and one scoped permission row.
It does not reclassify historical drafts or move existing requests. Test this with
`qcmc_logic.tests.test_provincial_purchase_request` in addition to the suites above.
