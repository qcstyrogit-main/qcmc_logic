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
