from unittest import TestCase
from unittest.mock import patch

from qcmc_logic.customs.permissions import (
    WAREHOUSE_TRANSACTION_DOCTYPES,
    _warehouse_access_applies,
    work_order_permission_query,
)
from qcmc_logic.customs.warehouse_access_permissions import SKIP_DOCTYPES
from qcmc_logic.utils import check_warehouse_access


class TestWarehouseAccessRollout(TestCase):
    def test_permission_gate_is_unrestricted_without_access_records(self):
        with (
            patch(
                "qcmc_logic.customs.permissions.is_global_warehouse_access_enabled",
                return_value=True,
            ),
            patch(
                "qcmc_logic.customs.permissions.has_warehouse_access",
                return_value=False,
            ),
        ):
            self.assertFalse(_warehouse_access_applies("user@example.com"))

    def test_permission_gate_applies_after_access_records_exist(self):
        with (
            patch(
                "qcmc_logic.customs.permissions.is_global_warehouse_access_enabled",
                return_value=True,
            ),
            patch(
                "qcmc_logic.customs.permissions.has_warehouse_access",
                return_value=True,
            ),
        ):
            self.assertTrue(_warehouse_access_applies("user@example.com"))

    def test_check_warehouse_access_allows_unconfigured_users(self):
        with patch("qcmc_logic.utils.has_warehouse_access", return_value=False):
            self.assertTrue(
                check_warehouse_access(
                    "user@example.com",
                    "RMFS - EDSA",
                    require_transact=True,
                )
            )

    def test_manufacturing_planning_doctypes_are_not_warehouse_restricted(self):
        self.assertNotIn("Work Order", WAREHOUSE_TRANSACTION_DOCTYPES)
        self.assertEqual(work_order_permission_query("user@example.com"), "")
        self.assertIn("BOM", SKIP_DOCTYPES)
        self.assertIn("Job Card", SKIP_DOCTYPES)
        self.assertIn("Work Order", SKIP_DOCTYPES)
        self.assertIn("Stock Entry", WAREHOUSE_TRANSACTION_DOCTYPES)

    def test_setup_helper_and_master_doctypes_are_strictly_excluded(self):
        expected_exclusions = {
            "Allowed Warehouse",
            "BOM",
            "BOM Creator",
            "Bin",
            "Cost Center Warehouse Mapping",
            "Item Default",
            "Job Card",
            "Production Plan",
            "Putaway Rule",
            "Role Profile Warehouse Access",
            "Serial and Batch Bundle",
            "Stock Ledger Entry",
            "Stock Settings",
            "User Permission",
            "Warehouse",
            "Warehouse Access",
            "Work Order",
            "Workstation",
        }

        self.assertTrue(expected_exclusions.issubset(SKIP_DOCTYPES))
        self.assertTrue(expected_exclusions.isdisjoint(WAREHOUSE_TRANSACTION_DOCTYPES))

    def test_stock_transaction_doctypes_are_restricted(self):
        expected_transactions = {
            "Delivery Note",
            "Material Request",
            "Pick List",
            "POS Invoice",
            "Purchase Invoice",
            "Purchase Order",
            "Purchase Receipt",
            "Sales Invoice",
            "Sales Order",
            "Stock Entry",
            "Stock Reconciliation",
            "Subcontracting Order",
            "Subcontracting Receipt",
            "Warehouse Transfer",
        }

        self.assertTrue(expected_transactions.issubset(WAREHOUSE_TRANSACTION_DOCTYPES))
