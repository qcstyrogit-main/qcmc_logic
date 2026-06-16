# Material Request Warehouse Rules

This documents the custom warehouse behavior for Material Request records,
especially `Material Transfer` requests.

## Business Rule

The creator of the Material Request is treated as the requesting warehouse.
That means the requester selects their own warehouse as the target warehouse,
then selects the serving warehouse they want to request stock from.

In field terms:

- `set_warehouse` / item `warehouse` = target or requesting warehouse.
- `set_from_warehouse` / item `from_warehouse` = source or serving warehouse.

## Target Warehouse

The target warehouse is the requester's warehouse.

Conditions:

- Must be a non-group Warehouse.
- Must be in the current user's Warehouse Access list.
- Must have `Allow Transact` enabled for the current user.
- Defaults to the user's default allowed transact warehouse on new Material Requests.
- Does not depend on the source warehouse selection.

This avoids a source/target deadlock where the target picker waits for a source,
while the source picker is already using the target as context.

## Source Warehouse

The source warehouse is the warehouse being asked to serve the request.

Conditions:

- Must be a non-group Warehouse.
- Must not be the same as the target warehouse when a target is selected.
- Must not be a province warehouse.
- If at least one Warehouse has `custom_can_serve_material_requests` enabled,
  only enabled warehouses can be selected as source warehouses.
- If no Warehouse has `custom_can_serve_material_requests` enabled yet, all
  non-province warehouses can serve Material Transfer requests.
- If warehouse type restriction is enabled, and the selected target warehouse is not
  a province warehouse, the source warehouse type must match the target warehouse
  type.
- Does not require the Material Request creator to have Warehouse Access or
  `Allow Transact` for the source warehouse.

The requester is allowed to ask a serving warehouse for stock, but this does not
give the requester authority to issue stock from that serving warehouse.

## Validation And Transfer Creation

On Material Request validation:

- Source warehouses are checked with the serving-warehouse rule above.
- For `Material Transfer`, source warehouse company validation is skipped.
- Target warehouse access is still enforced through Warehouse Access.

When creating a Warehouse Transfer from a Material Request:

- The Warehouse Transfer creator must have `Allow Transact` access to the source
  warehouse.
- The selected Material Request must match the Warehouse Transfer source and
  target warehouses.

## Related Code

- Client filters: `qcmc_logic/public/js/warehouse_access.js`
- Link query methods: `qcmc_logic/utils.py`
- Material Request validation override:
  `qcmc_logic/overrides/material_request_override.py`
- Warehouse Access validation:
  `qcmc_logic/customs/warehouse_access_permissions.py`
