"""Shared ERPNext Sales Order eligibility for operational delivery scheduling."""

OPEN_DELIVERY_STATUSES = ("To Deliver and Bill", "To Deliver", "To Bill")


def is_open_sales_order_for_delivery(so):
	"""Submitted orders with remaining delivery demand only."""
	getter = getattr(so, "get", None)
	is_return = getter("is_return") if getter else getattr(so, "is_return", False)
	status = getter("status") if getter and getter("status") is not None else getattr(so, "status", None)
	return (getattr(so, "docstatus", None) == 1
		and not is_return
		and status in OPEN_DELIVERY_STATUSES)


def open_delivery_status_sql():
	"""Static SQL fragment; status values are code constants, never user input."""
	return "'To Deliver and Bill', 'To Deliver', 'To Bill'"
