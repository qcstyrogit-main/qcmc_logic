from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import frappe
import httpx
from frappe import _
from frappe.utils import now_datetime


AIKA_APP_KEY = "7DU2DJFDR8321"
DEFAULT_SERVER_URL = "http://aika168.com"
ALLOWED_HOST_SUFFIX = ".aika168.com"
REQUEST_TIMEOUT_SECONDS = 15


class AikaError(Exception):
	pass


def _safe_login_failure(data) -> str:
	"""Describe an AIKA login failure without exposing device/session data."""
	if not isinstance(data, dict):
		return f"AIKA login returned {type(data).__name__}, not an object."

	fields = ", ".join(sorted(str(key) for key in data)) or "none"
	message = next(
		(
			str(data[key]).strip()
			for key in ("error", "errorMessage", "message", "msg", "result", "status", "state")
			if key in data and isinstance(data[key], (str, int, float, bool)) and str(data[key]).strip()
		),
		None,
	)
	detail = f" AIKA message: {message[:200]}." if message else ""
	return f"AIKA login returned no usable tracker device.{detail} Response fields: {fields}."


def _find_device_info(data):
	"""Accept the known response plus harmless wrapper/list variations."""
	if not isinstance(data, dict):
		return None
	for key in ("deviceInfo", "DeviceInfo", "device", "Device"):
		value = data.get(key)
		if isinstance(value, dict):
			return value
		if isinstance(value, list) and value and isinstance(value[0], dict):
			return value[0]
	for key in ("data", "result"):
		value = data.get(key)
		if isinstance(value, dict):
			device = _find_device_info(value)
			if device:
				return device
	return None


@dataclass(frozen=True)
class AikaDevice:
	device_id: str
	device_name: str
	model: int
	session_key: str
	id_number: str = ""


def validate_aika_url(url: str, *, require_http: bool = False) -> str:
	parsed = urlparse((url or "").strip())
	if parsed.scheme not in {"http", "https"} or not parsed.hostname:
		raise AikaError("AIKA URL must be a complete HTTP or HTTPS URL.")
	if require_http and parsed.scheme != "http":
		raise AikaError("The discovered AIKA OpenAPI endpoint must use its expected HTTP scheme.")
	if parsed.username or parsed.password:
		raise AikaError("Credentials must not be embedded in the AIKA URL.")
	hostname = parsed.hostname.lower().rstrip(".")
	if hostname != "aika168.com" and not hostname.endswith(ALLOWED_HOST_SUFFIX):
		raise AikaError("AIKA URL points to an unapproved host.")
	return parsed.geturl().rstrip("/")


def parse_aika_response(response_text: str) -> dict:
	try:
		root = ElementTree.fromstring(response_text)
		return json.loads(root.text or "{}")
	except (ElementTree.ParseError, json.JSONDecodeError, TypeError) as exc:
		raise AikaError("AIKA returned an invalid response.") from exc


def _parse_position_time(value: str | None):
	if not value:
		return None
	for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
		try:
			# AIKA currently returns UTC despite the TimeZones=8:00 request.
			return datetime.strptime(value, fmt) + timedelta(hours=8)
		except ValueError:
			continue
	return None


class AikaReadOnlyClient:
	"""Minimal AIKA client intentionally containing no device-command methods."""

	def __init__(self, server_url: str = DEFAULT_SERVER_URL):
		self.server_url = validate_aika_url(server_url)
		self.api_url = None
		self.device = None
		self.client = httpx.Client(
			timeout=REQUEST_TIMEOUT_SECONDS,
			follow_redirects=False,
			headers={"Content-Type": "application/x-www-form-urlencoded"},
		)

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		self.logout()
		self.client.close()

	def discover(self):
		response = self.client.get(urljoin(f"{self.server_url}/", "getapp.aspx"))
		response.raise_for_status()
		# Current AIKA discovery returns an HTTP OpenAPI URL. Enforcing the known
		# scheme and domain prevents credential forwarding to an injected host.
		self.api_url = validate_aika_url(response.text.strip(), require_http=True)
		return self.api_url

	def _post(self, method: str, payload: dict, *, include_session: bool = True):
		if not self.api_url:
			self.discover()
		if include_session:
			if not self.device:
				raise AikaError("AIKA session is not authenticated.")
			payload = {**payload, "Key": self.device.session_key}
		response = self.client.post(f"{self.api_url}/{method}", data=payload)
		response.raise_for_status()
		return parse_aika_response(response.text)

	def login(self, username: str, password: str, login_type: int = 1):
		data = self._post(
			"Login",
			{
				"Name": username,
				"Pass": password,
				"LoginType": login_type,
				"LoginAPP": "AKSH",
				"GMT": "8:00",
				"Key": AIKA_APP_KEY,
			},
			include_session=False,
		)
		device = _find_device_info(data) or {}
		if not device.get("deviceID") or not device.get("key2018"):
			raise AikaError(_safe_login_failure(data))
		self.device = AikaDevice(
			device_id=str(device["deviceID"]),
			device_name=str(device.get("deviceName") or ""),
			model=int(device.get("model") or 0),
			session_key=str(device["key2018"]),
		)
		return self.device

	def login_account(self, username: str, password: str):
		data = self._post(
			"Login",
			{"Name": username, "Pass": password, "LoginType": 0, "LoginAPP": "AKSH", "GMT": "8:00", "Key": AIKA_APP_KEY},
			include_session=False,
		)
		user = data.get("userInfo") if isinstance(data, dict) else None
		if not isinstance(user, dict) or not user.get("userID") or not user.get("key2018"):
			raise AikaError(_safe_login_failure(data))
		devices = self._post(
			"GetDeviceList",
			{"ID": user["userID"], "PageNo": 1, "PageCount": 500, "TypeID": 0, "IsAll": True, "Language": "en", "Key": user["key2018"]},
			include_session=False,
		)
		items = devices.get("arr") if isinstance(devices, dict) else None
		if not isinstance(items, list):
			raise AikaError("AIKA account returned no device list.")
		return [
			AikaDevice(
				str(item["id"]), str(item.get("name") or ""), int(item.get("model") or 0),
				str(user["key2018"]), str(item.get("sn") or ""),
			)
			for item in items
			if isinstance(item, dict) and item.get("id")
		]

	def get_tracking(self, device=None):
		if device:
			self.device = device
		return self._post(
			"GetTracking",
			{
				"DeviceID": self.device.device_id,
				"Model": self.device.model,
				"TimeZones": "8:00",
				"MapType": "Google",
				"Language": "en",
			},
		)

	def get_device_status(self, device=None):
		if device:
			self.device = device
		return self._post(
			"GetDeviceStatus",
			{
				"DeviceID": self.device.device_id,
				"TimeZones": "8:00",
				"Language": "en",
				"FilterWarn": "",
			},
		)

	def logout(self):
		if not self.device or not self.api_url:
			return
		try:
			self._post(
				"ExitAndroid",
				{"ID": self.device.device_id, "TypeID": "1"},
			)
		except Exception:
			pass


def fetch_tracker_position(tracker_name: str):
	tracker = frappe.get_doc("AIKA GPS Tracker", tracker_name)
	if not tracker.enabled:
		raise AikaError("AIKA tracker is disabled.")
	password = tracker.get_password("password", raise_exception=False)
	if not password:
		raise AikaError("AIKA password is not configured.")

	try:
		with AikaReadOnlyClient(tracker.server_url or DEFAULT_SERVER_URL) as client:
			devices = {device.device_id: device for device in client.login_account(tracker.username, password)}
			vehicles = frappe.get_all(
				"Vehicle",
				filters={"custom_aika_tracker": tracker.name, "custom_gps_tracking_enabled": 1},
				fields=["name", "custom_gps_device_id"],
			)
			if not vehicles:
				raise AikaError("No enabled Vehicles are linked to this AIKA account. Use Link AIKA Vehicles first.")
			positions = []
			for vehicle in vehicles:
				device = devices.get(str(vehicle.custom_gps_device_id or ""))
				if not device:
					continue
				location = client.get_tracking(device)
				status = client.get_device_status(device)
				latitude = float(location.get("lat") or 0)
				longitude = float(location.get("lng") or 0)
				if not (-90 <= latitude <= 90 and -180 <= longitude <= 180) or (latitude == 0 and longitude == 0):
					continue
				position_time = _parse_position_time(location.get("positionTime")) or now_datetime()
				existing = frappe.db.exists("AIKA GPS Position", {"vehicle": vehicle.name, "position_time": position_time})
				if existing:
					position_name = existing
				else:
					position = frappe.get_doc(
						{
							"doctype": "AIKA GPS Position",
							"tracker": tracker.name,
							"vehicle": vehicle.name,
							"device_id": device.device_id,
							"device_name": device.device_name,
							"latitude": latitude,
							"longitude": longitude,
							"speed_kph": float(location.get("speed") or 0),
							"course": int(location.get("course") or 0),
							"position_time": position_time,
							"received_at": now_datetime(),
							"gps_valid": int(location.get("isGPS") or 0) == 1,
							"is_stopped": int(location.get("isStop") or 0) == 1,
							"battery_percent": int(location.get("battery") or status.get("battery") or 0),
							"ignition_on": "acc on" in str(status.get("state") or "").lower(),
							"device_status": str(status.get("status") or ""),
						}
					).insert(ignore_permissions=True)
					position_name = position.name
				positions.append(position_name)
				frappe.db.set_value("Vehicle", vehicle.name, {
					"custom_gps_device_name": device.device_name,
					"custom_gps_last_position": position_time,
					"custom_gps_latitude": latitude,
					"custom_gps_longitude": longitude,
					"custom_gps_speed_kph": float(location.get("speed") or 0),
				}, update_modified=False)

		if not positions:
			raise AikaError("AIKA returned no valid positions for the linked Vehicles.")

		frappe.db.set_value(
			"AIKA GPS Tracker",
			tracker.name,
			{
				"device_id": None,
				"last_position_time": max((frappe.db.get_value("AIKA GPS Position", name, "position_time") for name in positions)),
				"last_sync_at": now_datetime(),
				"last_status": "Online",
				"last_error": None,
			},
			update_modified=False,
		)
		frappe.db.commit()
		return {"status": "success", "tracker": tracker.name, "positions": positions}
	except Exception as exc:
		frappe.db.set_value(
			"AIKA GPS Tracker",
			tracker.name,
			{"last_sync_at": now_datetime(), "last_status": "Error", "last_error": str(exc)[:500]},
			update_modified=False,
		)
		frappe.db.commit()
		frappe.logger("aika_gps").warning("AIKA GPS sync failed for %s: %s", tracker.name, exc)
		raise


def fetch_delivery_trip_vehicle(delivery_trip: str):
	"""Fast-path sync for the single Vehicle assigned to an active trip."""
	trip = frappe.get_doc("Delivery Trip", delivery_trip)
	if trip.docstatus == 2 or not trip.vehicle:
		return {"status": "skipped"}
	vehicle = frappe.db.get_value(
		"Vehicle", trip.vehicle,
		["name", "custom_gps_tracking_enabled", "custom_aika_tracker", "custom_gps_device_id"],
		as_dict=True,
	)
	if not vehicle or not vehicle.custom_gps_tracking_enabled or not vehicle.custom_aika_tracker:
		raise AikaError("The Delivery Trip Vehicle is not linked to an enabled AIKA tracker.")
	tracker = frappe.get_doc("AIKA GPS Tracker", vehicle.custom_aika_tracker)
	password = tracker.get_password("password", raise_exception=False)
	with AikaReadOnlyClient(tracker.server_url or DEFAULT_SERVER_URL) as client:
		devices = {device.device_id: device for device in client.login_account(tracker.username, password)}
		device = devices.get(str(vehicle.custom_gps_device_id or ""))
		if not device:
			raise AikaError("The Vehicle GPS ID is not available in the AIKA account.")
		location = client.get_tracking(device)
		status = client.get_device_status(device)

	latitude = float(location.get("lat") or 0)
	longitude = float(location.get("lng") or 0)
	if not (-90 <= latitude <= 90 and -180 <= longitude <= 180) or (latitude == 0 and longitude == 0):
		raise AikaError("AIKA returned invalid GPS coordinates.")
	position_time = _parse_position_time(location.get("positionTime")) or now_datetime()
	existing = frappe.db.exists("AIKA GPS Position", {"vehicle": vehicle.name, "position_time": position_time})
	if not existing:
		existing = frappe.get_doc({
			"doctype": "AIKA GPS Position", "tracker": tracker.name, "vehicle": vehicle.name,
			"device_id": device.device_id, "device_name": device.device_name,
			"latitude": latitude, "longitude": longitude,
			"speed_kph": float(location.get("speed") or 0), "course": int(location.get("course") or 0),
			"position_time": position_time, "received_at": now_datetime(),
			"gps_valid": int(location.get("isGPS") or 0) == 1,
			"is_stopped": int(location.get("isStop") or 0) == 1,
			"battery_percent": int(location.get("battery") or status.get("battery") or 0),
			"ignition_on": "acc on" in str(status.get("state") or "").lower(),
			"device_status": str(status.get("status") or ""),
		}).insert(ignore_permissions=True).name
	frappe.db.set_value("Vehicle", vehicle.name, {
		"custom_gps_device_name": device.device_name, "custom_gps_last_position": position_time,
		"custom_gps_latitude": latitude, "custom_gps_longitude": longitude,
		"custom_gps_speed_kph": float(location.get("speed") or 0),
	}, update_modified=False)
	frappe.db.commit()
	message = {
		"delivery_trip": trip.name, "vehicle": vehicle.name, "latitude": latitude,
		"longitude": longitude, "speed_kph": float(location.get("speed") or 0),
		"position_time": position_time,
	}
	frappe.publish_realtime(
		"qcmc_delivery_trip_gps", message,
		doctype="Delivery Trip", docname=trip.name,
	)
	return {"status": "success", "position": existing, **message}


def correct_existing_position_times():
	"""One-time correction for positions imported before UTC conversion was added."""
	for row in frappe.get_all("AIKA GPS Position", fields=["name", "vehicle", "position_time"]):
		corrected = row.position_time + timedelta(hours=8)
		frappe.db.set_value("AIKA GPS Position", row.name, "position_time", corrected, update_modified=False)
		if row.vehicle:
			frappe.db.set_value("Vehicle", row.vehicle, "custom_gps_last_position", corrected, update_modified=False)
	frappe.db.commit()


@frappe.whitelist()
def link_account_vehicles(tracker: str):
	frappe.only_for("System Manager")
	account = frappe.get_doc("AIKA GPS Tracker", tracker)
	password = account.get_password("password", raise_exception=False)
	with AikaReadOnlyClient(account.server_url or DEFAULT_SERVER_URL) as client:
		devices = client.login_account(account.username, password)
	vehicles = frappe.get_all("Vehicle", fields=["name", "custom_gps_id_number"])
	by_id_number = {
		str(row.custom_gps_id_number).strip(): row.name
		for row in vehicles if row.custom_gps_id_number
	}
	linked = []
	for device in devices:
		vehicle = by_id_number.get(device.id_number)
		if not vehicle:
			continue
		frappe.db.set_value("Vehicle", vehicle, {
			"custom_gps_tracking_enabled": 1,
			"custom_gps_provider": "AIKA",
			"custom_aika_tracker": account.name,
			"custom_gps_device_id": device.device_id,
			"custom_gps_id_number": device.id_number,
			"custom_gps_device_name": device.device_name,
		})
		linked.append(vehicle)
	frappe.db.commit()
	return {"linked": linked, "count": len(linked)}


def get_vehicle_link_report(tracker: str):
	"""Explain fleet linking by the authoritative GPS ID Number."""
	account = frappe.get_doc("AIKA GPS Tracker", tracker)
	password = account.get_password("password", raise_exception=False)
	with AikaReadOnlyClient(account.server_url or DEFAULT_SERVER_URL) as client:
		devices = client.login_account(account.username, password)
	vehicles = frappe.get_all("Vehicle", fields=["name", "custom_gps_id_number"])
	by_id_number = {}
	for row in vehicles:
		if row.custom_gps_id_number:
			by_id_number.setdefault(str(row.custom_gps_id_number).strip(), []).append(row.name)
	matched = []
	unmatched = []
	duplicate_matches = []
	for device in devices:
		matches = by_id_number.get(device.id_number, [])
		if len(matches) == 1:
			matched.append({"aika_name": device.device_name, "vehicle": matches[0]})
		elif len(matches) > 1:
			duplicate_matches.append({"aika_name": device.device_name, "vehicles": matches})
		else:
			unmatched.append({"aika_name": device.device_name, "id_number": device.id_number})
	return {
		"aika_device_count": len(devices),
		"erp_vehicle_count": len(vehicles),
		"matched_count": len(matched),
		"unmatched_count": len(unmatched),
		"duplicate_match_count": len(duplicate_matches),
		"unmatched": unmatched,
		"duplicate_matches": duplicate_matches,
	}


def diagnose_tracker_login(tracker_name: str):
	"""Run a credential-safe login check, including for a disabled tracker."""
	tracker = frappe.get_doc("AIKA GPS Tracker", tracker_name)
	password = tracker.get_password("password", raise_exception=False)
	if not password:
		return "AIKA password is not configured."
	try:
		with AikaReadOnlyClient(tracker.server_url or DEFAULT_SERVER_URL) as client:
			device = client.login(tracker.username, password)
			return f"Login succeeded for device {device.device_name or device.device_id}."
	except Exception as exc:
		return str(exc)[:500]


def diagnose_tracker_login_modes(tracker_name: str):
	"""Compare AIKA account/device modes without returning credentials or keys."""
	tracker = frappe.get_doc("AIKA GPS Tracker", tracker_name)
	password = tracker.get_password("password", raise_exception=False)
	if not password:
		return {"error": "AIKA password is not configured."}
	results = {}
	for login_type in (0, 1):
		try:
			with AikaReadOnlyClient(tracker.server_url or DEFAULT_SERVER_URL) as client:
				device = client.login(tracker.username, password, login_type=login_type)
				results[str(login_type)] = f"success ({device.device_name or device.device_id})"
		except Exception as exc:
			results[str(login_type)] = str(exc)[:500]
	return results


def diagnose_account_shape(tracker_name: str):
	"""Return login field names only; never values, credentials, IDs, or keys."""
	tracker = frappe.get_doc("AIKA GPS Tracker", tracker_name)
	password = tracker.get_password("password", raise_exception=False)
	with AikaReadOnlyClient(tracker.server_url or DEFAULT_SERVER_URL) as client:
		data = client._post(
			"Login",
			{"Name": tracker.username, "Pass": password, "LoginType": 0, "LoginAPP": "AKSH", "GMT": "8:00", "Key": AIKA_APP_KEY},
			include_session=False,
		)
	return {
		"fields": sorted(str(key) for key in data) if isinstance(data, dict) else [],
		"user_info_fields": sorted(str(key) for key in (data.get("userInfo") or {})) if isinstance(data, dict) and isinstance(data.get("userInfo"), dict) else [],
	}


def diagnose_account_devices_shape(tracker_name: str):
	"""Return device-list structure only, omitting all values."""
	tracker = frappe.get_doc("AIKA GPS Tracker", tracker_name)
	password = tracker.get_password("password", raise_exception=False)
	with AikaReadOnlyClient(tracker.server_url or DEFAULT_SERVER_URL) as client:
		login = client._post(
			"Login",
			{"Name": tracker.username, "Pass": password, "LoginType": 0, "LoginAPP": "AKSH", "GMT": "8:00", "Key": AIKA_APP_KEY},
			include_session=False,
		)
		user = login.get("userInfo") or {}
		data = client._post("GetUserDevices", {"UserID": user.get("userID"), "Key": user.get("key2018")}, include_session=False)
	return {
		"type": type(data).__name__,
		"fields": sorted(str(key) for key in data) if isinstance(data, dict) else [],
		"list_fields": sorted(str(key) for item in data if isinstance(item, dict) for key in item) if isinstance(data, list) else [],
		"user_list_type": type(data.get("userList")).__name__ if isinstance(data, dict) else None,
		"user_list_fields": sorted(
			str(key)
			for item in ((data.get("userList") or []) if isinstance(data, dict) else [])
			if isinstance(item, dict)
			for key in item
		),
	}


def diagnose_device_list_shape(tracker_name: str):
	"""Return GetDeviceList structure only, omitting all values."""
	tracker = frappe.get_doc("AIKA GPS Tracker", tracker_name)
	password = tracker.get_password("password", raise_exception=False)
	with AikaReadOnlyClient(tracker.server_url or DEFAULT_SERVER_URL) as client:
		login = client._post(
			"Login",
			{"Name": tracker.username, "Pass": password, "LoginType": 0, "LoginAPP": "AKSH", "GMT": "8:00", "Key": AIKA_APP_KEY},
			include_session=False,
		)
		user = login.get("userInfo") or {}
		data = client._post(
			"GetDeviceList",
			{"ID": user.get("userID"), "PageNo": 1, "PageCount": 100, "TypeID": 0, "IsAll": True, "Language": "en", "Key": user.get("key2018")},
			include_session=False,
		)
	return {
		"fields": sorted(str(key) for key in data) if isinstance(data, dict) else [],
		"nested": {
			str(name): {"type": type(value).__name__, "item_fields": sorted(str(key) for item in value if isinstance(item, dict) for key in item) if isinstance(value, list) else []}
			for name, value in data.items()
		} if isinstance(data, dict) else {},
	}


@frappe.whitelist()
def enqueue_fetch(tracker: str):
	frappe.only_for("System Manager")
	if not frappe.db.exists("AIKA GPS Tracker", tracker):
		frappe.throw(_("AIKA GPS Tracker does not exist."))
	frappe.enqueue(
		"qcmc_logic.integrations.aika_gps.fetch_tracker_position",
		queue="short",
		tracker_name=tracker,
		enqueue_after_commit=True,
		job_id=f"aika-gps-{tracker}",
		deduplicate=True,
	)
	return {"status": "queued", "tracker": tracker}


def enqueue_enabled_trackers():
	for tracker in frappe.get_all("AIKA GPS Tracker", filters={"enabled": 1}, pluck="name"):
		frappe.enqueue(
			"qcmc_logic.integrations.aika_gps.fetch_tracker_position",
			queue="short",
			tracker_name=tracker,
			enqueue_after_commit=True,
			job_id=f"aika-gps-{tracker}",
			deduplicate=True,
		)
