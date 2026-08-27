"""Delivery Trip routing without requiring a locally hosted OSRM instance."""

import math
from urllib.parse import urlparse

import frappe
from frappe.utils import add_to_date, cint, now_datetime, time_diff_in_seconds


DEFAULT_OSRM_BASE_URL = "https://router.project-osrm.org"


def _get_osrm_base_url():
	"""Return the configured OSRM endpoint or the public demo router."""
	base_url = (frappe.conf.get("osrm_base_url") or DEFAULT_OSRM_BASE_URL).strip().rstrip("/")
	parsed = urlparse(base_url)
	if parsed.scheme not in {"http", "https"} or not parsed.netloc:
		frappe.throw("Invalid osrm_base_url. Use a complete HTTP or HTTPS URL.")
	return base_url


def _route_optimizer_module():
	try:
		from route_optimizer.api import delivery_trip
	except ImportError:
		frappe.throw("The Route Optimizer app is not installed.")

	# Route Optimizer defaults to localhost. Setting the endpoint for each request
	# makes a local OSRM/Docker service optional and supports site-level config.
	delivery_trip.OSRM_BASE = _get_osrm_base_url()
	# The upstream helper saves after resolving stop coordinates, while both route
	# actions save again after applying their results. Defer persistence to that
	# final save so linked Delivery Notes emit only one update notification.
	delivery_trip._get_stop_points = lambda trip: _get_stop_points_without_save(
		trip, delivery_trip
	)
	return delivery_trip


def _get_stop_points_without_save(trip, route_module):
	"""Resolve stop coordinates in memory; the calling route action saves once."""
	points = []
	rows = []

	for row in trip.delivery_stops:
		address_name = row.get("address_name")
		if not address_name:
			customer = row.get("customer")
			if not customer:
				frappe.throw("Delivery Stop missing both Customer and Address Name.")

			address_name = route_module._get_customer_shipping_address(customer)
			if not address_name:
				frappe.throw(f"No Address found for customer: {customer}")
			row.address_name = address_name

		lat, lng = route_module._get_or_create_coords_from_address(address_name)
		lat = float(lat)
		lng = float(lng)

		if row.meta.has_field("custom_latitude"):
			row.custom_latitude = lat
		if row.meta.has_field("custom_longitude"):
			row.custom_longitude = lng

		points.append((lat, lng))
		rows.append(row)

	return points, rows


@frappe.whitelist()
def optimize_route_osrm(delivery_trip):
	return _route_optimizer_module().optimize_route_osrm(delivery_trip)


@frappe.whitelist()
def calculate_etas_osrm(delivery_trip):
	return _route_optimizer_module().calculate_etas_osrm(delivery_trip)


@frappe.whitelist()
def get_routing_status():
	base_url = _get_osrm_base_url()
	return {
		"osrm_base_url": base_url,
		"uses_public_demo": base_url == DEFAULT_OSRM_BASE_URL,
	}


@frappe.whitelist()
def get_live_vehicle_position(delivery_trip):
	"""Return the assigned Vehicle's latest AIKA position for the trip map."""
	trip = frappe.get_doc("Delivery Trip", delivery_trip)
	trip.check_permission("read")
	if not trip.vehicle:
		return {"available": False, "reason": "No Vehicle is assigned to this Delivery Trip."}

	vehicle = frappe.db.get_value(
		"Vehicle",
		trip.vehicle,
		[
			"name", "license_plate", "custom_gps_tracking_enabled",
			"custom_gps_device_name", "custom_gps_last_position",
			"custom_gps_latitude", "custom_gps_longitude", "custom_gps_speed_kph",
		],
		as_dict=True,
	)
	if not vehicle or not vehicle.custom_gps_tracking_enabled:
		return {"available": False, "vehicle": trip.vehicle, "reason": "GPS tracking is not enabled for this Vehicle."}

	latitude = float(vehicle.custom_gps_latitude or 0)
	longitude = float(vehicle.custom_gps_longitude or 0)
	if not latitude or not longitude:
		return {"available": False, "vehicle": vehicle.name, "reason": "No GPS position has been received yet."}

	age_seconds = None
	if vehicle.custom_gps_last_position:
		age_seconds = max(0, int(time_diff_in_seconds(now_datetime(), vehicle.custom_gps_last_position)))
	return {
		"available": True,
		"vehicle": vehicle.name,
		"license_plate": vehicle.license_plate,
		"device_name": vehicle.custom_gps_device_name,
		"latitude": latitude,
		"longitude": longitude,
		"speed_kph": float(vehicle.custom_gps_speed_kph or 0),
		"position_time": vehicle.custom_gps_last_position,
		"age_seconds": age_seconds,
		"stale": age_seconds is None or age_seconds > 600,
	}


@frappe.whitelist()
def request_live_vehicle_update(delivery_trip):
	"""Queue one AIKA refresh for the Vehicle assigned to this readable trip."""
	trip = frappe.get_doc("Delivery Trip", delivery_trip)
	trip.check_permission("read")
	if trip.docstatus == 2 or not trip.vehicle:
		return {"queued": False, "reason": "The trip is cancelled or has no Vehicle."}
	frappe.enqueue(
		"qcmc_logic.integrations.aika_gps.fetch_delivery_trip_vehicle",
		queue="short", delivery_trip=trip.name,
		job_id=f"delivery-trip-live-gps-{trip.name}", deduplicate=True,
	)
	return {"queued": True, "vehicle": trip.vehicle}


def _traffic_level(speed_kph):
	speed = float(speed_kph or 0)
	if speed < 10:
		return "heavy"
	if speed < 25:
		return "slow"
	return "moving"


def _distance_meters(first, second):
	lat1, lon1 = math.radians(float(first.latitude)), math.radians(float(first.longitude))
	lat2, lon2 = math.radians(float(second.latitude)), math.radians(float(second.longitude))
	dlat, dlon = lat2 - lat1, lon2 - lon1
	a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
	return 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@frappe.whitelist()
def get_fleet_traffic_observations(delivery_trip, minutes=30):
	"""Return recent, anonymized fleet-speed observations for a map overlay."""
	trip = frappe.get_doc("Delivery Trip", delivery_trip)
	trip.check_permission("read")
	if not trip.vehicle:
		return {"available": False, "reason": "No Vehicle is assigned."}

	tracker = frappe.db.get_value("Vehicle", trip.vehicle, "custom_aika_tracker")
	if not tracker:
		return {"available": False, "reason": "The assigned Vehicle has no AIKA account."}

	minutes = min(max(cint(minutes), 5), 120)
	cutoff = add_to_date(now_datetime(), minutes=-minutes, as_datetime=True)
	rows = frappe.get_all(
		"AIKA GPS Position",
		filters={"tracker": tracker, "position_time": [">=", cutoff], "gps_valid": 1},
		fields=["vehicle", "latitude", "longitude", "speed_kph", "position_time"],
		order_by="vehicle asc, position_time asc",
		limit_page_length=1000,
	)
	observations = []
	counts = {"heavy": 0, "slow": 0, "moving": 0}
	by_vehicle = {}
	for row in rows:
		by_vehicle.setdefault(row.vehicle, []).append(row)
	# Ignore vehicles that remained at essentially one location. A parked truck is
	# not evidence of road congestion.
	moving_rows = []
	for vehicle_rows in by_vehicle.values():
		if len(vehicle_rows) < 2:
			continue
		origin = vehicle_rows[0]
		if max(_distance_meters(origin, row) for row in vehicle_rows[1:]) < 100:
			continue
		moving_rows.extend(vehicle_rows)

	for row in moving_rows:
		latitude = float(row.latitude or 0)
		longitude = float(row.longitude or 0)
		if not latitude or not longitude:
			continue
		level = _traffic_level(row.speed_kph)
		counts[level] += 1
		observations.append({
			"vehicle": row.vehicle,
			"latitude": latitude,
			"longitude": longitude,
			"speed_kph": float(row.speed_kph or 0),
			"position_time": row.position_time,
			"level": level,
		})
	return {
		"available": bool(observations),
		"window_minutes": minutes,
		"observations": observations,
		"counts": counts,
		"notice": "Estimated from recent QCMC fleet speeds; not a public road-traffic feed.",
	}
