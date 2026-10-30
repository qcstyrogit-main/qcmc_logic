from qcmc_logic.patches.setup_invoicing_clerk_role import execute as setup_invoicing_clerk_role


def execute():
	# Reapply the dedicated Sales Invoice permissions after the role scope changed.
	setup_invoicing_clerk_role()
