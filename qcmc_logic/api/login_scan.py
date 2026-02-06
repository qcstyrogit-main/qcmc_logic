import math
import frappe
import requests
from frappe.auth import LoginManager
from frappe.utils import now_datetime
from frappe.utils import cint



GEOFENCE_EXEMPT_DESIGNATIONS = {
    "account manager",
    "regional sales manager - (gma terr)",
    "regional sales manager - provincial",
    "regional sales manager - (ind/insti/sup)",
}


def _normalize_text(value):
    return " ".join(str(value or "").strip().lower().split())


def _is_geofence_exempt(designation):
    return _normalize_text(designation) in GEOFENCE_EXEMPT_DESIGNATIONS


def _to_float(value, field_name):
    try:
        return float(value)
    except Exception:
        frappe.throw(f"Invalid {field_name}")


def _haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@frappe.whitelist()
def validate_checkin_radius(latitude=None, longitude=None, allowed_radius_meters=50):
    try:
        user = frappe.session.user
        if user == "Guest":
            frappe.throw("Not allowed", frappe.PermissionError)

        if latitude is None or longitude is None:
            return {"success": False, "allowed": False, "message": "Location is required"}

        app_lat = _to_float(latitude, "latitude")
        app_lon = _to_float(longitude, "longitude")

        emp = frappe.db.get_value(
            "Employee",
            {"user_id": user},
            ["name", "custom_location", "designation"],
            as_dict=True
        )
        if not emp:
            return {"success": False, "allowed": False, "message": "No Employee linked to this user"}

        # Bypass geofence for exempt designations
        if _is_geofence_exempt(emp.get("designation")):
            return {
                "success": True,
                "allowed": True,
                "distance_meters": 0,
                "allowed_radius_meters": 0,
                "location_name": emp.get("custom_location"),
                "message": "Geofencing bypassed for designation",
            }

        # Load all locations with coordinates
        locations = frappe.get_all(
            "Location",
            fields=["name", "location_name", "latitude", "longitude", "area", "area_uom"],
        )

        valid_locations = []
        for loc in locations:
            if loc.get("latitude") is None or loc.get("longitude") is None:
                continue

            loc_lat = _to_float(loc.get("latitude"), "Location.latitude")
            loc_lon = _to_float(loc.get("longitude"), "Location.longitude")

            # Default radius fallback: value from app/request (50m)
            radius_m = _to_float(allowed_radius_meters, "allowed_radius_meters")

            # If area is provided, derive radius from area (circle): radius = sqrt(area/pi)
            area_val = loc.get("area")
            area_uom = _normalize_text(loc.get("area_uom"))
            if area_val not in (None, ""):
                area_numeric = _to_float(area_val, "Location.area")

                if area_uom in ("meter", "m2", "sqm", "sq meter", "square meter", "square meters"):
                    area_m2 = area_numeric
                elif area_uom in ("km2", "sq km", "square kilometer", "square kilometers"):
                    area_m2 = area_numeric * 1_000_000.0
                elif area_uom in ("ft2", "sq ft", "square foot", "square feet"):
                    area_m2 = area_numeric * 0.09290304
                else:
                    area_m2 = area_numeric  # assume m² if unknown

                if area_m2 > 0:
                    radius_m = math.sqrt(area_m2 / math.pi)

            distance_m = _haversine_m(app_lat, app_lon, loc_lat, loc_lon)
            if distance_m <= radius_m:
                valid_locations.append({
                    "name": loc.get("location_name") or loc.get("name"),
                    "distance_m": round(distance_m, 2),
                    "allowed_radius_meters": round(radius_m, 2),
                })

        if valid_locations:
            closest = sorted(valid_locations, key=lambda x: x["distance_m"])[0]
            return {
                "success": True,
                "allowed": True,
                "distance_meters": closest["distance_m"],
                "allowed_radius_meters": closest["allowed_radius_meters"],
                "location_name": closest["name"],
                "message": "Inside allowed area",
            }

        return {
            "success": True,
            "allowed": False,
            "message": "Outside allowed area",
        }

    except Exception:
        frappe.log_error(frappe.get_traceback(), "login_scan.validate_checkin_radius")
        frappe.local.response["http_status_code"] = 500
        return {"success": False, "allowed": False, "message": "Unable to validate check-in radius"}



@frappe.whitelist(allow_guest=True)
def login(username, password):
    try:
        login_manager = LoginManager()
        login_manager.authenticate(user=username, pwd=password)
        login_manager.post_login()
        frappe.db.commit()

        user_id = frappe.session.user

        user_doc = frappe.db.get_value(
            "User",
            user_id,
            ["name", "email", "full_name"],
            as_dict=True
        ) or {}

        emp = frappe.db.get_value(
            "Employee",
            {"user_id": user_id},
            ["name", "employee_name", "company", "custom_location", "department", "designation"],
            as_dict=True
        ) or {}

        designation = emp.get("designation")

        return {
            "success": True,
            "message": "Login successful",
            "sid": frappe.session.sid,
            "user": {
                "name": user_id,
                "email": user_doc.get("email") or username,
                "full_name": emp.get("employee_name") or user_doc.get("full_name") or user_id,
                "company": emp.get("company"),
                "custom_location": emp.get("custom_location"),
                "department": emp.get("department"),
                "designation": designation,
                "geofence_exempt": _is_geofence_exempt(designation),
            }
        }

    except frappe.AuthenticationError:
        frappe.clear_messages()
        frappe.local.response["http_status_code"] = 401
        return {"success": False, "message": "Invalid username or password"}

    except Exception:
        frappe.log_error(frappe.get_traceback(), "login_scan.login")
        frappe.local.response["http_status_code"] = 500
        return {"success": False, "message": "Login failed"}


@frappe.whitelist()
def create_employee_checkin(
    log_type="IN",
    latitude=None,
    longitude=None,
    device_id=None,
    skip_auto_attendance=0,
    allowed_radius_meters=50
):
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("Not allowed", frappe.PermissionError)

    log_type = (log_type or "IN").upper()
    if log_type not in ("IN", "OUT"):
        frappe.throw("Invalid log_type. Use IN or OUT.")

    employee = frappe.db.get_value(
        "Employee",
        {"user_id": user},
        ["name", "custom_location", "designation"],
        as_dict=True
    )
    if not employee:
        frappe.throw("No Employee linked to this user")

    is_exempt = _is_geofence_exempt(employee.get("designation"))

    matched_location = None

    if not is_exempt:
        if latitude is None or longitude is None:
            frappe.throw("Location is required for check in/check out")

        app_lat = _to_float(latitude, "latitude")
        app_lon = _to_float(longitude, "longitude")
        radius_m = _to_float(allowed_radius_meters, "allowed_radius_meters")

        locations = frappe.get_all(
            "Location",
            fields=["name", "latitude", "longitude", "area", "area_uom"],
        )

        nearest = None

        for loc in locations:
            if loc.get("latitude") is None or loc.get("longitude") is None:
                continue

            loc_lat = _to_float(loc.get("latitude"), "Location.latitude")
            loc_lon = _to_float(loc.get("longitude"), "Location.longitude")

            # Default radius fallback: value from app/request (50m)
            radius_m = _to_float(allowed_radius_meters, "allowed_radius_meters")

            area_val = loc.get("area")
            area_uom = _normalize_text(loc.get("area_uom"))
            if area_val not in (None, ""):
                area_numeric = _to_float(area_val, "Location.area")

                if area_uom in ("meter", "m2", "sqm", "sq meter", "square meter", "square meters"):
                    area_m2 = area_numeric
                elif area_uom in ("km2", "sq km", "square kilometer", "square kilometers"):
                    area_m2 = area_numeric * 1_000_000.0
                elif area_uom in ("ft2", "sq ft", "square foot", "square feet"):
                    area_m2 = area_numeric * 0.09290304
                else:
                    area_m2 = area_numeric

                if area_m2 > 0:
                    radius_m = math.sqrt(area_m2 / math.pi)

            distance_m = _haversine_m(app_lat, app_lon, loc_lat, loc_lon)
            if distance_m <= radius_m:
                if nearest is None or distance_m < nearest["distance_m"]:
                    nearest = {
                        "name": loc.get("name"),  # docname (GUYONG, EDSA, etc.)
                        "distance_m": distance_m,
                        "radius_m": radius_m,
                    }

        if not nearest:
            frappe.throw("Outside allowed area.")

        matched_location = nearest["name"]
        distance_m = nearest["distance_m"]
        radius_m = nearest["radius_m"]
    else:
        app_lat = _to_float(latitude, "latitude") if latitude is not None else None
        app_lon = _to_float(longitude, "longitude") if longitude is not None else None
        radius_m = 0
        distance_m = 0

    doc = frappe.new_doc("Employee Checkin")
    doc.employee = employee.get("name")
    doc.log_type = log_type
    doc.time = now_datetime()
    doc.device_id = device_id
    doc.skip_auto_attendance = int(skip_auto_attendance)

    valid_columns = doc.meta.get_valid_columns()
    if "latitude" in valid_columns and app_lat is not None:
        doc.latitude = app_lat
    if "longitude" in valid_columns and app_lon is not None:
        doc.longitude = app_lon
    if "custom_location_name" in valid_columns and matched_location:
        doc.custom_location_name = matched_location

    doc.insert()
    frappe.db.commit()

    return {
        "success": True,
        "checkin": doc.name,
        "employee": employee.get("name"),
        "time": doc.time,
        "latitude": app_lat,
        "longitude": app_lon,
        "custom_location_name": matched_location,
        "distance_meters": round(distance_m, 2),
        "allowed_radius_meters": radius_m,
        "geofence_exempt": is_exempt,
    }





@frappe.whitelist()
def get_checkin_history(employee=None, limit=100):
    try:
        if frappe.session.user == "Guest":
            frappe.local.response["http_status_code"] = 401
            return {"success": False, "message": "Not authenticated"}

        if not employee:
            employee = frappe.db.get_value(
                "Employee",
                {"user_id": frappe.session.user},
                "name"
            )

        if not employee:
            return {"success": True, "checkins": []}

        try:
            limit = int(limit)
        except Exception:
            limit = 100
        limit = max(1, min(limit, 500))

        rows = frappe.get_all(
            "Employee Checkin",
            filters={"employee": employee},
            fields=["name", "employee", "log_type", "time", "creation",
                    "latitude", "longitude", "custom_location_name"],
            order_by="time desc",
            limit_page_length=limit,
        )

        checkins = []
        for row in rows:
            checkins.append({
                "name": row.get("name"),
                "employee": row.get("employee"),
                "log_type": row.get("log_type"),
                "time": row.get("time") or row.get("creation"),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "custom_location_name": row.get("custom_location_name"),
            })

        return {"success": True, "checkins": checkins}

    except Exception:
        frappe.log_error(frappe.get_traceback(), "login_scan.get_checkin_history")
        frappe.local.response["http_status_code"] = 500
        return {"success": False, "message": "Unable to load check-in history"}


    





@frappe.whitelist()
def reverse_geocode(latitude=None, longitude=None, zoom=18):
    if latitude is None or longitude is None:
        return {"success": False, "message": "Latitude and longitude are required"}

    try:
        lat = float(latitude)
        lon = float(longitude)
    except Exception:
        return {"success": False, "message": "Invalid latitude/longitude"}

    zoom = cint(zoom) or 18
    zoom = max(5, min(zoom, 20))

    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "format": "jsonv2",
        "lat": f"{lat:.6f}",
        "lon": f"{lon:.6f}",
        "zoom": zoom,
        "addressdetails": 1,
    }
    headers = {
        "Accept": "application/json",
        "User-Agent": "GeoTime-QCMC/1.0 (support@yourdomain.com)",
        "Accept-Language": "en",
    }

    try:
        res = requests.get(url, params=params, headers=headers, timeout=8)
        res.raise_for_status()
        data = res.json()
        display_name = (data.get("display_name") or "").strip()

        return {
            "success": True,
            "display_name": display_name,
            "address": data.get("address") or {},
            "lat": data.get("lat"),
            "lon": data.get("lon"),
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "login_scan.reverse_geocode")
        frappe.local.response["http_status_code"] = 500
        return {"success": False, "message": "Unable to reverse geocode"}

