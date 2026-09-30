import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime


ROTATION_DAYS = 30
GRACE_MINUTES = 10
MAX_GRACE_RECOVERY_SIBLINGS = 5


class MobileAuthError(Exception):
	def __init__(self, error_code: str, message: str, http_status: int = 401):
		self.error_code = error_code
		self.http_status = http_status
		super().__init__(message)


@dataclass(frozen=True)
class MobileTokenResult:
	mobile_token: str
	device_session: str
	token_record: str
	user: str
	token_rotated: bool = False
	grace_expires_at: object | None = None


def hash_mobile_token(raw_token: str) -> str:
	return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()


def extract_mobile_token(explicit: str | None = None) -> str:
	request = getattr(frappe.local, "request", None)
	if request and str(getattr(request, "method", "")).upper() == "POST":
		try:
			payload = request.get_json(silent=True) or {}
		except Exception:
			payload = {}
		if isinstance(payload, dict):
			token = str(payload.get("mobile_token") or "").strip()
			if token:
				return token
		form = getattr(request, "form", None)
		if form:
			token = str(form.get("mobile_token") or "").strip()
			if token:
				return token
		return ""
	return str(explicit or "").strip()


def _rate_limit_key(kind: str, identity: str) -> str:
	digest = hashlib.sha256(str(identity or "").encode("utf-8")).hexdigest()
	return f"qcmc-mobile-auth-rate:{kind}:{digest}"


def enforce_rate_limit(kind: str, identity: str, *, limit: int, seconds: int) -> None:
	key = _rate_limit_key(kind, identity)
	count = frappe.cache.incrby(key, 1)
	if count == 1:
		frappe.cache.expire(key, seconds)
	if count > limit:
		raise MobileAuthError(
			"AUTH_RATE_LIMITED",
			"Too many authentication attempts. Please try again later.",
			429,
		)


def issue_device_token(
	user: str,
	employee: str | None = None,
	device_id: str | None = None,
	device_name: str | None = None,
) -> MobileTokenResult:
	now = now_datetime()
	raw_token = secrets.token_urlsafe(32)
	session = frappe.get_doc({
		"doctype": "Mobile Device Session",
		"token_family": secrets.token_hex(16),
		"user": user,
		"employee": employee,
		"device_id": str(device_id or "").strip(),
		"device_name": str(device_name or "").strip(),
		"created_at": now,
		"last_used_at": now,
	}).insert(ignore_permissions=True)
	token = frappe.get_doc({
		"doctype": "Mobile Device Token",
		"device_session": session.name,
		"token_hash": hash_mobile_token(raw_token),
		"issued_at": now,
		"last_used_at": now,
		"status": "Active",
	}).insert(ignore_permissions=True)
	return MobileTokenResult(
		mobile_token=raw_token,
		device_session=session.name,
		token_record=token.name,
		user=user,
	)


def _new_token_for_family(
	device_session: str,
	user: str,
	predecessor: str | None = None,
) -> MobileTokenResult:
	now = now_datetime()
	raw_token = secrets.token_urlsafe(32)
	token = frappe.get_doc({
		"doctype": "Mobile Device Token",
		"device_session": device_session,
		"token_hash": hash_mobile_token(raw_token),
		"issued_at": now,
		"last_used_at": now,
		"status": "Active",
		"predecessor": predecessor,
	}).insert(ignore_permissions=True)
	return MobileTokenResult(raw_token, device_session, token.name, user)


def _locked_token_and_family(raw_token: str):
	if not raw_token:
		raise MobileAuthError("MOBILE_TOKEN_MISSING", "Mobile token is required.")
	token_rows = frappe.db.sql(
		"""
		select name, device_session, issued_at, status, grace_expires_at, replaced_by
		from `tabMobile Device Token`
		where token_hash = %s
		for update
		""",
		(hash_mobile_token(raw_token),),
		as_dict=True,
	)
	if not token_rows:
		raise MobileAuthError("MOBILE_TOKEN_INVALID", "Mobile token is invalid.")
	token = token_rows[0]
	family_rows = frappe.db.sql(
		"""
		select name, user, revoked
		from `tabMobile Device Session`
		where name = %s
		for update
		""",
		(token.device_session,),
		as_dict=True,
	)
	if not family_rows:
		raise MobileAuthError("MOBILE_TOKEN_INVALID", "Mobile token is invalid.")
	return token, family_rows[0]


def _validate_family_user(token, family):
	if token.status == "Revoked" or family.revoked:
		raise MobileAuthError("MOBILE_TOKEN_REVOKED", "Mobile device session was revoked.")
	if token.status == "Grace" and (
		not token.grace_expires_at
		or get_datetime(token.grace_expires_at) <= now_datetime()
	):
		raise MobileAuthError("MOBILE_TOKEN_EXPIRED", "Mobile token grace period expired.")
	enabled = frappe.db.get_value("User", family.user, "enabled")
	if enabled is None or not cint(enabled):
		raise MobileAuthError("USER_DISABLED", "User is disabled.")


def validate_device_token(raw_token: str, *, allow_rotation: bool) -> MobileTokenResult:
	token, family = _locked_token_and_family(raw_token)
	_validate_family_user(token, family)
	now = now_datetime()
	frappe.db.set_value(
		"Mobile Device Session", family.name, "last_used_at", now, update_modified=False
	)
	frappe.db.set_value(
		"Mobile Device Token", token.name, "last_used_at", now, update_modified=False
	)

	rotation_enabled = bool(cint(frappe.conf.get("qcmc_mobile_token_rotation_enabled")))
	if allow_rotation and rotation_enabled and token.status == "Grace":
		enforce_rate_limit(
			"grace-recovery",
			f"{getattr(frappe.local, 'request_ip', '')}:{family.name}",
			limit=10,
			seconds=GRACE_MINUTES * 60,
		)
		recovery_count = frappe.db.count(
			"Mobile Device Token",
			{
				"device_session": family.name,
				"predecessor": token.name,
				"status": "Active",
				"name": ["!=", token.replaced_by or ""],
			},
		)
		if recovery_count >= MAX_GRACE_RECOVERY_SIBLINGS:
			raise MobileAuthError(
				"MOBILE_TOKEN_RECOVERY_LIMIT",
				"Mobile token recovery limit reached.",
			)
		result = _new_token_for_family(family.name, family.user, token.name)
		frappe.db.commit()
		return MobileTokenResult(
			result.mobile_token, result.device_session, result.token_record,
			result.user, True, token.grace_expires_at,
		)

	age = now - get_datetime(token.issued_at)
	if (
		allow_rotation
		and rotation_enabled
		and token.status == "Active"
		and age >= timedelta(days=ROTATION_DAYS)
	):
		grace_expires_at = add_to_date(now, minutes=GRACE_MINUTES)
		frappe.db.set_value(
			"Mobile Device Token",
			token.name,
			{"status": "Grace", "grace_expires_at": grace_expires_at},
			update_modified=False,
		)
		result = _new_token_for_family(family.name, family.user, token.name)
		frappe.db.set_value(
			"Mobile Device Token", token.name, "replaced_by", result.token_record,
			update_modified=False,
		)
		frappe.db.commit()
		return MobileTokenResult(
			result.mobile_token, result.device_session, result.token_record,
			result.user, True, grace_expires_at,
		)

	frappe.db.commit()
	return MobileTokenResult(raw_token, family.name, token.name, family.user)


def resolve_device_token_user(raw_token: str) -> str | None:
	try:
		token, family = _locked_token_and_family(raw_token)
		_validate_family_user(token, family)
		return family.user
	except MobileAuthError:
		return None


def revalidate_device_family(device_session: str) -> str:
	rows = frappe.db.sql(
		"""
		select name, user, revoked
		from `tabMobile Device Session`
		where name = %s
		for update
		""",
		(device_session,),
		as_dict=True,
	)
	if not rows or rows[0].revoked:
		raise MobileAuthError("MOBILE_TOKEN_REVOKED", "Mobile device session was revoked.")
	family = rows[0]
	enabled = frappe.db.get_value("User", family.user, "enabled")
	if enabled is None or not cint(enabled):
		raise MobileAuthError("USER_DISABLED", "User is disabled.")
	frappe.db.commit()
	return family.user


def revoke_device_family(
	device_session: str,
	actor: str | None = None,
	reason: str | None = None,
) -> bool:
	rows = frappe.db.sql(
		"select name, revoked from `tabMobile Device Session` where name = %s for update",
		(device_session,), as_dict=True,
	)
	if not rows:
		return False
	now = now_datetime()
	if not rows[0].revoked:
		frappe.db.set_value(
			"Mobile Device Session", device_session,
			{"revoked": 1, "revoked_at": now, "revoked_by": actor, "revocation_reason": reason},
			update_modified=False,
		)
	frappe.db.sql(
		"""
		update `tabMobile Device Token`
		set status = 'Revoked', revoked_at = coalesce(revoked_at, %s)
		where device_session = %s and status != 'Revoked'
		""",
		(now, device_session),
	)
	frappe.db.commit()
	return True


def revoke_all_user_families(
	user: str,
	actor: str | None = None,
	reason: str | None = None,
) -> int:
	names = frappe.get_all(
		"Mobile Device Session", filters={"user": user, "revoked": 0}, pluck="name"
	)
	for name in names:
		revoke_device_family(name, actor=actor, reason=reason)
	return len(names)
