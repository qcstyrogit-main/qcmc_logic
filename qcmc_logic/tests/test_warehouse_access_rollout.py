from unittest import TestCase
from unittest.mock import patch

import frappe

from qcmc_logic.customs.permissions import (
    WAREHOUSE_TRANSACTION_DOCTYPES,
    _sales_transaction_read_permission_query,
    _warehouse_access_applies,
    _warehouse_transaction_permission_query,
    sales_transaction_has_permission,
    warehouse_transaction_has_permission,
    warehouse_transfer_has_permission,
    warehouse_transfer_permission_query,
)
from qcmc_logic.customs.sales_transaction_territory import (
    populate_mapped_transaction_territory,
)
from qcmc_logic.customs.manufacturing_warehouse_access import (
    bom_permission_query,
    work_order_permission_query,
)
from qcmc_logic.customs.warehouse_access_permissions import SKIP_DOCTYPES
from qcmc_logic.utils import check_warehouse_access, ensure_scanner_warehouse_access


class TestWarehouseAccessRollout(TestCase):
    def test_scanner_read_uses_list_view_warehouse_access(self):
        with patch(
            "qcmc_logic.utils.get_user_allowed_warehouses",
            return_value=["FG - Sta Clara"],
        ) as allowed:
            ensure_scanner_warehouse_access(
                "scanner@example.com", ["FG - Sta Clara"], require_transact=False
            )

        allowed.assert_called_once_with(
            "scanner@example.com",
            require_transact=False,
            require_list_view=True,
            source="Role Profile",
        )

    def test_scanner_write_uses_transact_warehouse_access(self):
        with patch(
            "qcmc_logic.utils.get_user_allowed_warehouses",
            return_value=["FG - Sta Clara"],
        ) as allowed:
            ensure_scanner_warehouse_access(
                "scanner@example.com", ["FG - Sta Clara"], require_transact=True
            )

        allowed.assert_called_once_with(
            "scanner@example.com",
            require_transact=True,
            require_list_view=False,
            source="Role Profile",
        )

    def test_scanner_rejects_any_warehouse_not_in_role_profile_access(self):
        with patch(
            "qcmc_logic.utils.get_user_allowed_warehouses",
            return_value=["FG - Sta Clara"],
        ):
            with self.assertRaises(frappe.PermissionError):
                ensure_scanner_warehouse_access(
                    "scanner@example.com",
                    ["FG - Sta Clara", "FG - Guyong"],
                    require_transact=True,
                )

    def _transaction_doc(self, doctype, rows=None, **values):
        table_fields = []
        for fieldname, child_doctype in (rows or {}).keys():
            table_fields.append(
                frappe._dict(
                    fieldname=fieldname,
                    fieldtype="Table",
                    options=child_doctype,
                )
            )

        doc = frappe._dict(
            doctype=doctype,
            docstatus=0,
            meta=frappe._dict(
                fields=table_fields,
                has_field=lambda fieldname: fieldname in values,
            ),
            **values,
        )
        for (fieldname, _child_doctype), child_rows in (rows or {}).items():
            doc[fieldname] = [frappe._dict(row) for row in child_rows]

        return doc

    def _sales_doc(self, doctype, territory="South Luzon", warehouse="HO - QC"):
        child_doctype = f"{doctype} Item"
        return self._transaction_doc(
            doctype,
            rows={("items", child_doctype): [{"warehouse": warehouse}]},
            territory=territory,
            set_warehouse=warehouse,
        )

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

    def test_material_request_read_allows_target_list_view_even_if_source_is_disallowed(self):
        doc = self._transaction_doc(
            "Material Request",
            rows={
                ("items", "Material Request Item"): [
                    {
                        "from_warehouse": "Stockroom - Sta Clara",
                        "warehouse": "FG - Sta Clara",
                    }
                ]
            },
            set_from_warehouse="Stockroom - Sta Clara",
            set_warehouse="FG - Sta Clara",
        )

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.territory_has_permission", return_value=True),
        ):
            self.assertTrue(
                warehouse_transaction_has_permission(
                    doc,
                    ptype="read",
                    user="scfgencoder@qcstyro.com",
                )
            )

    def test_material_request_read_allows_source_list_view_even_if_target_is_disallowed(self):
        doc = self._transaction_doc(
            "Material Request",
            rows={
                ("items", "Material Request Item"): [
                    {
                        "from_warehouse": "Stockroom - Sta Clara",
                        "warehouse": "FG - Sta Clara",
                    }
                ]
            },
            set_from_warehouse="Stockroom - Sta Clara",
            set_warehouse="FG - Sta Clara",
        )

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["Stockroom - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.territory_has_permission", return_value=True),
        ):
            self.assertTrue(
                warehouse_transaction_has_permission(
                    doc,
                    ptype="select",
                    user="stockroom@example.com",
                )
            )

    def test_material_request_read_allows_when_both_warehouses_are_list_view_allowed(self):
        doc = self._transaction_doc(
            "Material Request",
            rows={
                ("items", "Material Request Item"): [
                    {
                        "from_warehouse": "Stockroom - Sta Clara",
                        "warehouse": "FG - Sta Clara",
                    }
                ]
            },
            set_from_warehouse="Stockroom - Sta Clara",
            set_warehouse="FG - Sta Clara",
        )

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["Stockroom - Sta Clara", "FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.territory_has_permission", return_value=True),
        ):
            self.assertTrue(
                warehouse_transaction_has_permission(
                    doc,
                    ptype="read",
                    user="user@example.com",
                )
            )

    def test_material_request_read_blocks_when_no_warehouse_is_list_view_allowed(self):
        doc = self._transaction_doc(
            "Material Request",
            rows={
                ("items", "Material Request Item"): [
                    {
                        "from_warehouse": "Stockroom - Sta Clara",
                        "warehouse": "FG - Sta Clara",
                    }
                ]
            },
            set_from_warehouse="Stockroom - Sta Clara",
            set_warehouse="FG - Sta Clara",
        )

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["RMFS - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.territory_has_permission", return_value=True),
        ):
            self.assertFalse(
                warehouse_transaction_has_permission(
                    doc,
                    ptype="read",
                    user="rmfs@example.com",
                )
            )

    def test_blank_warehouse_fields_do_not_grant_read_access(self):
        doc = self._transaction_doc(
            "Material Request",
            rows={
                ("items", "Material Request Item"): [
                    {
                        "from_warehouse": None,
                        "warehouse": None,
                    }
                ]
            },
            set_from_warehouse=None,
            set_warehouse=None,
        )

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.territory_has_permission", return_value=True),
        ):
            self.assertFalse(
                warehouse_transaction_has_permission(
                    doc,
                    ptype="read",
                    user="scfgencoder@qcstyro.com",
                )
            )

    def test_material_request_write_still_requires_all_transaction_warehouses(self):
        doc = self._transaction_doc(
            "Material Request",
            rows={
                ("items", "Material Request Item"): [
                    {
                        "from_warehouse": "Stockroom - Sta Clara",
                        "warehouse": "FG - Sta Clara",
                    }
                ]
            },
            set_from_warehouse="Stockroom - Sta Clara",
            set_warehouse="FG - Sta Clara",
        )

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.territory_has_permission", return_value=True),
        ):
            self.assertFalse(
                warehouse_transaction_has_permission(
                    doc,
                    ptype="write",
                    user="scfgencoder@qcstyro.com",
                )
            )

    def test_stock_entry_read_allows_when_either_source_or_target_is_list_view_allowed(self):
        doc = self._transaction_doc(
            "Stock Entry",
            rows={
                ("items", "Stock Entry Detail"): [
                    {
                        "s_warehouse": "Stockroom - Sta Clara",
                        "t_warehouse": "FG - Sta Clara",
                    }
                ]
            },
            from_warehouse="Stockroom - Sta Clara",
            to_warehouse="FG - Sta Clara",
        )

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.territory_has_permission", return_value=True),
        ):
            self.assertTrue(
                warehouse_transaction_has_permission(
                    doc,
                    ptype="read",
                    user="scfgencoder@qcstyro.com",
                )
            )

    def test_stock_entry_write_still_requires_all_transaction_warehouses(self):
        doc = self._transaction_doc(
            "Stock Entry",
            rows={
                ("items", "Stock Entry Detail"): [
                    {
                        "s_warehouse": "Stockroom - Sta Clara",
                        "t_warehouse": "FG - Sta Clara",
                    }
                ]
            },
            from_warehouse="Stockroom - Sta Clara",
            to_warehouse="FG - Sta Clara",
        )

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.territory_has_permission", return_value=True),
        ):
            self.assertFalse(
                warehouse_transaction_has_permission(
                    doc,
                    ptype="submit",
                    user="scfgencoder@qcstyro.com",
                )
            )

    def test_warehouse_transaction_list_query_only_requires_one_allowed_warehouse(self):
        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions._get_transaction_config") as get_config,
            patch("qcmc_logic.customs.permissions._sql_list", return_value="'FG - Sta Clara'"),
        ):
            get_config.return_value = {
                "fields": ["set_warehouse", "set_from_warehouse"],
                "children": {"Material Request Item": ["warehouse", "from_warehouse"]},
            }
            query = _warehouse_transaction_permission_query(
                "Material Request",
                "scfgencoder@qcstyro.com",
            )

        self.assertIn("`tabMaterial Request`.`set_warehouse` IN", query)
        self.assertIn("`tabMaterial Request`.`set_from_warehouse` IN", query)
        self.assertIn("`tabMaterial Request Item`.`warehouse` IN", query)
        self.assertIn("`tabMaterial Request Item`.`from_warehouse` IN", query)
        self.assertIn(" OR ", query)
        self.assertNotIn("NOT IN", query)
        self.assertNotIn("NOT EXISTS", query)

    def test_sales_transaction_read_allows_warehouse_without_territory(self):
        doc = self._sales_doc("Sales Order", territory="North Luzon", warehouse="FG - Sta Clara")

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.has_territory_access", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_territories",
                return_value=["South Luzon"],
            ),
        ):
            self.assertTrue(sales_transaction_has_permission(doc, "read", "user@example.com"))

    def test_sales_transaction_read_allows_territory_without_warehouse(self):
        doc = self._sales_doc("Delivery Note", territory="South Luzon", warehouse="HO - QC")

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.has_territory_access", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_territories",
                return_value=["South Luzon"],
            ),
        ):
            self.assertTrue(sales_transaction_has_permission(doc, "select", "user@example.com"))

    def test_sales_transaction_read_allows_when_both_systems_match(self):
        doc = self._sales_doc("Sales Invoice", territory="South Luzon", warehouse="FG - Sta Clara")

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.has_territory_access", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_territories",
                return_value=["South Luzon"],
            ),
        ):
            self.assertTrue(sales_transaction_has_permission(doc, "read", "user@example.com"))

    def test_sales_transaction_read_denies_when_neither_system_matches(self):
        doc = self._sales_doc("Sales Order", territory="North Luzon", warehouse="HO - QC")

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.has_territory_access", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_territories",
                return_value=["South Luzon"],
            ),
        ):
            self.assertFalse(sales_transaction_has_permission(doc, "read", "user@example.com"))

    def test_sales_transaction_blank_territory_does_not_bypass_warehouse(self):
        doc = self._sales_doc("Delivery Note", territory="", warehouse="HO - QC")

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.has_territory_access", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_territories",
                return_value=["South Luzon"],
            ),
        ):
            self.assertFalse(sales_transaction_has_permission(doc, "read", "user@example.com"))

    def test_sales_transaction_read_allowed_but_write_denied_without_transaction_flag(self):
        doc = self._sales_doc("Sales Invoice", territory="South Luzon", warehouse="FG - Sta Clara")

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.has_territory_access", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_territories",
                return_value=["South Luzon"],
            ),
            patch(
                "qcmc_logic.customs.permissions.territory_has_permission",
                side_effect=[False],
            ),
        ):
            self.assertTrue(sales_transaction_has_permission(doc, "read", "user@example.com"))
            self.assertFalse(sales_transaction_has_permission(doc, "write", "user@example.com"))

    def test_sales_transaction_territory_transaction_does_not_grant_warehouse_transaction(self):
        doc = self._sales_doc("Sales Order", territory="South Luzon", warehouse="HO - QC")

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.has_territory_access", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_territories",
                return_value=["South Luzon"],
            ),
        ):
            self.assertFalse(sales_transaction_has_permission(doc, "submit", "user@example.com"))

    def test_sales_transaction_without_role_profile_territory_keeps_warehouse_behavior(self):
        doc = self._sales_doc("Sales Order", territory="South Luzon", warehouse="HO - QC")

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.has_territory_access", return_value=False),
        ):
            self.assertFalse(sales_transaction_has_permission(doc, "read", "user@example.com"))

    def test_sales_transaction_administrator_remains_unrestricted(self):
        doc = self._sales_doc("Sales Invoice", territory="", warehouse="HO - QC")

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=False),
            patch("qcmc_logic.customs.permissions.has_territory_access", return_value=False),
        ):
            self.assertTrue(sales_transaction_has_permission(doc, "read", "Administrator"))

    def test_sales_transaction_list_query_matches_direct_document_or_logic(self):
        doc = self._sales_doc("Delivery Note", territory="South Luzon", warehouse="HO - QC")

        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions.has_territory_access", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_territories",
                return_value=["South Luzon"],
            ),
            patch(
                "qcmc_logic.customs.permissions._warehouse_transaction_permission_query",
                return_value="warehouse_condition",
            ),
            patch(
                "qcmc_logic.customs.permissions.frappe.get_meta",
                return_value=frappe._dict(has_field=lambda fieldname: fieldname == "territory"),
            ),
        ):
            query = _sales_transaction_read_permission_query("Delivery Note", "user@example.com")
            self.assertTrue(sales_transaction_has_permission(doc, "read", "user@example.com"))

        self.assertIn("(warehouse_condition) OR", query)
        self.assertIn("`tabDelivery Note`.`territory` IS NOT NULL", query)

    def test_unrelated_warehouse_doctype_still_uses_warehouse_only_list_query(self):
        with (
            patch("qcmc_logic.customs.permissions._warehouse_access_applies", return_value=True),
            patch(
                "qcmc_logic.customs.permissions.get_user_allowed_warehouses",
                return_value=["FG - Sta Clara"],
            ),
            patch("qcmc_logic.customs.permissions._get_transaction_config") as get_config,
            patch("qcmc_logic.customs.permissions._sql_list", return_value="'FG - Sta Clara'"),
        ):
            get_config.return_value = {
                "fields": ["set_warehouse"],
                "children": {"Material Request Item": ["warehouse"]},
            }
            query = _warehouse_transaction_permission_query(
                "Material Request",
                "user@example.com",
            )

        self.assertIn("`tabMaterial Request`.`set_warehouse` IN", query)
        self.assertNotIn("territory", query.lower())

    def test_mapped_delivery_note_populates_blank_territory_from_sales_order(self):
        doc = self._sales_doc("Delivery Note", territory="", warehouse="HO - QC")
        doc["items"][0].sales_order = "SO-0001"

        with patch("qcmc_logic.customs.sales_transaction_territory.frappe.db.get_value") as get_value:
            get_value.return_value = "South Luzon"
            populate_mapped_transaction_territory(doc)

        self.assertEqual(doc.territory, "South Luzon")
        get_value.assert_called_once_with("Sales Order", "SO-0001", "territory")

    def test_mapped_sales_invoice_keeps_explicit_territory(self):
        doc = self._sales_doc("Sales Invoice", territory="North Luzon", warehouse="HO - QC")
        doc["items"][0].delivery_note = "DN-0001"

        with patch("qcmc_logic.customs.sales_transaction_territory.frappe.db.get_value") as get_value:
            populate_mapped_transaction_territory(doc)

        self.assertEqual(doc.territory, "North Luzon")
        get_value.assert_not_called()

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
