"""Regression checks using mocked database reads; no real documents are saved."""
import unittest
from unittest.mock import MagicMock, patch
import frappe
from qcmc_logic import dynamic_reorder_native_guard as guard


def fail(message, *args, **kwargs):
    raise ValueError(message)


class Request(frappe._dict):
    def set(self, key, value):
        self[key] = value


def request(auto=1):
    return Request(auto_created_via_reorder=auto, schedule_date="2026-12-05", items=[
        frappe._dict(item_code="Managed", warehouse="A", schedule_date="2026-12-05"),
        frappe._dict(item_code="Unmanaged", warehouse="B", schedule_date="2026-12-01"),
        frappe._dict(item_code="Managed", warehouse="C", schedule_date="2026-12-02"),
    ])


class TestNativeGuard(unittest.TestCase):
    def test_manual_request_unchanged(self):
        doc = request(0)
        with patch.object(frappe, "db", MagicMock()) as db:
            guard.filter_new_native_request(doc)
            guard.validate_native_request(doc)
            db.sql.assert_not_called()
        self.assertEqual(len(doc["items"]), 3)

    def test_mixed_request_retains_unmanaged_pairs(self):
        doc = request()
        with patch.object(guard, "protected_pairs", return_value={("Managed", "A")}):
            guard.filter_new_native_request(doc)
            guard.validate_native_request(doc)
        self.assertEqual([(r.item_code,r.warehouse) for r in doc["items"]],
                         [("Unmanaged","B"),("Managed","C")])
        self.assertEqual(doc.schedule_date, "2026-12-02")

    def test_all_managed_blocked(self):
        doc = request()
        with patch.object(guard, "protected_pairs", return_value={(r.item_code,r.warehouse) for r in doc["items"]}), patch.object(frappe,"throw",side_effect=fail):
            with self.assertRaisesRegex(ValueError,"no unmanaged"):
                guard.filter_new_native_request(doc)
        self.assertEqual(len(doc["items"]),3)

    def test_unmanaged_unchanged(self):
        doc = request()
        with patch.object(guard,"protected_pairs",return_value=set()):
            guard.filter_new_native_request(doc)
            guard.validate_native_request(doc)
        self.assertEqual(len(doc["items"]),3)
        self.assertEqual(doc.schedule_date,"2026-12-05")

    def test_validation_blocks_conflicting_rows(self):
        doc = request()
        with patch.object(guard,"protected_pairs",return_value={("Managed","A")}), patch.object(frappe,"throw",side_effect=fail):
            with self.assertRaisesRegex(ValueError,"Managed / A"):
                guard.validate_native_request(doc)

    def test_native_guard_includes_preserved_guyong_marker(self):
        doc = request()
        with patch.object(frappe,"db",MagicMock()) as db, patch.object(frappe,"get_meta") as meta:
            meta.return_value.has_field.return_value=True
            db.sql.side_effect=[[],[frappe._dict(parent="Managed",warehouse="FG - Guyong")]]
            self.assertEqual(guard.protected_pairs(doc),{("Managed","FG - Guyong")})
            self.assertIn("custom_reorder_excluded_mapping", db.sql.call_args.args[0])

    def test_database_lookup_locks_items(self):
        doc = request()
        with patch.object(frappe,"db",MagicMock()) as db, patch.object(frappe,"get_meta") as meta:
            meta.return_value.has_field.return_value=True
            db.sql.side_effect=[[],[frappe._dict(parent="Managed",warehouse="A")]]
            self.assertEqual(guard.protected_pairs(doc),{("Managed","A")})
            self.assertEqual(db.sql.call_count,2)
            for call in db.sql.call_args_list:
                self.assertIn("FOR UPDATE",call.args[0])
                self.assertEqual(call.args[1],("Managed","Unmanaged"))
            db.set_value.assert_not_called()
            db.commit.assert_not_called()
