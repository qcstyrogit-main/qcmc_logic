"""Discussion on active company announcements, using standard Frappe Comments."""

from bs4 import BeautifulSoup
from urllib.parse import quote

import frappe
from frappe.desk.notifications import notify_mentions
from frappe.utils import get_fullname, getdate, sanitize_html

REPLY_PREFIX = 'qcmc-announcement-reply:'
CHANGE_EVENT = 'qcmc_announcement_comments_changed'


def publish_comment_change(doc, method=None):
    if doc.reference_doctype != 'Announcements' or doc.comment_type != 'Comment':
        return
    announcement = frappe.db.get_value('Announcements', doc.reference_name,
        ['published', 'publish_from', 'publish_to'], as_dict=True)
    today = getdate()
    if (not announcement or not announcement.published
            or (announcement.publish_from and getdate(announcement.publish_from) > today)
            or (announcement.publish_to and getdate(announcement.publish_to) < today)):
        return
    # The authenticated Desk room receives only an invalidation identifier.
    # Content, author identities and counts are fetched through guarded APIs.
    frappe.publish_realtime(CHANGE_EVENT, {'announcement': doc.reference_name}, after_commit=True)


@frappe.whitelist()
def get_comment_count(name):
    _active(name)
    return {'count': frappe.db.count('Comment', _filters(name))}


def stamp_comment_mentions(doc, method=None):
    if doc.reference_doctype != 'Announcements' or doc.comment_type != 'Comment' or not doc.name:
        return
    soup = BeautifulSoup(doc.content or '', 'html.parser')
    for mention in soup.select('.mention[data-id]'):
        # Override client metadata with the actual saved Comment identity.
        mention['data-qcmc-comment'] = doc.name
    doc.content = str(soup)


def validated_comment(announcement, name):
    if not name:
        return None
    row = frappe.db.get_value('Comment', name, ['reference_doctype', 'reference_name', 'comment_type'], as_dict=True)
    if row and row.reference_doctype == 'Announcements' and row.reference_name == announcement and row.comment_type == 'Comment':
        return name


def comment_in_content(announcement, content):
    for mention in BeautifulSoup(content or '', 'html.parser').select('.mention[data-qcmc-comment]'):
        name = validated_comment(announcement, mention.get('data-qcmc-comment'))
        if name:
            return name


def link_mention_notification(doc, method=None):
    """Send mention recipients to the accessible popup, rather than admin Form."""
    if doc.type == 'Mention' and doc.document_type == 'Announcements' and doc.document_name and not doc.link:
        link = '/desk?qcmc_announcement=' + quote(doc.document_name, safe='')
        comment = comment_in_content(doc.document_name, doc.email_content)
        if comment:
            link += '&qcmc_comment=' + quote(comment, safe='')
        doc.link = frappe.utils.get_url(link)


def _require_login():
    if frappe.session.user == 'Guest':
        raise frappe.PermissionError('Please log in to comment on announcements')


def _active(name):
    _require_login()
    doc = frappe.get_doc('Announcements', name)
    today = getdate()
    if (not doc.published or (doc.publish_from and getdate(doc.publish_from) > today)
            or (doc.publish_to and getdate(doc.publish_to) < today)):
        raise frappe.PermissionError('Announcement is unavailable')


def _filters(name):
    return {'reference_doctype': 'Announcements', 'reference_name': name, 'comment_type': 'Comment'}


def _can_manage(comment):
    return (comment.owner == frappe.session.user or frappe.session.user == 'Administrator'
            or 'System Manager' in frappe.get_roles())


def _comment(name, announcement=None):
    _require_login()
    doc = frappe.get_doc('Comment', name)
    if (doc.reference_doctype != 'Announcements' or doc.comment_type != 'Comment'
            or (announcement and doc.reference_name != announcement)):
        raise frappe.PermissionError('Comment is unavailable')
    return doc


def _clean_content(content):
    if not isinstance(content, str) or len(content) > 30000:
        frappe.throw('Comment must contain at most 30,000 characters')
    content = sanitize_html(content, always_sanitize=True, disallowed_tags=['form', 'input', 'button'])
    soup = BeautifulSoup(content, 'html.parser')
    # Frappe's mention notifier requires data-id. Do not let malformed pasted
    # HTML break comment insertion or manufacture a notification recipient.
    for mention in soup.select('.mention'):
        if not mention.get('data-id'):
            mention['class'] = [item for item in mention.get('class', []) if item != 'mention']
    content = str(soup)
    if not soup.get_text().strip():
        frappe.throw('Please enter a comment')
    return content


def add_counts(rows):
    if not rows:
        return
    result = frappe.db.sql('''SELECT reference_name, COUNT(name) AS comments
        FROM `tabComment` WHERE reference_doctype = 'Announcements'
        AND comment_type = 'Comment' AND reference_name IN %(names)s
        GROUP BY reference_name''', {'names': tuple(row['name'] for row in rows)}, as_dict=True)
    counts = {row.reference_name: row.comments for row in result}
    for row in rows:
        row['comments'] = counts.get(row['name'], 0)


@frappe.whitelist()
def get_comments(name):
    _active(name)
    # Ordinary employees can read active announcements through the notices API
    # even when they have no permission to open the administration DocType.
    rows = frappe.get_all('Comment', filters=_filters(name),
        fields=['name', 'owner', 'comment_by', 'content', 'creation', 'modified', 'subject'],
        order_by='creation asc, name asc', limit_page_length=0)
    names = {}
    comments = []
    for row in rows:
        if row.owner not in names:
            names[row.owner] = {'name': get_fullname(row.owner),
                'image': frappe.get_cached_value('User', row.owner, 'user_image')}
        subject = row.subject or ''
        comments.append({
            'name': row.name, 'author': row.owner,
            'author_name': row.comment_by or names[row.owner]['name'],
            'author_image': names[row.owner]['image'],
            'content': sanitize_html(row.content or '', always_sanitize=True),
            'creation': row.creation, 'modified': row.modified,
            'parent': subject[len(REPLY_PREFIX):] if subject.startswith(REPLY_PREFIX) else None,
            'can_manage': _can_manage(row),
        })
    return {'comments': comments, 'count': len(comments)}


@frappe.whitelist()
def get_mention_profile(name, user):
    # Limit the popup to active Desk users referenced in this discussion.
    # Mentions are user-authored; the fixed four-field output defines the
    # internal directory information available to authenticated employees.
    comments = get_comments(name)['comments']
    if not any(mention.get('data-id') == user and mention.get('data-is-group') != 'true'
            for row in comments
            for mention in BeautifulSoup(row['content'], 'html.parser').select('.mention')):
        raise frappe.PermissionError('Profile is unavailable')
    profile = frappe.db.get_value('User', {'name': user, 'enabled': 1, 'user_type': 'System User'}, ['full_name', 'email'], as_dict=True)
    if not profile:
        raise frappe.PermissionError('Profile is unavailable')
    employee = frappe.db.get_value('Employee', {'user_id': user, 'status': 'Active'},
        ['employee_name', 'department', 'designation'], as_dict=True) or {}
    return {'name': employee.get('employee_name') or profile.full_name or user,
        'department': employee.get('department') or '',
        'position': employee.get('designation') or '', 'email': profile.email or user}


@frappe.whitelist(methods=['POST'])
def add_comment(name, content, parent=None):
    _active(name)
    if parent:
        _comment(parent, announcement=name)
    doc = frappe.get_doc({
        'doctype': 'Comment', 'comment_type': 'Comment',
        'reference_doctype': 'Announcements', 'reference_name': name,
        'comment_email': frappe.session.user, 'content': _clean_content(content),
        # Standard Comment.subject stores the immutable reply relationship;
        # this avoids altering Frappe's core schema or losing timeline comments.
        'subject': REPLY_PREFIX + parent if parent else None,
    })
    doc.insert(ignore_permissions=True)  # Native hooks sanitize and notify @mentions.
    return {'name': doc.name, 'count': frappe.db.count('Comment', _filters(name))}


@frappe.whitelist(methods=['POST'])
def update_comment(comment, content):
    doc = _comment(comment)
    _active(doc.reference_name)
    if not _can_manage(doc):
        raise frappe.PermissionError('You can only edit your own comments')
    old = BeautifulSoup(doc.content or '', 'html.parser')
    previous = {(item.get('data-id'), item.get('data-is-group')) for item in old.select('.mention')}
    doc.content = _clean_content(content)
    doc.save(ignore_permissions=True)
    # Native Comment only notifies on insertion. Edits notify newly mentioned
    # users without sending duplicate notifications to existing mentions.
    new = BeautifulSoup(doc.content, 'html.parser')
    for item in new.select('.mention'):
        if (item.get('data-id'), item.get('data-is-group')) in previous:
            item['class'] = [value for value in item.get('class', []) if value != 'mention']
    notify_mentions('Announcements', doc.reference_name, str(new))
    return {'count': frappe.db.count('Comment', _filters(doc.reference_name))}


@frappe.whitelist(methods=['POST'])
def delete_comment(comment):
    doc = _comment(comment)
    _active(doc.reference_name)
    if not _can_manage(doc):
        raise frappe.PermissionError('You can only delete your own comments')
    # Replies remain, and the client labels their missing parent as deleted.
    frappe.delete_doc('Comment', comment, ignore_permissions=True)
    return {'count': frappe.db.count('Comment', _filters(doc.reference_name))}
