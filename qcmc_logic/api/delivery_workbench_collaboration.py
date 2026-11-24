"""Committed workbench invalidations and per-browser Delivery Note edit leases.

As in company_messenger, realtime notifications use user rooms and after_commit.
Events contain no document data; viewers reload through permission-checked APIs.
Redis leases complement (and do not replace) SQL locks and modified timestamps.
"""

import json
import re
import secrets

import frappe
from frappe import _
from redis.exceptions import RedisError


EVENT = "qcmc_delivery_workbench_changed"
TTL = 30
ROLES = {"Sales Coordinator", "Stock Confirm User"}
REVISION_KEY = "delivery_workbench:revision"

ACQUIRE = """
local old = redis.call('GET', KEYS[1])
if old then
 local entry = cjson.decode(old)
 if entry.user == ARGV[2] and entry.client == ARGV[3] then
  redis.call('EXPIRE', KEYS[1], ARGV[4])
 end
 return old
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[4])
return ARGV[1]
"""
TOUCH = """
local old = redis.call('GET', KEYS[1])
if not old then return 0 end
local entry = cjson.decode(old)
if entry.token ~= ARGV[1] or entry.user ~= ARGV[2] then return 0 end
if ARGV[3] == 'release' then redis.call('DEL', KEYS[1])
else redis.call('EXPIRE', KEYS[1], ARGV[4]) end
return 1
"""


def _role_check():
	if frappe.session.user == "Guest" or (frappe.session.user != "Administrator" and not ROLES.intersection(frappe.get_roles())):
		frappe.throw(_("You cannot access Delivery Schedule Workbench collaboration."), frappe.PermissionError)


def _authorize(name, edit=False):
	_role_check()
	doc = frappe.get_doc("Delivery Note", name)
	doc.check_permission("read")
	if edit:
		if doc.docstatus == 0 and doc.workflow_state == "Draft" and doc.items and all(
			row.get("custom_so_delivery_schedule") for row in doc.items
		):
			from qcmc_logic.api.delivery_schedule_revision import _validate_v2_sales_edit_draft
			_validate_v2_sales_edit_draft(doc)
		else:
			from qcmc_logic.api import delivery_confirmation_service as confirmation
			confirmation._validate_sales_review_delivery_note(doc, require_transact=True)
	return doc


def _client(value):
	if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", value):
		frappe.throw(_("Reload the workbench to start an editing session."))
	return value


def _key(name):
	return frappe.cache.make_key(f"delivery_workbench:lease:{name}")


def _entry(name):
	try:
		raw = frappe.cache.get(_key(name))
		return json.loads(raw) if raw else None
	except (RedisError, ValueError, TypeError):
		frappe.throw(_("Cannot verify the editing lock. Retry before saving."))


def _status(entry, client_id):
	if not entry:
		return None
	return {"user": entry["user"], "owner_name": entry["owner_name"],
		"mine": entry["user"] == frappe.session.user and entry["client"] == client_id}


def revision():
	try:
		return int(frappe.cache.get(frappe.cache.make_key(REVISION_KEY)) or 0)
	except RedisError:
		frappe.throw(_("Workbench live updates are unavailable. Retry shortly."))


@frappe.whitelist(methods=["POST"])
def acquire_edit(delivery_note, client_id, document_modified):
	client_id = _client(client_id)
	_authorize(delivery_note, edit=True)
	from qcmc_logic.api import delivery_confirmation_service as confirmation
	doc = confirmation._get_locked_delivery_note(delivery_note)
	doc.check_permission("read")
	if not (doc.docstatus == 0 and doc.workflow_state == "Draft" and doc.items and all(
		row.get("custom_so_delivery_schedule") for row in doc.items
	)):
		confirmation._validate_sales_review_delivery_note(doc, require_transact=True)
	if str(doc.modified) != str(document_modified):
		frappe.throw(_("This Delivery Note changed. Refresh before editing."), frappe.TimestampMismatchError)
	entry = {"user": frappe.session.user, "client": client_id,
		"owner_name": frappe.get_cached_value("User", frappe.session.user, "full_name") or frappe.session.user,
		"token": secrets.token_urlsafe(32)}
	try:
		entry = json.loads(frappe.cache.eval(ACQUIRE, 1, _key(delivery_note), json.dumps(entry), frappe.session.user, client_id, TTL))
	except (RedisError, ValueError, TypeError):
		frappe.throw(_("Cannot acquire an editing lock. Retry shortly."))
	status = _status(entry, client_id)
	if not status["mine"]:
		return {"acquired": False, "lock": status}
	_publish("locks", after_commit=False)
	return {"acquired": True, "token": entry["token"], "lock": status, "ttl": TTL}


@frappe.whitelist(methods=["POST"])
def release_edit(delivery_note, token):
	_authorize(delivery_note)
	if not isinstance(token, str):
		frappe.throw(_("Invalid editing lock."))
	try:
		released = bool(frappe.cache.eval(TOUCH, 1, _key(delivery_note), token or "", frappe.session.user, "release", TTL))
	except RedisError:
		frappe.throw(_("Cannot release the editing lock. It will expire automatically."))
	if released:
		_publish("locks", after_commit=False)
	return {"released": released}


@frappe.whitelist(methods=["POST"])
def get_state(delivery_notes=None, client_id=None, leases=None):
	_role_check()
	client_id = _client(client_id)
	names = frappe.parse_json(delivery_notes or "[]")
	leases = frappe.parse_json(leases or "{}")
	if (not isinstance(names, list) or len(names) > 500
		or any(not isinstance(name, str) or not name for name in names)
		or not isinstance(leases, dict) or any(not isinstance(token, str) for token in leases.values())):
		frappe.throw(_("Select a smaller delivery schedule filter."))
	locks, renewed = {}, []
	for name in dict.fromkeys(names):
		_authorize(name)
		entry = _entry(name)
		if entry and name in leases and entry["client"] == client_id:
			if _touch(name, leases[name]):
				renewed.append(name)
		locks[name] = _status(_entry(name), client_id)
	return {"locks": locks, "renewed": renewed, "revision": revision()}


def _touch(name, token):
	try:
		return bool(frappe.cache.eval(TOUCH, 1, _key(name), token or "", frappe.session.user, "renew", TTL))
	except RedisError:
		frappe.throw(_("Cannot renew the editing lock. Retry before saving."))


def bind_edit(doc, token):
	"""Require a browser lease for workbench writes, including delegated methods."""
	entry = _entry(doc.name)
	if not isinstance(token, str) or not entry or entry["user"] != frappe.session.user or not secrets.compare_digest(entry["token"], token):
		frappe.throw(_("The editing lock expired or belongs to another session. Refresh and acquire it again."))
	if not _touch(doc.name, token):
		frappe.throw(_("The editing lock expired. Refresh before saving."))
	if not frappe.flags.get("delivery_workbench_tokens"):
		frappe.flags.delivery_workbench_tokens = {}
	frappe.flags.delivery_workbench_tokens[doc.name] = token
	doc.flags.delivery_workbench_edit_token = token


def guard_edit(doc, method=None):
	"""Protect leased DNs from conflicting saves in forms and legacy APIs too."""
	entry = _entry(doc.name)
	token = doc.flags.get("delivery_workbench_edit_token") or frappe.flags.get("delivery_workbench_tokens", {}).get(doc.name)
	if token and not entry:
		frappe.throw(_("The editing lock expired. Refresh before saving."))
	if entry and (entry["user"] != frappe.session.user or not token or not secrets.compare_digest(entry["token"], token)):
		frappe.throw(_("This Delivery Note is being edited by {0}. Wait until editing is finished.").format(entry["owner_name"]))


def _publish(kind, after_commit=True):
	users = set(frappe.get_all("Has Role", filters={"parenttype": "User", "role": ["in", sorted(ROLES)]}, pluck="parent"))
	users.add("Administrator")
	for user in users:
		# Deliberately no DN/customer/quantity/lock-owner data in the event.
		frappe.publish_realtime(EVENT, {"kind": kind}, user=user, after_commit=after_commit)


def notify_change(doc, method=None):
	if doc.doctype == "Delivery Note" and method not in ("after_delete",):
		guard_edit(doc, method)
	if frappe.flags.get("delivery_workbench_change_queued"):
		return
	frappe.flags.delivery_workbench_change_queued = True
	frappe.db.after_rollback.add(_clear_queued_change)
	frappe.db.after_commit.add(_increment_revision)
	_publish("saved", after_commit=True)


def _clear_queued_change():
	frappe.flags.delivery_workbench_change_queued = False


def _increment_revision():
	try:
		frappe.cache.incr(frappe.cache.make_key(REVISION_KEY))
	except RedisError:
		frappe.logger().warning("Delivery workbench revision update failed; realtime refresh remains available")
