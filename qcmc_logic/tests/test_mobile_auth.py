import unittest
import hashlib
from datetime import timedelta
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase


def run_mobile_auth_tests():
	suite = unittest.defaultTestLoader.loadTestsFromModule(
		__import__(__name__, fromlist=["*"])
	)
	result = unittest.TextTestRunner(verbosity=1).run(suite)
	if not result.wasSuccessful():
		raise AssertionError(
			f"Mobile authentication tests failed: {len(result.failures)} failures, "
			f"{len(result.errors)} errors"
		)
	return {"tests_run": result.testsRun, "successful": True}


class TestMobileAuthSchema(FrappeTestCase):
	def test_token_hash_is_required_unique_and_not_listable(self):
		meta = frappe.get_meta("Mobile Device Token")
		field = meta.get_field("token_hash")

		self.assertEqual(field.reqd, 1)
		self.assertEqual(field.unique, 1)
		self.assertEqual(meta.permissions, [])

	def test_only_system_manager_can_read_device_sessions(self):
		permissions = frappe.get_meta("Mobile Device Session").permissions

		self.assertEqual(len(permissions), 1)
		self.assertEqual(permissions[0].role, "System Manager")
		self.assertEqual(permissions[0].read, 1)

	def test_mobile_auth_lookup_indexes_exist(self):
		def index_columns(table):
			rows = frappe.db.sql(f"show index from `{table}`", as_dict=True)
			indexes = {}
			for row in rows:
				indexes.setdefault(row.Key_name, []).append(
					(row.Seq_in_index, row.Column_name)
				)
			return {
				name: tuple(column for _, column in sorted(columns))
				for name, columns in indexes.items()
			}

		session_indexes = index_columns("tabMobile Device Session")
		token_indexes = index_columns("tabMobile Device Token")

		self.assertIn(("user", "revoked"), session_indexes.values())
		self.assertIn(("device_session", "status"), token_indexes.values())


class TestMobileTokenLifecycle(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._existing_device_sessions = set(
			frappe.get_all("Mobile Device Session", pluck="name")
		)
		self._created_users = []

	def tearDown(self):
		created_sessions = set(
			frappe.get_all("Mobile Device Session", pluck="name")
		) - self._existing_device_sessions
		if created_sessions:
			frappe.db.delete(
				"Mobile Device Token", {"device_session": ["in", list(created_sessions)]}
			)
			frappe.db.delete(
				"Mobile Device Session", {"name": ["in", list(created_sessions)]}
			)
		for user in self._created_users:
			frappe.db.delete("User", {"name": user})
		frappe.db.commit()
		super().tearDown()

	def test_rate_limit_uses_digest_and_rejects_excess_attempt(self):
		from qcmc_logic.api.mobile_auth import (
			MobileAuthError,
			_rate_limit_key,
			enforce_rate_limit,
		)

		identity = f"sensitive-{frappe.generate_hash(length=12)}"
		key = _rate_limit_key("invalid-resume", identity)
		self.assertNotIn(identity, key)
		frappe.cache.delete(key)
		try:
			enforce_rate_limit("invalid-resume", identity, limit=2, seconds=60)
			enforce_rate_limit("invalid-resume", identity, limit=2, seconds=60)
			with self.assertRaises(MobileAuthError) as error:
				enforce_rate_limit("invalid-resume", identity, limit=2, seconds=60)
			self.assertEqual(error.exception.error_code, "AUTH_RATE_LIMITED")
			self.assertEqual(error.exception.http_status, 429)
		finally:
			frappe.cache.delete(key)

	def test_issue_device_token_persists_only_hash_and_device_metadata(self):
		from qcmc_logic.api.mobile_auth import issue_device_token

		result = issue_device_token(
			"Administrator",
			device_id="SCANNER-2",
			device_name="Warehouse Scanner 2",
		)

		self.assertGreaterEqual(len(result.mobile_token), 43)
		session = frappe.db.get_value(
			"Mobile Device Session",
			result.device_session,
			["user", "device_id", "device_name"],
			as_dict=True,
		)
		self.assertEqual(session.user, "Administrator")
		self.assertEqual(session.device_id, "SCANNER-2")
		self.assertEqual(session.device_name, "Warehouse Scanner 2")
		token_hash = frappe.db.get_value(
			"Mobile Device Token", result.token_record, "token_hash"
		)
		self.assertEqual(
			token_hash,
			hashlib.sha256(result.mobile_token.encode()).hexdigest(),
		)
		for doctype, name in (
			("Mobile Device Session", result.device_session),
			("Mobile Device Token", result.token_record),
		):
			values = frappe.db.get_value(
				doctype,
				name,
				frappe.db.get_table_columns(doctype),
				as_dict=True,
			)
			self.assertNotIn(result.mobile_token, {str(value) for value in values.values()})

	def test_rotation_is_disabled_by_default(self):
		from qcmc_logic.api.mobile_auth import issue_device_token, validate_device_token

		issued = issue_device_token("Administrator")
		frappe.db.set_value(
			"Mobile Device Token",
			issued.token_record,
			"issued_at",
			frappe.utils.now_datetime() - timedelta(days=31),
			update_modified=False,
		)

		validated = validate_device_token(issued.mobile_token, allow_rotation=True)

		self.assertEqual(validated.mobile_token, issued.mobile_token)
		self.assertFalse(validated.token_rotated)

	def test_old_token_rotates_with_fixed_grace_and_bounded_recovery(self):
		from qcmc_logic.api.mobile_auth import (
			MobileAuthError,
			issue_device_token,
			validate_device_token,
		)

		issued = issue_device_token("Administrator")
		frappe.db.set_value(
			"Mobile Device Token",
			issued.token_record,
			"issued_at",
			frappe.utils.now_datetime() - timedelta(days=30, seconds=1),
			update_modified=False,
		)
		original_setting = frappe.conf.get("qcmc_mobile_token_rotation_enabled")
		frappe.conf.qcmc_mobile_token_rotation_enabled = 1
		try:
			rotated = validate_device_token(issued.mobile_token, allow_rotation=True)
			self.assertNotEqual(rotated.mobile_token, issued.mobile_token)
			self.assertTrue(rotated.token_rotated)
			fixed_expiry = frappe.db.get_value(
				"Mobile Device Token", issued.token_record, "grace_expires_at"
			)
			delta = frappe.utils.get_datetime(fixed_expiry) - frappe.utils.now_datetime()
			self.assertGreater(delta.total_seconds(), 590)
			self.assertLessEqual(delta.total_seconds(), 600)

			recoveries = [
				validate_device_token(issued.mobile_token, allow_rotation=True)
				for _ in range(5)
			]
			self.assertEqual(len({row.mobile_token for row in recoveries}), 5)
			self.assertEqual(
				frappe.db.get_value(
					"Mobile Device Token", issued.token_record, "grace_expires_at"
				),
				fixed_expiry,
			)
			with self.assertRaises(MobileAuthError) as error:
				validate_device_token(issued.mobile_token, allow_rotation=True)
			self.assertEqual(error.exception.error_code, "MOBILE_TOKEN_RECOVERY_LIMIT")
		finally:
			frappe.conf.qcmc_mobile_token_rotation_enabled = original_setting

	def test_family_revocation_does_not_revoke_another_device(self):
		from qcmc_logic.api.mobile_auth import (
			MobileAuthError,
			issue_device_token,
			revoke_device_family,
			validate_device_token,
		)

		first = issue_device_token("Administrator", device_id="S1")
		second = issue_device_token("Administrator", device_id="S2")
		revoke_device_family(first.device_session, actor="Administrator")

		with self.assertRaises(MobileAuthError) as error:
			validate_device_token(first.mobile_token, allow_rotation=False)
		self.assertEqual(error.exception.error_code, "MOBILE_TOKEN_REVOKED")
		self.assertEqual(
			validate_device_token(second.mobile_token, allow_rotation=False).user,
			"Administrator",
		)

	def test_disabled_user_is_distinct_from_invalid_token(self):
		from qcmc_logic.api.mobile_auth import (
			MobileAuthError,
			issue_device_token,
			validate_device_token,
		)

		user = f"mobile-auth-disabled-{frappe.generate_hash(length=8)}@example.com"
		self._created_users.append(user)
		frappe.get_doc({
			"doctype": "User",
			"email": user,
			"first_name": "Mobile Auth Disabled",
			"enabled": 1,
			"send_welcome_email": 0,
		}).insert(ignore_permissions=True)
		issued = issue_device_token(user)
		frappe.db.set_value("User", user, "enabled", 0, update_modified=False)

		with self.assertRaises(MobileAuthError) as disabled:
			validate_device_token(issued.mobile_token, allow_rotation=False)
		self.assertEqual(disabled.exception.error_code, "USER_DISABLED")
		with self.assertRaises(MobileAuthError) as invalid:
			validate_device_token("not-a-token", allow_rotation=False)
		self.assertEqual(invalid.exception.error_code, "MOBILE_TOKEN_INVALID")


class TestMobileAuthAPI(TestMobileTokenLifecycle):
	def test_logout_is_idempotent_and_revokes_only_current_device_family(self):
		from qcmc_logic.api.login_scan import logout
		from qcmc_logic.api.mobile_auth import issue_device_token, validate_device_token

		first = issue_device_token("Administrator", device_id="S1")
		second = issue_device_token("Administrator", device_id="S2")
		original_sid = frappe.session.sid
		try:
			frappe.session.sid = "logout-sid"
			with patch("qcmc_logic.api.login_scan.delete_session") as delete_session:
				response = logout(first.mobile_token)
				repeated = logout(first.mobile_token)
		finally:
			frappe.session.sid = original_sid

		self.assertTrue(response["success"])
		self.assertTrue(repeated["success"])
		delete_session.assert_any_call("logout-sid")
		self.assertEqual(
			frappe.db.get_value("Mobile Device Session", first.device_session, "revoked"), 1
		)
		self.assertEqual(
			validate_device_token(second.mobile_token, allow_rotation=False).user,
			"Administrator",
		)

	def test_admin_can_revoke_all_devices_for_one_user(self):
		from qcmc_logic.api.login_scan import revoke_all_mobile_sessions
		from qcmc_logic.api.mobile_auth import issue_device_token

		user = f"mobile-auth-admin-{frappe.generate_hash(length=8)}@example.com"
		self._created_users.append(user)
		frappe.get_doc({
			"doctype": "User", "email": user, "first_name": "Mobile Auth Admin Test",
			"enabled": 1, "send_welcome_email": 0,
		}).insert(ignore_permissions=True)
		first = issue_device_token(user, device_id="S1")
		second = issue_device_token(user, device_id="S2")
		original_user = frappe.session.user
		try:
			frappe.session.user = "Administrator"
			response = revoke_all_mobile_sessions(user, reason="Security test")
		finally:
			frappe.session.user = original_user

		self.assertTrue(response["success"])
		self.assertEqual(response["revoked_device_sessions"], 2)
		self.assertEqual(
			frappe.db.get_value("Mobile Device Session", first.device_session, "revoked"), 1
		)
		self.assertEqual(
			frappe.db.get_value("Mobile Device Session", second.device_session, "revoked"), 1
		)

	def test_device_revocation_admin_api_requires_system_manager(self):
		from qcmc_logic.api.login_scan import revoke_device_session
		from qcmc_logic.api.mobile_auth import issue_device_token

		issued = issue_device_token("Administrator")
		original_user = frappe.session.user
		try:
			frappe.session.user = "Guest"
			with self.assertRaises(frappe.PermissionError):
				revoke_device_session(issued.device_session)
		finally:
			frappe.session.user = original_user

	def test_production_credential_endpoint_rejects_insecure_transport(self):
		from qcmc_logic.api.login_scan import _require_secure_transport
		from qcmc_logic.api.mobile_auth import MobileAuthError

		original_request = getattr(frappe.local, "request", None)
		original_developer_mode = frappe.conf.get("developer_mode")
		request = Mock()
		request.is_secure = False
		request.host = "erp.example.com"
		request.headers = {"X-Forwarded-Proto": "http"}
		frappe.local.request = request
		frappe.conf.developer_mode = 0
		try:
			with self.assertRaises(MobileAuthError) as error:
				_require_secure_transport()
			self.assertEqual(error.exception.error_code, "INSECURE_TRANSPORT")
		finally:
			frappe.conf.developer_mode = original_developer_mode
			frappe.local.request = original_request

	def test_mobile_token_extraction_uses_post_body_not_query_argument(self):
		from qcmc_logic.api.login_scan import _get_mobile_token_arg

		original_request = getattr(frappe.local, "request", None)
		request = Mock()
		request.method = "POST"
		request.args = {"mobile_token": "query-token"}
		request.form = {}
		request.get_json.return_value = {"mobile_token": "body-token"}
		frappe.local.request = request
		try:
			self.assertEqual(_get_mobile_token_arg("query-token"), "body-token")
		finally:
			frappe.local.request = original_request

	def test_resume_returns_fresh_session_and_mobile_token(self):
		from qcmc_logic.api.login_scan import resume_session
		from qcmc_logic.api.mobile_auth import issue_device_token

		issued = issue_device_token("Administrator", device_id="S2")
		original_user = frappe.session.user
		original_sid = frappe.session.sid
		original_data = frappe.session.data
		manager = Mock()

		def login_as(user):
			frappe.session.user = user
			frappe.session.sid = "renewed-sid"
			frappe.session.data = frappe._dict(csrf_token="renewed-csrf")

		manager.login_as.side_effect = login_as
		try:
			frappe.session.user = "Guest"
			with patch("qcmc_logic.api.login_scan.LoginManager", return_value=manager):
				response = resume_session(issued.mobile_token)
		finally:
			frappe.session.user = original_user
			frappe.session.sid = original_sid
			frappe.session.data = original_data

		self.assertTrue(response["success"])
		self.assertEqual(response["sid"], "renewed-sid")
		self.assertEqual(response["csrf_token"], "renewed-csrf")
		self.assertEqual(response["user"], "Administrator")
		self.assertEqual(response["user_details"]["name"], "Administrator")
		self.assertEqual(response["mobile_token"], issued.mobile_token)

	def test_resume_destroys_new_sid_when_family_revoked_during_login(self):
		from qcmc_logic.api.login_scan import resume_session
		from qcmc_logic.api.mobile_auth import issue_device_token, revoke_device_family

		issued = issue_device_token("Administrator")
		manager = Mock()
		original_user = frappe.session.user
		original_sid = frappe.session.sid
		original_data = frappe.session.data

		def login_as(user):
			frappe.session.user = user
			frappe.session.sid = "must-be-destroyed"
			frappe.session.data = frappe._dict(csrf_token="unsafe")
			revoke_device_family(issued.device_session, actor="Administrator")

		manager.login_as.side_effect = login_as
		try:
			with (
				patch("qcmc_logic.api.login_scan.LoginManager", return_value=manager),
				patch("qcmc_logic.api.login_scan.delete_session") as delete_session,
			):
				frappe.session.user = "Guest"
				response = resume_session(issued.mobile_token)
		finally:
			frappe.session.user = original_user
			frappe.session.sid = original_sid
			frappe.session.data = original_data

		self.assertFalse(response["success"])
		self.assertEqual(response["error_code"], "MOBILE_TOKEN_REVOKED")
		delete_session.assert_called_once_with("must-be-destroyed")
		self.assertNotIn("sid", response)

	def test_resume_destroys_new_sid_when_user_disabled_during_login(self):
		from qcmc_logic.api.login_scan import resume_session
		from qcmc_logic.api.mobile_auth import issue_device_token

		user = f"mobile-auth-race-{frappe.generate_hash(length=8)}@example.com"
		self._created_users.append(user)
		frappe.get_doc({
			"doctype": "User", "email": user, "first_name": "Mobile Auth Race",
			"enabled": 1, "send_welcome_email": 0,
		}).insert(ignore_permissions=True)
		issued = issue_device_token(user)
		manager = Mock()
		original_user = frappe.session.user
		original_sid = frappe.session.sid
		original_data = frappe.session.data

		def login_as(login_user):
			frappe.session.user = login_user
			frappe.session.sid = "disabled-user-sid"
			frappe.session.data = frappe._dict(csrf_token="unsafe")
			frappe.db.set_value("User", user, "enabled", 0, update_modified=False)
			frappe.db.commit()

		manager.login_as.side_effect = login_as
		try:
			with (
				patch("qcmc_logic.api.login_scan.LoginManager", return_value=manager),
				patch("qcmc_logic.api.login_scan.delete_session") as delete_session,
			):
				frappe.session.user = "Guest"
				response = resume_session(issued.mobile_token)
		finally:
			frappe.session.user = original_user
			frappe.session.sid = original_sid
			frappe.session.data = original_data

		self.assertEqual(response["error_code"], "USER_DISABLED")
		delete_session.assert_called_once_with("disabled-user-sid")
		self.assertNotIn("sid", response)

	def test_resume_does_not_hold_token_lock_during_login_session_commit(self):
		from qcmc_logic.api.login_scan import resume_session
		from qcmc_logic.api.mobile_auth import issue_device_token

		issued = issue_device_token("Administrator")
		lock_state = {"held": False}
		real_sql = frappe.db.sql
		real_commit = frappe.db.commit
		manager = Mock()
		original_user = frappe.session.user
		original_sid = frappe.session.sid
		original_data = frappe.session.data

		def tracked_sql(query, *args, **kwargs):
			if "for update" in str(query).lower():
				lock_state["held"] = True
			return real_sql(query, *args, **kwargs)

		def tracked_commit(*args, **kwargs):
			lock_state["held"] = False
			return real_commit(*args, **kwargs)

		def login_as(user):
			self.assertFalse(lock_state["held"])
			frappe.session.user = user
			frappe.session.sid = "lock-safe-sid"
			frappe.session.data = frappe._dict(csrf_token="safe")
			tracked_commit()

		manager.login_as.side_effect = login_as
		try:
			with (
				patch.object(frappe.db, "sql", side_effect=tracked_sql),
				patch.object(frappe.db, "commit", side_effect=tracked_commit),
				patch("qcmc_logic.api.login_scan.LoginManager", return_value=manager),
			):
				frappe.session.user = "Guest"
				response = resume_session(issued.mobile_token)
		finally:
			frappe.session.user = original_user
			frappe.session.sid = original_sid
			frappe.session.data = original_data

		self.assertTrue(response["success"])

	def test_resume_reports_session_failure_as_temporary(self):
		from qcmc_logic.api.login_scan import resume_session
		from qcmc_logic.api.mobile_auth import issue_device_token

		issued = issue_device_token("Administrator")
		manager = Mock()
		manager.login_as.side_effect = RuntimeError("temporary database failure")
		original_user = frappe.session.user
		original_sid = frappe.session.sid
		original_data = frappe.session.data
		try:
			with patch("qcmc_logic.api.login_scan.LoginManager", return_value=manager):
				frappe.session.user = "Guest"
				response = resume_session(issued.mobile_token)
		finally:
			frappe.session.user = original_user
			frappe.session.sid = original_sid
			frappe.session.data = original_data

		self.assertEqual(response["error_code"], "AUTH_TEMPORARILY_UNAVAILABLE")
		self.assertEqual(frappe.local.response["http_status_code"], 503)

	def test_login_issues_persistent_token_and_preserves_response_fields(self):
		from qcmc_logic.api.login_scan import login
		from qcmc_logic.api.mobile_auth import _rate_limit_key

		original_user = frappe.session.user
		original_sid = frappe.session.sid
		original_data = frappe.session.data
		manager = Mock()

		def post_login():
			frappe.session.user = "Administrator"
			frappe.session.sid = "fresh-login-sid"
			frappe.session.data = frappe._dict(csrf_token="fresh-login-csrf")

		manager.post_login.side_effect = post_login
		rate_key = _rate_limit_key(
			"login", f"{getattr(frappe.local, 'request_ip', '')}:administrator"
		)
		frappe.cache.delete(rate_key)
		try:
			with patch("qcmc_logic.api.login_scan.LoginManager", return_value=manager):
				response = login(
					"Administrator",
					"secret-password",
					device_id="S2",
					device_name="Scanner 2",
				)
		finally:
			frappe.cache.delete(rate_key)
			frappe.session.user = original_user
			frappe.session.sid = original_sid
			frappe.session.data = original_data

		self.assertTrue(response["success"])
		self.assertEqual(response["sid"], "fresh-login-sid")
		self.assertEqual(response["csrf_token"], "fresh-login-csrf")
		self.assertEqual(response["user"]["name"], "Administrator")
		self.assertTrue(response["mobile_token"])
		device_session = frappe.db.get_value(
			"Mobile Device Token",
			{"token_hash": hashlib.sha256(response["mobile_token"].encode()).hexdigest()},
			"device_session",
		)
		self.assertTrue(device_session)
		self.assertEqual(
			frappe.db.get_value("Mobile Device Session", device_session, "device_id"),
			"S2",
		)
		manager.authenticate.assert_called_once_with(
			user="Administrator", pwd="secret-password"
		)

	def test_login_rate_limit_has_stable_429_error(self):
		from qcmc_logic.api.login_scan import login
		from qcmc_logic.api.mobile_auth import MobileAuthError

		with patch(
			"qcmc_logic.api.login_scan.enforce_rate_limit",
			side_effect=MobileAuthError("AUTH_RATE_LIMITED", "Try later.", 429),
		):
			response = login("user@example.com", "never-logged")

		self.assertEqual(response["error_code"], "AUTH_RATE_LIMITED")
		self.assertEqual(frappe.local.response["http_status_code"], 429)

	def test_invalid_resume_attempts_are_rate_limited_by_request_source(self):
		from qcmc_logic.api.login_scan import resume_session
		from qcmc_logic.api.mobile_auth import _rate_limit_key

		identity = str(getattr(frappe.local, "request_ip", "") or "unknown")
		key = _rate_limit_key("resume-invalid", identity)
		frappe.cache.delete(key)
		try:
			responses = [resume_session(f"invalid-token-{index}") for index in range(11)]
		finally:
			frappe.cache.delete(key)

		self.assertEqual(responses[0]["error_code"], "MOBILE_TOKEN_INVALID")
		self.assertEqual(responses[-1]["error_code"], "AUTH_RATE_LIMITED")

	def test_logout_rejects_insecure_production_transport(self):
		from qcmc_logic.api.login_scan import logout

		original_request = getattr(frappe.local, "request", None)
		original_developer_mode = frappe.conf.get("developer_mode")
		request = Mock()
		request.method = "POST"
		request.get_json.return_value = {"mobile_token": "sensitive-token"}
		request.form = {}
		request.is_secure = False
		request.host = "erp.example.com"
		request.headers = {"X-Forwarded-Proto": "http"}
		frappe.local.request = request
		frappe.conf.developer_mode = 0
		try:
			response = logout()
		finally:
			frappe.conf.developer_mode = original_developer_mode
			frappe.local.request = original_request

		self.assertFalse(response["success"])
		self.assertEqual(response["error_code"], "INSECURE_TRANSPORT")
