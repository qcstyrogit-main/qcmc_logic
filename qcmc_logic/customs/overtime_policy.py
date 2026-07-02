from __future__ import annotations

from math import floor

import frappe
from frappe.utils import flt


MINIMUM_OVERTIME_HOURS = 1.0
OVERTIME_INCREMENT_HOURS = 0.5


def normalize_overtime_duration(duration, overtime_type=None, overtime_type_cache=None):
	"""Apply QCMC OT policy: minimum 1 hour, then whole 30-minute increments."""
	hours = flt(duration)
	if hours <= 0:
		return 0.0

	if overtime_type:
		cache = overtime_type_cache if overtime_type_cache is not None else {}
		if overtime_type not in cache:
			cache[overtime_type] = flt(
				frappe.db.get_value(
					"Overtime Type",
					overtime_type,
					"maximum_overtime_hours_allowed",
				)
			)
		maximum_hours = flt(cache.get(overtime_type))
		if maximum_hours > 0:
			hours = min(hours, maximum_hours)

	if hours < MINIMUM_OVERTIME_HOURS:
		return 0.0

	return flt(floor(hours / OVERTIME_INCREMENT_HOURS) * OVERTIME_INCREMENT_HOURS, 2)


def normalize_overtime_details(doc):
	total = 0.0
	overtime_type_cache = {}
	for detail in doc.get("overtime_details") or []:
		duration = normalize_overtime_duration(
			detail.overtime_duration,
			detail.overtime_type,
			overtime_type_cache,
		)
		detail.overtime_duration = duration
		total += duration

	if hasattr(doc, "total_overtime_duration"):
		doc.total_overtime_duration = flt(total, 2)
