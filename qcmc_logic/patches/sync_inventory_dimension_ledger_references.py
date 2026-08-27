from qcmc_logic.patches.remove_retired_location_inventory_dimensions import (
	sync_active_inventory_dimensions,
)


def execute():
	sync_active_inventory_dimensions()
