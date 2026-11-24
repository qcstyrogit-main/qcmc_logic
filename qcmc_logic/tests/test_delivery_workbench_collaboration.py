"""Site-free API tests and real Lua tests against a disposable Unix-socket Redis.

Never connects to a bench Redis or site database. Redis persistence is disabled.
"""
import concurrent.futures
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from unittest import TestCase, SkipTest
from unittest.mock import MagicMock, patch

import frappe
from redis import Redis
from redis.exceptions import RedisError

from qcmc_logic.api import delivery_workbench_collaboration as collaboration
from qcmc_logic.api import delivery_confirmation_service as confirmation


class TestWorkbenchCollaboration(TestCase):
	@classmethod
	def setUpClass(cls):
		if not shutil.which("redis-server"):
			raise SkipTest("redis-server required for isolated lease tests")
		cls.directory = tempfile.TemporaryDirectory(prefix="qcmc-workbench-test-")
		socket = str(Path(cls.directory.name) / "redis.sock")
		cls.process = subprocess.Popen(["redis-server", "--port", "0", "--unixsocket", socket,
			"--unixsocketperm", "700", "--save", "", "--appendonly", "no"],
			stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		cls.cache = Redis(unix_socket_path=socket)
		for _ in range(100):
			try:
				if cls.cache.ping():
					break
			except ConnectionError:
				pass
			except Exception:
				if cls.process.poll() is not None:
					raise RuntimeError("Disposable Redis failed to start")
			time.sleep(.02)
		else:
			cls.process.terminate()
			raise RuntimeError("Disposable Redis unavailable")
		cls.cache.make_key = lambda key: f"isolated-test:{key}"

	@classmethod
	def tearDownClass(cls):
		cls.cache.close()
		cls.process.terminate()
		cls.process.wait(timeout=5)
		cls.directory.cleanup()

	def setUp(self):
		self.cache.flushdb()  # Only this test's private Redis process.
		self.doc = MagicMock(name="Delivery Note")
		self.doc.name = "_Test-DN"
		self.doc.doctype = "Delivery Note"
		self.doc.modified = "v1"
		self.doc.flags = frappe._dict()
		self.flags = frappe._dict()
		self.session = frappe._dict(user="_Test-user")
		self.db = MagicMock()
		def fail(message, exc=frappe.ValidationError, **kwargs):
			raise exc(message)
		for patcher in (
			patch.object(frappe, "cache", self.cache),
			patch.object(frappe, "session", self.session),
			patch.object(frappe, "flags", self.flags),
			patch.object(frappe, "db", self.db),
			patch.object(frappe, "get_roles", return_value=["Sales Coordinator"]),
			patch.object(frappe, "get_doc", return_value=self.doc),
			patch.object(frappe, "get_cached_value", return_value="Test Editor"),
			patch.object(frappe, "throw", side_effect=fail),
			patch.object(frappe, "get_all", return_value=["_Test-viewer"]),
			patch.object(frappe, "publish_realtime"),
			patch.object(collaboration, "_", side_effect=lambda value: value),
			patch.object(confirmation, "_get_locked_delivery_note", return_value=self.doc),
			patch.object(confirmation, "_validate_sales_review_delivery_note"),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def acquire(self, client="a" * 20):
		return collaboration.acquire_edit(self.doc.name, client, "v1")

	def test_one_browser_wins_and_same_user_other_tab_is_locked(self):
		first = self.acquire()
		self.assertTrue(first["acquired"])
		second = self.acquire("b" * 20)
		self.assertFalse(second["acquired"])
		self.assertFalse(second["lock"]["mine"])
		self.assertNotIn("token", second)
		self.assertEqual(self.acquire()["token"], first["token"])
		self.session.user = "_Test-other-user"
		self.assertFalse(self.acquire()["acquired"])

	def test_real_lua_allows_exactly_one_concurrent_holder(self):
		key = collaboration._key(self.doc.name)
		def attempt(index):
			entry = dict(user=str(index), client=str(index), token=str(index), owner_name=str(index))
			return json.loads(self.cache.eval(collaboration.ACQUIRE, 1, key, json.dumps(entry), str(index), str(index), collaboration.TTL))["user"]
		with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
			owners = list(pool.map(attempt, range(32)))
		self.assertEqual(len(set(owners)), 1)

	def test_stale_release_and_foreign_user_cannot_remove_lock(self):
		token = self.acquire()["token"]
		self.assertFalse(collaboration.release_edit(self.doc.name, "stale")["released"])
		self.session.user = "_Test-other-user"
		self.assertFalse(collaboration.release_edit(self.doc.name, token)["released"])
		self.session.user = "_Test-user"
		self.assertTrue(collaboration.release_edit(self.doc.name, token)["released"])
		self.assertIsNone(collaboration._entry(self.doc.name))

	def test_heartbeat_renews_only_matching_browser_and_token(self):
		token = self.acquire()["token"]
		self.cache.expire(collaboration._key(self.doc.name), 2)
		state = collaboration.get_state([self.doc.name], "a" * 20, {self.doc.name: token})
		self.assertEqual(state["renewed"], [self.doc.name])
		self.assertGreater(self.cache.ttl(collaboration._key(self.doc.name)), 25)
		self.assertLessEqual(self.cache.ttl(collaboration._key(self.doc.name)), 30)
		state = collaboration.get_state([self.doc.name], "b" * 20, {self.doc.name: token})
		self.assertEqual(state["renewed"], [])

	def test_expired_token_cannot_save_or_release_new_holder(self):
		token = self.acquire()["token"]
		self.cache.delete(collaboration._key(self.doc.name))  # Simulate expiry deterministically.
		with self.assertRaises(frappe.ValidationError):
			collaboration.bind_edit(self.doc, token)
		new = self.acquire("b" * 20)
		self.assertFalse(collaboration.release_edit(self.doc.name, token)["released"])
		self.assertNotEqual(new["token"], token)

	def test_server_guard_blocks_form_and_allows_bound_workbench_save(self):
		token = self.acquire()["token"]
		with self.assertRaises(frappe.ValidationError):
			collaboration.guard_edit(self.doc)
		collaboration.bind_edit(self.doc, token)
		collaboration.guard_edit(self.doc)
		other = MagicMock()
		other.name, other.flags = self.doc.name, frappe._dict()
		collaboration.guard_edit(other)  # Delegated API in same request.
		self.session.user = "_Test-other-user"
		with self.assertRaises(frappe.ValidationError):
			collaboration.guard_edit(other)

	def test_unleased_normal_form_save_is_allowed(self):
		collaboration.guard_edit(self.doc)

	def test_stale_document_and_invalid_client_cannot_acquire(self):
		with self.assertRaises(frappe.TimestampMismatchError):
			collaboration.acquire_edit(self.doc.name, "a" * 20, "old")
		with self.assertRaises(frappe.ValidationError):
			self.acquire("invalid")
		self.assertIsNone(collaboration._entry(self.doc.name))

	def test_authorization_precedes_lock_disclosure(self):
		self.doc.check_permission.side_effect = frappe.PermissionError
		with self.assertRaises(frappe.PermissionError):
			self.acquire()
		with self.assertRaises(frappe.PermissionError):
			collaboration.get_state([self.doc.name], "a" * 20, {})
		self.assertIsNone(collaboration._entry(self.doc.name))

	def test_non_workbench_roles_cannot_use_api(self):
		with patch.object(frappe, "get_roles", return_value=[]):
			with self.assertRaises(frappe.PermissionError):
				self.acquire()

	def test_invalid_state_payload_is_rejected(self):
		for names in ([[{}]], [1], [""]):
			with self.assertRaises(frappe.ValidationError):
				collaboration.get_state(names, "a" * 20, {})

	def test_committed_refresh_is_private_coalesced_and_revision_is_deferred(self):
		collaboration.notify_change(self.doc)
		collaboration.notify_change(self.doc)
		self.assertEqual(collaboration.revision(), 0)
		self.db.after_commit.add.assert_called_once_with(collaboration._increment_revision)
		calls = frappe.publish_realtime.call_args_list
		self.assertEqual(len(calls), 2)
		for call in calls:
			self.assertEqual(call.args, (collaboration.EVENT, {"kind": "saved"}))
			self.assertTrue(call.kwargs["after_commit"])
			self.assertIn(call.kwargs["user"], {"Administrator", "_Test-viewer"})
		self.db.after_commit.add.call_args.args[0]()
		self.assertEqual(collaboration.revision(), 1)

	def test_redis_outage_fails_closed_for_saves(self):
		with patch.object(self.cache, "get", side_effect=RedisError("Offline")):
			with self.assertRaises(frappe.ValidationError):
				collaboration.guard_edit(self.doc)

	def test_rollback_allows_a_later_change_to_queue_a_notification(self):
		collaboration.notify_change(self.doc)
		self.db.after_rollback.add.assert_called_once_with(collaboration._clear_queued_change)
		self.db.after_rollback.add.call_args.args[0]()
		self.assertFalse(self.flags.delivery_workbench_change_queued)
		collaboration.notify_change(self.doc)
		self.assertEqual(self.db.after_commit.add.call_count, 2)
