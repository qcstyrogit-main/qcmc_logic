import frappe
import socket
from datetime import datetime, timedelta


def _clean_duplicate_logs(logs, threshold_seconds=30):
    if not logs:
        return []
    sorted_logs = sorted(logs, key=lambda x: (x.user_id, x.timestamp))
    cleaned = []
    last_ts = {}
    for log in sorted_logs:
        last = last_ts.get(log.user_id)
        if last and (log.timestamp - last).total_seconds() <= threshold_seconds:
            continue
        cleaned.append(log)
        last_ts[log.user_id] = log.timestamp
    return cleaned


def _check_existing_checkin(employee, log_time):
    threshold = 60
    start = log_time - timedelta(seconds=threshold)
    end = log_time + timedelta(seconds=threshold)
    return bool(frappe.db.exists(
        "Employee Checkin",
        [["employee", "=", employee], ["time", ">=", start], ["time", "<=", end]],
    ))


def _determine_log_type(checkin, att_timestamp, employee):
    """Determine IN/OUT based on shift window, falling back to alternating last log."""
    log_type = None

    if checkin.shift_start and checkin.shift_end:
        shift_start = checkin.shift_start
        shift_end = checkin.shift_end
        if shift_end < shift_start:
            shift_end += timedelta(days=1)
        if abs((att_timestamp - shift_start).total_seconds()) <= 4 * 3600:
            log_type = "IN"
        elif abs((att_timestamp - shift_end).total_seconds()) <= 4 * 3600:
            log_type = "OUT"

    if not log_type:
        last_log = frappe.db.get_value(
            "Employee Checkin", {"employee": employee}, "log_type", order_by="time desc"
        )
        log_type = "OUT" if last_log == "IN" else "IN"

    return log_type


def _process_logs(dev_name, dev_ip, dev_machine_no, dev_device_id, unique_logs, summary):
    """Insert Employee Checkin records for a list of deduplicated logs."""
    for att in unique_logs:
        attendance_device_id = f"{dev_machine_no}-{att.user_id}"
        employee = frappe.db.get_value(
            "Employee", {"attendance_device_id": attendance_device_id, "status": "Active"}, "name"
        )
        if not employee:
            frappe.log_error(f"No Employee for attendance_device_id {attendance_device_id}", "ZK Downloader")
            summary["missing_employees"] += 1
            continue

        if _check_existing_checkin(employee, att.timestamp):
            summary["skipped_duplicates"] += 1
            continue

        checkin = frappe.get_doc({
            "doctype": "Employee Checkin",
            "employee": employee,
            "time": att.timestamp,
            "device_id": dev_device_id or dev_name,
            "log_type": None,
        })
        checkin.fetch_shift()
        checkin.log_type = _determine_log_type(checkin, att.timestamp, employee)
        checkin.insert(ignore_permissions=True)
        summary["inserted_logs"] += 1

    # Commit once per device after all records are inserted
    frappe.db.commit()


@frappe.whitelist()
def fetch_and_insert_attendance_logs(start_date=None, end_date=None):
    """Fetch logs from all active ZKTeco devices and insert into Employee Checkin."""
    from zk import ZK

    devices = frappe.get_all(
        "ZKTeco Device",
        filters={"status": 1, "auto_fetch": 1},
        fields=["name", "device_ip", "port", "machine_no", "last_sync", "device_id"],
    )
    if not devices:
        return {"success": False, "message": "No active devices with Auto Fetch enabled."}

    summary = {
        "devices_processed": 0,
        "total_logs": 0,
        "inserted_logs": 0,
        "skipped_duplicates": 0,
        "missing_employees": 0,
        "errors": [],
    }

    for dev in devices:
        try:
            zk = ZK(dev.device_ip, port=int(dev.port or 4370), timeout=10, password="0")
            conn = zk.connect()
            attendances = conn.get_attendance()
            conn.disconnect()

            last_sync = dev.get("last_sync")
            if last_sync:
                last_sync = last_sync if isinstance(last_sync, datetime) else datetime.strptime(str(last_sync), "%Y-%m-%d %H:%M:%S")
            else:
                last_sync = datetime(1970, 1, 1)

            sd = datetime.strptime(start_date, "%Y-%m-%d") if isinstance(start_date, str) and start_date else last_sync
            ed = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1) - timedelta(seconds=1)) if isinstance(end_date, str) and end_date else datetime.now()

            filtered = [log for log in attendances if hasattr(log, "timestamp") and sd <= log.timestamp <= ed]
            unique_logs = _clean_duplicate_logs(filtered, threshold_seconds=30)

            summary["devices_processed"] += 1
            summary["total_logs"] += len(unique_logs)

            _process_logs(dev.name, dev.device_ip, dev.machine_no, dev.get("device_id"), unique_logs, summary)

            frappe.db.set_value("ZKTeco Device", dev.name, "last_sync", datetime.now())
            frappe.db.commit()

        except Exception as e:
            frappe.db.rollback()
            error_msg = f"Error processing device {dev.device_ip}: {str(e)}"
            summary["errors"].append(error_msg)
            frappe.log_error(error_msg, "ZK Downloader")

    summary["success"] = True
    return summary


@frappe.whitelist()
def fetch_attendance_for_device(device_name, start_date=None, end_date=None):
    """Fetch and insert attendance logs for a single ZKTeco Device."""
    from zk import ZK

    dev = frappe.get_doc("ZKTeco Device", device_name)

    summary = {
        "devices_processed": 0,
        "total_logs": 0,
        "inserted_logs": 0,
        "skipped_duplicates": 0,
        "missing_employees": 0,
        "errors": [],
    }

    try:
        zk = ZK(dev.device_ip, port=int(dev.port or 4370), timeout=10, password="0")
        conn = zk.connect()
        attendances = conn.get_attendance()
        conn.disconnect()

        last_sync = dev.last_sync
        if last_sync:
            last_sync = last_sync if isinstance(last_sync, datetime) else datetime.strptime(str(last_sync), "%Y-%m-%d %H:%M:%S")
        else:
            last_sync = datetime(1970, 1, 1)

        sd = datetime.strptime(start_date, "%Y-%m-%d") if isinstance(start_date, str) and start_date else last_sync
        ed = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1) - timedelta(seconds=1)) if isinstance(end_date, str) and end_date else datetime.now()

        filtered = [log for log in attendances if hasattr(log, "timestamp") and sd <= log.timestamp <= ed]
        unique_logs = _clean_duplicate_logs(filtered, threshold_seconds=30)

        summary["devices_processed"] = 1
        summary["total_logs"] = len(unique_logs)

        _process_logs(dev.name, dev.device_ip, dev.machine_no, getattr(dev, "device_id", None), unique_logs, summary)

        frappe.db.set_value("ZKTeco Device", device_name, "last_sync", datetime.now())
        frappe.db.commit()
        summary["success"] = True

    except Exception as e:
        frappe.db.rollback()
        error_msg = f"Error processing device {dev.device_ip}: {str(e)}"
        summary["errors"].append(error_msg)
        frappe.log_error(error_msg, "ZK Downloader")
        summary["success"] = False

    return summary


@frappe.whitelist()
def test_connection(device_name):
    """Test TCP + ZK connection for a single ZKTeco Device."""
    from zk import ZK

    dev = frappe.get_doc("ZKTeco Device", device_name)
    ip = dev.device_ip
    port = int(dev.port or 4370)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((ip, port))
        sock.close()
        if result != 0:
            return {"success": False, "message": f"Device {ip}:{port} is not reachable (TCP check failed)."}
    except Exception as e:
        return {"success": False, "message": f"TCP error: {str(e)}"}

    try:
        zk = ZK(ip, port=port, timeout=5, password="0")
        conn = zk.connect()
        firmware = conn.get_firmware_version() if hasattr(conn, "get_firmware_version") else "N/A"
        serial = conn.get_serialnumber() if hasattr(conn, "get_serialnumber") else "N/A"
        conn.disconnect()
        return {
            "success": True,
            "message": f"Connected successfully to {ip}:{port}",
            "firmware": firmware,
            "serial": serial,
        }
    except Exception as e:
        return {"success": False, "message": f"ZK connection error: {str(e)}"}
