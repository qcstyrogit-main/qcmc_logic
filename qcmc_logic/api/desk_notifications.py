"""Announcement destinations and the current user's unread Desk count."""
from email import policy
from email.parser import Parser
from urllib.parse import parse_qs, quote, unquote, urlsplit

from bs4 import BeautifulSoup
import frappe
from qcmc_logic.api.announcement_comments import _active, _require_login, comment_in_content, validated_comment


def _target_from_url(url):
    parsed = urlsplit(url or '')
    target = parse_qs(parsed.query).get('qcmc_announcement', [None])[0]
    if target:
        return target
    parts = [unquote(part) for part in parsed.path.split('/') if part]
    if len(parts) == 3 and parts[0] in ('desk', 'app') and parts[1].lower() == 'announcements':
        return parts[2]
    if len(parts) == 4 and parts[:2] == ['desk', 'Form'] and parts[2] == 'Announcements':
        return parts[3]


def announcement_target(row):
    if row.get('document_type') == 'Announcements':
        return row.get('document_name')
    if row.get('document_type') != 'Email Queue' or not row.get('document_name'):
        return None
    queue = frappe.db.get_value('Email Queue', row.get('document_name'),
        ['reference_doctype', 'reference_name', 'message'], as_dict=True)
    if not queue:
        return None
    if queue.get('reference_doctype') == 'Announcements':
        return queue.get('reference_name')
    try:
        message = Parser(policy=policy.default).parsestr(queue.get('message') or '')
        body = message.get_body(preferencelist=('html',))
        if body:
            # Frappe puts the trusted Open Document CTA after the description.
            # Never interpret user-authored links in that description as targets.
            links = [link for link in BeautifulSoup(body.get_content(), 'html.parser').select('div.more-info > a[href]')
                if not link.find_parent('blockquote')]
            if links:
                url = links[-1]['href']
                host = urlsplit(url).hostname
                allowed = {urlsplit(frappe.utils.get_url()).hostname, frappe.local.site}
                if not host or host in allowed:
                    return _target_from_url(url)
    except (ValueError, LookupError, TypeError):
        return None


@frappe.whitelist()
def get_notification_logs(limit=20):
    _require_login()
    # Administrator's native permission query includes everyone's logs. The
    # bell is personal for every account, including Administrator.
    logs = frappe.get_all('Notification Log', filters={'for_user': frappe.session.user},
        fields=['*'], order_by='creation desc', limit_page_length=max(1, min(100, frappe.utils.cint(limit))))
    if frappe.request:
        # The native HTTP cache can otherwise serve stale lists after realtime
        # events, and retain destinations generated before this override.
        frappe.local.response_headers.set('Cache-Control', 'no-store')
    rows = []
    user_info = frappe._dict()
    for original in logs:
        row = dict(original)
        if row.get('from_user') and row['from_user'] not in user_info:
            frappe.utils.add_user_info(row['from_user'], user_info)
        target = announcement_target(row)
        if target:
            row['link'] = '/desk?qcmc_announcement=' + quote(target, safe='')
            # Preserve new deep links cheaply. Resolve legacy content only on
            # click, not on every realtime/recovery refresh of the list.
            comment = parse_qs(urlsplit(original.get('link') or '').query).get('qcmc_comment', [None])[0]
            if comment:
                row['link'] += '&qcmc_comment=' + quote(comment, safe='')
        rows.append(row)
    return {'notification_logs': rows, 'user_info': user_info}


def notification_comment(row, announcement):
    link = row.get('link') or ''
    content = row.get('email_content') or ''
    if row.get('document_type') == 'Email Queue':
        message = frappe.db.get_value('Email Queue', row.get('document_name'), 'message')
        try:
            body = Parser(policy=policy.default).parsestr(message or '').get_body(preferencelist=('html',))
            soup = BeautifulSoup(body.get_content() if body else '', 'html.parser')
            links = [node for node in soup.select('div.more-info > a[href]') if not node.find_parent('blockquote')]
            if links:
                link = links[-1]['href']
            block = soup.find('blockquote')
            content = str(block) if block else ''
        except (ValueError, LookupError, TypeError):
            return None
    name = parse_qs(urlsplit(link).query).get('qcmc_comment', [None])[0]
    name = validated_comment(announcement, name) or comment_in_content(announcement, content)
    if name or not content:
        return name
    # Legacy notifications have no ID. Only use an unambiguous content match;
    # never jump to an arbitrary recent comment or another announcement.
    expected = ' '.join(BeautifulSoup(content, 'html.parser').get_text(' ', strip=True).split())
    filters = {'reference_doctype': 'Announcements', 'reference_name': announcement, 'comment_type': 'Comment'}
    if row.get('from_user'):
        filters['owner'] = row.get('from_user')
    if row.get('creation'):
        filters['creation'] = ['<=', row.get('creation')]
    matches = [comment.name for comment in frappe.get_all('Comment', filters=filters, fields=['name', 'content'], order_by='creation desc', limit_page_length=100)
        if ' '.join(BeautifulSoup(comment.content or '', 'html.parser').get_text(' ', strip=True).split()) == expected]
    return matches[0] if len(matches) == 1 else None


def _own_notification(name):
    _require_login()
    row = frappe.get_doc('Notification Log', name)
    if row.for_user != frappe.session.user:
        raise frappe.PermissionError('Notification is unavailable')
    return row


def _publish_read():
    frappe.publish_realtime('qcmc_notifications_read', user=frappe.session.user, after_commit=True)


@frappe.whitelist(methods=['POST'])
def mark_as_read(docname):
    row = _own_notification(docname)
    if frappe.flags.read_only:
        return
    frappe.db.set_value('Notification Log', row.name, 'read', 1, update_modified=False)
    _publish_read()


@frappe.whitelist(methods=['POST'])
def mark_all_as_read():
    _require_login()
    if frappe.flags.read_only:
        return
    frappe.db.set_value('Notification Log', {'for_user': frappe.session.user, 'read': 0}, 'read', 1, update_modified=False)
    _publish_read()


@frappe.whitelist()
def get_unread_count():
    _require_login()
    return frappe.db.count('Notification Log', {'for_user': frappe.session.user, 'read': 0})


@frappe.whitelist(methods=['POST'])
def open_announcement_notification(notification):
    row = _own_notification(notification)
    target = announcement_target(row)
    if target:
        _active(target)
    comment = notification_comment(row, target) if target else None
    # Legacy queue links are intercepted too. Preserve the native read-on-click
    # behavior even when the caller falls back to an unrelated queue page.
    if not frappe.flags.read_only:
        frappe.db.set_value('Notification Log', notification, 'read', 1, update_modified=False)
        _publish_read()
    return {'announcement': target, **({'comment': comment} if comment else {})}
