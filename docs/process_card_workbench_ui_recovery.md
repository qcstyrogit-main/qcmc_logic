# Process Card creation UI freeze

## Findings

Creation renders a standalone Frappe Shift Type Link control. In the installed
v16 `form/controls/base_control.js`, `set_value()` runs asynchronous validation,
sets the model/input, and invokes `df.change`. Rebuilding the form from that
callback can repeatedly create controls and schedule more change callbacks.
A successful creation-context API response does not rule out this UI problem.

The page now hydrates the server-validated Shift Type with `set_input()`.
User changes update the two dependent time inputs without rebuilding the page.
Callbacks from detached controls are ignored. Existing same-value and route
request guards remain in place.

Frappe's installed `views/pageview.js` caches Page scripts under
`_page:process-card-workbench` in localStorage and reads them when developer mode
is disabled. A hard refresh does not remove that cache. The inspected site and
common configuration do not enable developer mode. The browser's actual cached
script was not available for inspection.

The new Desk startup asset removes this page's cached script if it lacks the
current UI revision marker. It preserves other Page caches and the session's
machine/shift creation defaults. Future changes needing cache invalidation must
update the marker in both the Page script and startup asset, and the startup
asset version in `hooks.py`.

## Recover an existing browser session

From a responsive Desk tab on the same ERP origin, run this in the browser
console, then select the machine and Create Process Card again:

```javascript
localStorage.removeItem("_page:process-card-workbench");
location.reload();
```

This removes only the cached Workbench code in that browser. It does not change
documents. It also makes the corrected Page script available immediately if the
running site's hooks cache has not yet picked up the new startup asset.

## Verification and limits

Run `node qcmc_logic/tests/test_process_card_workbench_ui.cjs` and
`node qcmc_logic/tests/test_production_floor_workbench_ui.cjs`. The creation test
executes `render_creation`, models asynchronous control change callbacks,
checks silent hydration and dependent time updates, and rejects detached
callbacks. Cache tests cover stale/current scripts, unrelated storage, and
blocked browser storage.

18 Process Card UI tests and 8 Floor Navigator UI tests passed. JavaScript
syntax checks and `git diff --check` passed. A full browser run was unavailable:
the installed Electron executable cannot load `libnss3.so`. No site migrations,
service restarts, site cache commands, or production document writes were run.
