"""Fail-closed security regression tests; no site writes."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import frappe
from qcmc_logic import dynamic_reorder_permissions as permissions
from qcmc_logic import dynamic_reorder_dashboard as dashboard
from qcmc_logic import dynamic_reorder_service as service

class TestReorderPermissionBoundary(unittest.TestCase):
    def test_list_restricted(self):
        self.assertEqual(permissions.query("Administrator"),"")
        for user in ("Guest","planner@example.test","manager@example.test"):
            self.assertEqual(permissions.query(user),"1=0")

    def test_document_restricted(self):
        for action in ("read","write","create","delete","export"):
            self.assertFalse(permissions.has_permission(None,"planner@example.test",action))
            self.assertTrue(permissions.has_permission(None,"Administrator",action))

    def test_overview_denied_before_queries(self):
        with patch.object(frappe,"session",SimpleNamespace(user="planner@example.test")),patch.object(frappe,"get_single") as read,patch.object(frappe,"throw",side_effect=frappe.PermissionError):
            with self.assertRaises(frappe.PermissionError):
                dashboard.overview()
            read.assert_not_called()

    def test_mutation_denied_for_non_admin(self):
        with patch.object(frappe,"session",SimpleNamespace(user="planner@example.test")),patch.object(frappe,"throw",side_effect=frappe.PermissionError):
            with self.assertRaises(frappe.PermissionError):
                service.require_admin()
