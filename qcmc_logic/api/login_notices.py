"""Monthly company notices for authenticated ERP Desk users."""

from hashlib import sha256
from mimetypes import guess_type
from urllib.parse import quote

import frappe
from frappe.utils import getdate
from werkzeug.wrappers import Response

from qcmc_logic.api.public_announcements import list_active_announcements
from qcmc_logic.api.announcement_comments import add_counts as add_announcement_comment_counts


def _add_announcement_view_counts(rows):
    if not rows:
        return
    counts = frappe.db.sql(
        'SELECT announcement, COUNT(name) AS views FROM `tabAnnouncement View` '
        'WHERE announcement IN %(names)s GROUP BY announcement',
        {'names': tuple(row['name'] for row in rows)}, as_dict=True)
    counts = {row.announcement: row.views for row in counts}
    for row in rows:
        row['views'] = counts.get(row['name'], 0)


@frappe.whitelist(methods=['POST'])
def record_announcement_view(name):
    if frappe.session.user == 'Guest':
        raise frappe.PermissionError('Please log in to view company notices')
    doc = frappe.get_doc('Announcements', name)
    today = getdate()
    if (not doc.published
            or (doc.publish_from and getdate(doc.publish_from) > today)
            or (doc.publish_to and getdate(doc.publish_to) < today)):
        raise frappe.PermissionError('Announcement is unavailable')
    # Derive identity from the login session, never from a browser parameter.
    identity = {'announcement': name, 'viewer': frappe.session.user}
    # Link values follow announcement/user renames; historical hash names do not.
    if not frappe.db.exists('Announcement View', identity):
        frappe.get_doc({
            'doctype': 'Announcement View', **identity,
        }).insert(ignore_permissions=True, ignore_if_duplicate=True)
    return {'views': frappe.db.count('Announcement View', {'announcement': name})}


def _notice_image_url(image, name):
    # Local files must use the current browser origin and its login cookie.
    prefix = frappe.utils.get_url().rstrip('/') + '/'
    path = '/' + image[len(prefix):] if image and image.startswith(prefix) else image
    if path and path.startswith('/private/files/'):
        return '/api/method/qcmc_logic.api.login_notices.get_announcement_image?name=' + quote(name, safe='')
    return path


@frappe.whitelist()
def get_announcement_image(name):
    if frappe.session.user == 'Guest':
        raise frappe.PermissionError('Please log in to view company notices')
    doc = frappe.get_doc('Announcements', name)
    today = getdate()
    if (not doc.published
            or (doc.publish_from and getdate(doc.publish_from) > today)
            or (doc.publish_to and getdate(doc.publish_to) < today)
            or not (doc.image or '').startswith('/private/files/')):
        raise frappe.PermissionError('Announcement image is unavailable')
    # Grant only the image explicitly attached to this active announcement.
    # Ordinary Desk users intentionally do not have Announcements read roles.
    file_name = frappe.db.get_value('File', {
        'file_url': doc.image,
        'attached_to_doctype': 'Announcements',
        'attached_to_name': name,
    }, 'name')
    if not file_name:
        raise frappe.PermissionError('Announcement image is unavailable')
    file = frappe.get_doc('File', file_name)
    content_type = guess_type(file.file_name)[0] or ''
    if not content_type.startswith('image/') or content_type == 'image/svg+xml':
        raise frappe.PermissionError('Unsupported announcement image type')
    return Response(file.get_content(encodings=[]), mimetype=content_type, headers={
        'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff',
    })


def extend_bootinfo(bootinfo):
    # extend_bootinfo runs even when Frappe reuses cached, per-user boot data.
    # Expose a one-way marker, never the authentication cookie itself.
    bootinfo["qcmc_login_notice_session"] = sha256(
        f"qcmc-login-notices:{frappe.session.sid}".encode()
    ).hexdigest()
    bootinfo['qcmc_realtime_same_origin'] = bool(frappe.conf.get('qcmc_realtime_same_origin'))
    bootinfo['qcmc_realtime_proxy_origin'] = frappe.conf.get('host_name') or ''


@frappe.whitelist()
def get_login_notices():
    if frappe.session.user == "Guest":
        raise frappe.PermissionError("Please log in to view company notices")

    current = getdate()
    messenger_roles = {"System Manager", "Company Messenger User", "Company Messenger Admin", "Tweet Support Agent"}
    can_greet = "company_messenger" in frappe.get_installed_apps() and (
        frappe.session.user == "Administrator" or bool(messenger_roles.intersection(frappe.get_roles()))
    )
    # Use Employee identity and its linked ERP user; names need not be unique.
    people = frappe.db.sql(
        """
        SELECT e.name, e.employee_name, e.department, e.date_of_birth,
               e.date_of_joining, u.name AS user_id
        FROM `tabEmployee` e
        LEFT JOIN `tabUser` u ON u.name = e.user_id
            AND u.enabled = 1 AND u.user_type = 'System User'
            AND (u.name = 'Administrator' OR EXISTS (
                SELECT 1 FROM `tabHas Role` r WHERE r.parent = u.name
                AND r.parenttype = 'User'
                AND r.role IN ('System Manager', 'Company Messenger User',
                               'Company Messenger Admin', 'Tweet Support Agent')
            ))
        WHERE e.status = 'Active'
          AND (MONTH(e.date_of_birth) = %(month)s OR MONTH(e.date_of_joining) = %(month)s)
        """,
        {"month": current.month},
        as_dict=True,
    )
    announcements = list_active_announcements(limit=100)
    if announcements["total"] > 100:
        announcements = list_active_announcements(limit=announcements["total"])
    for row in announcements['items']:
        row['image'] = _notice_image_url(row.get('image'), row['name'])
    _add_announcement_view_counts(announcements['items'])
    add_announcement_comment_counts(announcements['items'])

    def celebration(row, date_field):
        return {
            "employee_id": row["name"],
            "employee_name": row["employee_name"],
            "department": row.get("department") or "",
            "day": getdate(row[date_field]).day,
            "is_today": getdate(row[date_field]).day == current.day,
            "user_id": row.get("user_id") if can_greet else None,
        }

    birthdays, anniversaries = [], []
    for row in people:
        birth = getdate(row["date_of_birth"]) if row.get("date_of_birth") else None
        joining = getdate(row["date_of_joining"]) if row.get("date_of_joining") else None
        if birth and birth.month == current.month:
            birthdays.append(celebration(row, "date_of_birth"))
        if joining and joining.month == current.month and current.year > joining.year:
            anniversaries.append({**celebration(row, "date_of_joining"), "years": current.year - joining.year})
    for rows in (birthdays, anniversaries):
        rows.sort(key=lambda row: (not row["is_today"], row["day"], row["employee_name"]))

    return {
        "month": current.month,
        "year": current.year,
        "announcements": announcements["items"],
        "birthdays": birthdays,
        "anniversaries": anniversaries,
        "can_greet": can_greet,
    }
