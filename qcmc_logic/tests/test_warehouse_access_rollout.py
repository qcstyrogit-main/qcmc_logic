from unittest import TestCase
from unittest.mock import patch

import frappe

from qcmc_logic.customs.permissions import (
    WAREHOUSE_TRANSACTION_DOCTYPES,
    _warehouse_access_applies,
    warehouse_transfer_has_permission,
    warehouse_transfer_permission_query,
)
from qcmc_logic.customs.manufacturing_warehouse_access import (
    bom_permission_query,
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

    def test_manufacturing_planning_doctypes_use_targeted_warehouse_rules(self):
        self.assertNotIn("Work Order", WAREHOUSE_TRANSACTION_DOCTYPES)
        self.assertIn("BOM", SKIP_DOCTYPES)
        self.assertIn("Job Card", SKIP_DOCTYPES)
        self.assertIn("Work Order", SKIP_DOCTYPES)
        self.assertIn("Stock Entry", WAREHOUSE_TRANSACTION_DOCTYPES)

        with (
            patch(
                "qcmc_logic.customs.manufacturing_warehouse_access."
                "is_global_warehouse_access_enabled",
                return_value=True,
            ),
            patch(
                "qcmc_logic.customs.manufacturing_warehouse_access.has_warehouse_access",
                return_value=True,
            ),
            patch(
                "qcmc_logic.customs.manufacturing_warehouse_access.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
        ):
            query = work_order_permission_query("user@example.com")

        self.assertIn("`tabWork Order`.`fg_warehouse`", query)
        self.assertIn("`tabWork Order Item` child", query)
        self.assertIn("child.`source_warehouse` NOT IN", query)
        self.assertIn("`tabWork Order Operation` child", query)
        self.assertIn("child.`wip_warehouse` NOT IN", query)

    def test_bom_list_filters_by_role_profile_default_warehouse_company(self):
        with patch(
            "qcmc_logic.customs.manufacturing_warehouse_access."
            "get_default_company_from_role_profile_default_warehouse",
            return_value="QC Styropackaging Corporation",
        ):
            query = bom_permission_query("user@example.com")

        self.assertIn("`tabBOM`.`company`", query)
        self.assertIn("QC Styropackaging Corporation", query)

    def test_bom_list_uses_default_behavior_without_role_profile_default_warehouse(self):
        with patch(
            "qcmc_logic.customs.manufacturing_warehouse_access."
            "get_default_company_from_role_profile_default_warehouse",
            return_value=None,
        ):
            self.assertEqual(bom_permission_query("user@example.com"), "")

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

    def test_warehouse_transfer_sender_can_read_and_save_by_source_warehouse(self):
        doc = frappe._dict(
            doctype="Warehouse Transfer",
            docstatus=0,
            source_warehouse="FG - Sta Clara",
            target_warehouse="FG - La Union - MC",
        )

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ) as get_user_allowed_warehouses,
        ):
            self.assertTrue(
                warehouse_transfer_has_permission(
                    doc,
                    ptype="read",
                    user="scwarehouse@qcstyro.com",
                )
            )
            self.assertTrue(
                warehouse_transfer_has_permission(
                    doc,
                    ptype="write",
                    user="scwarehouse@qcstyro.com",
                )
            )
        get_user_allowed_warehouses.assert_any_call(
            "scwarehouse@qcstyro.com",
            require_list_view=True,
        )
        get_user_allowed_warehouses.assert_any_call(
            "scwarehouse@qcstyro.com",
            require_transact=True,
        )

    def test_warehouse_transfer_receiver_can_read_by_target_warehouse(self):
        doc = frappe._dict(
            doctype="Warehouse Transfer",
            docstatus=1,
            source_warehouse="FG - Sta Clara",
            target_warehouse="FG - La Union - MC",
        )

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - La Union - MC"],
            ),
        ):
            self.assertTrue(
                warehouse_transfer_has_permission(
                    doc,
                    ptype="read",
                    user="receiver@example.com",
                )
            )
            self.assertTrue(
                warehouse_transfer_has_permission(
                    doc,
                    ptype="write",
                    user="receiver@example.com",
                )
            )

    def test_warehouse_transfer_list_query_allows_source_or_target_access(self):
        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ) as get_user_allowed_warehouses,
            patch(
                "qcmc_logic.customs.permissions._sql_list",
                return_value="'FG - Sta Clara'",
            ),
        ):
            query = warehouse_transfer_permission_query("scwarehouse@qcstyro.com")

        get_user_allowed_warehouses.assert_called_once_with(
            "scwarehouse@qcstyro.com",
            require_list_view=True,
        )
        self.assertIn("`source_warehouse` IN", query)
        self.assertIn("`target_warehouse` IN", query)
        self.assertIn(" OR ", query)
