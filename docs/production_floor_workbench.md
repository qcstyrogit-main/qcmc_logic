# Production Floor Workbench

## Design

The Desk Page `production-floor-workbench` shows four top-level sites in order: Guyong, Sta Clara, MC 1, and MC 2. Persistent sites are `Production Site` records, each linked to one Company and one or more existing ERPNext Plant Floors through `Production Site Plant Floor` rows. Before a record exists, read APIs derive the mapping from the supplied Plant Floor naming rules. The first authorized layout save creates that site's record and mapping. The page uses native Desk navigation and existing Workstation and Process Card records. The first canvas contains buildings. Each building owns an interior canvas containing machines, sections, walkways and static shapes. A machine links to one existing Workstation; layouts never create Workstations or Process Cards.

`Production Floor Layout` stores one record per configured Production Site. Its JSON contains geometry and colors only, with a monotonically increasing `layout_version`. Older Plant Floor layout records remain in the table and are not deleted or silently assigned to sites. Coordinates and dimensions are absolute canvas units, rendered with CSS zoom and pan so screen size does not change stored geometry. The page provides View/Edit modes, grid snapping, pointer dragging/resizing, property fields, empty states, and a save action. On screens below 900 px, editing is disabled and the navigation/details panels can be opened separately; navigation remains available.

## API and access

`qcmc_logic.api.production_floor_workbench` exposes `list_sites`, `get_layout`, `get_floor_context` and `save_layout`. The first three are GET methods; saving requires POST. Access requires an existing manufacturing role and a Company visible through Frappe's permission-aware Company list. A Production Site is accepted only when it belongs to such a Company. Its Plant Floor rows must belong to that Company. Workstation context uses a permission-aware list of the site's assigned Plant Floors. Process Card context uses a permission-aware list filtered by selected shift date/type and allowed workstation IDs. Workstation `status` is read directly from ERPNext and is not a live feed.

Editing is restricted to Manufacturing Manager and System Manager, with normal DocType create/write checks. The layout controller validates site ownership, role/company access, geometry bounds and finite values, unique IDs, supported shapes, colors, unique machine links, and enabled Workstations on one of the site's Plant Floors. The API locks the Production Site row, compares `expected_version` with the stored version, then saves through the document ORM. Frappe owns transaction commit/rollback. An outdated save is rejected for reload; no merge is attempted.

## Development setup and verification

On a verified disposable development site, after reviewing pending migration hooks and fixtures:

```sh
bench --site <dev-site> migrate
bench --site <dev-site> clear-cache
```

The read-only mapping uses these supplied rules: for the QC Styro company, Plant Floor names containing `33` map to Sta Clara and all others map to Guyong; for MultiPlast, `FORMING-MC2`, `INJECTION`, and `SHRINKWRAP` map to MC 2 and all others map to MC 1. Review the displayed mappings before the first save. After a site record is created, managers can adjust its Plant Floor rows directly. The current Plant Floor list (for example, CUPS PRINTING and DRYER-ROOM) is not a list of Workstation Types. Workstation Type is a separate field on the Workstation master. Open `/app/production-floor-workbench`, create a building, open it, add a machine, select a Workstation, save, reload, move the machine, save, and inspect an existing Process Card. Test with two browser sessions to confirm a stale editor receives a version error. Verify a Manufacturing User can view but cannot save, and a Manufacturing Manager with Company/Workstation access can edit. Check desktop and tablet widths.

No site migration or browser preview was run as part of Task 03. Source-level tests cover validation, page/schema registration and stale save handling. Database permissions, migrations, transaction isolation and browser interactions still need verification on the disposable development site.

## Extension points

The page keeps `plant`, `building`, `selected`, `context.workstations`, and `context.process_cards` state. Process Card discovery, creation, and Job Card allocation consume the selected Workstation and date/shift context. Future manpower, downtime and scanner panels should add separate APIs and leave layout JSON limited to geometry and appearance.

## Process Card production workflow

Select a site, open a building, then select a machine. Existing cards for the selected Workstation and shift open in the Process Card Workbench. For a new card, choose **Create Process Card** in the machine details panel; this opens the Workbench creation screen with Company, Site, Workstation, Shift Date, and Shift Type carried from the floor selection. Shift start/end are initialized from the selected Shift Type and remain editable for partial or overnight shifts. Select one or more eligible existing Job Cards and choose **Create Process Card and Allocate Job Cards**. The server rechecks create permission, site/workstation membership, Job Card and Work Order access/status/company, and shift validity; it creates the Process Card and links the chosen Job Cards in the same save. The new card then opens in the Process Card Workbench. Creating with no Job Cards is disallowed.

Additional eligible Job Cards can be linked later from the Workbench's **Add Existing Job Card** action. The standard Process Card form remains available for inspection, but normal machine-based production creation and allocation no longer require opening it.
