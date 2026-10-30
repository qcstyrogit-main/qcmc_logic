# User Transaction Dashboard

## Follow-up requested by user

Make the date range visible above the cards, add searchable header filters
matching the supplied example, and allow choosing displayed modules/DocTypes
and users. Implement as visible labeled in-page Frappe controls: Date From,
Date To, Modules, Displayed DocTypes and Displayed Users. Selection lists are
searchable and empty selections mean all. Header searches filter names/IDs and
counts (including numeric comparisons). Recalculate row/column totals and
summary cards for the displayed scope. Preserve input focus while typing and
retain filters when dates refresh. The prior use of `page.main.html` detached
the native page toolbar; append the dashboard and mount its filters inside it.

## Intent

Provide an ERPNext Desk dashboard showing how many transaction documents each
user created within an inclusive date range, matching the supplied employee by
DocType grid. Count draft, submitted, and cancelled documents once each using
their original creator (`owner`) and creation timestamp, not their last editor
or posting date. Deleted documents cannot be counted.

## Approach

The user requested a dashboard rather than a report. Use a native custom Desk
Page, following the existing Delivery Schedule Workbench page structure.
Standard dashboard number cards cannot express the requested dynamic matrix;
a Script Report was proposed and the user selected a dashboard instead.
No separate website or new dependencies are needed.

## Proposed screen and behavior

- Title: User Transaction Dashboard; route: `/app/user-transaction-dashboard`.
- Date From and Date To filters, initially the current month through today.
  Both dates are required; reject an inverted range. Include the entire final
  day by querying creation before the following midnight.
- Refresh button and automatic reload when date filters change. Show loading,
  error, and empty states; discard stale responses after filter changes.
- Summary cards: total documents, users with activity, and DocTypes with activity.
- Horizontally scrollable matrix: employee/user name, one column per transaction
  DocType, and a total column. Include a totals footer and retain the name column
  while scrolling. Keep zero counts visible.
- Use Employee.employee_name when linked through Employee.user_id; otherwise
  use User.full_name or the user identifier. Aggregate by user identifier so
  repeated employee names or Employee links do not duplicate transactions.
- Include users without activity, including users without an Employee link.
  Keep a user identifier beside the display name so names remain distinguishable.

## Data scope and access (implementation proposals)

Use the existing activity report's transaction scope: persisted, top-level,
submittable DocTypes, including Purchase Order, Purchase Invoice, and custom
transactions. Exclude child tables, Single and virtual DocTypes, and master data.
Show all eligible DocTypes in a stable alphabetical order, even with zero counts.
The phrase “all documents” means all document statuses within these transaction
DocTypes, as confirmed in response to the status question.

Restrict the Page and its server endpoint to System Manager, matching the
existing User Transaction Activity report. Enforce authorization server-side
before querying user, employee, or transaction data. Counts cover site-wide
transactions for this authorized administrative view.

## Implementation boundaries and validation

Add Page metadata, a small read-only whitelisted data endpoint, and the
dashboard JavaScript. Preserve the existing activity report. Use grouped
database counts by owner rather than loading transaction records. Escape all
dynamic labels and user values before rendering.

Validate date boundaries, all three statuses, multiple DocTypes and owners,
zero activity, employee-name fallback and duplicate employee mappings, totals,
and unauthorized access. Check JavaScript syntax and Page metadata. Sync the
Page to the local development site and verify its data against database counts
when the environment permits. No transaction records are edited.
