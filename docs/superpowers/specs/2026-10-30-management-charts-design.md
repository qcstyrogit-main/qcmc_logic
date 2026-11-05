# Management charts

User approved proceeding with the proposed chart builder, saved personal layouts,
and printable management view. Reuse the existing dashboard and its System
Manager authorization. Measure creation, including all statuses.

## Approach

Use installed Frappe Charts rather than a separate BI service or new charting
dependency. Keep a focused public JavaScript controller separate from the
dashboard grid. Read scoped totals from the existing dashboard; query creation
time buckets on demand through an authorized endpoint for trends.

## Features and defaults

- Management Charts section between KPI cards and grid. Add/Edit/Remove charts;
  choose title, bar/stacked bar/line/pie/donut, metric and grouping, Top 5/10/All.
- Metrics: documents created, Using, Not Using, Usage Rate, Using vs Not Using.
  Group by module, DocType, user, overall, day or month as appropriate.
- Default charts: adoption donut, transactions by module, most-used DocTypes,
  top users, and monthly creation trend.
- Charts follow dates/module/DocType/user selectors and the full selected scope
  of KPI cards. Activity View only changes the grid; an adoption chart must
  retain both Using and Not Using.
- Count eligible users distinctly per group; compute percentages from group
  denominators. Module totals may overlap users and must not be represented
  as additive user shares. Restrict pie/donut to transaction shares or overall
  adoption. Restrict line/time trends to creation counts; no historic permission
  snapshots are available. Stacked bars use Using vs Not Using.
- Rank categories deterministically; Top-N transaction pie/donut retains an
  Other slice. Preserve user identity when names duplicate. Avoid NaN and show
  appropriate empty states for zero denominators/data.
- Save Layout stores chart definitions for the current user using native Page
  user settings; no account selector. Reload retrieves their saved definitions.
  Reset Defaults is a local edit until saved. Do not save transaction data or
  fixed dates: each reporting session uses the selected dashboard dates.
- Export individual SVG charts; Print Management Report opens a standalone
  document with period, module/DocType/user filters, generation time, KPIs,
  charts and their data tables. Browser Print/Save as PDF excludes Desk/grid UI.
- Trend queries validate selected DocTypes and parameterize dates/owners; zero
  fill days/months. Limit daily trends to 366 days, monthly to 120 months and
  explain limits in UI. Ignore stale responses; clear charts during refresh.
- Escape dynamic titles, labels, tooltips and print content. Destroy old chart
  instances and handle load/save/query errors without damaging the grid.

## Validation

Independent SQL validates trend totals and selected scope. Test authorization,
date and chart configuration validation, personal layout isolation, aggregation,
denominators, Top-N/Other, zero periods, initial/default saved layouts,
stale trend responses, cleanup, rendering escaping, and print/export actions.
