from unittest import TestCase
from unittest.mock import patch

import frappe

from qcmc_logic.customs.manufacturing_warehouse_access import (
    sales_order_reference_query,
)
from qcmc_logic.customs.sales_order import (
    _get_so_type_province_requirement,
    get_so_type_warehouse_query,
    validate_so_type_warehouses,
)


class TestSalesOrderWarehouseFlow(TestCase):
    def _sales_order(self, so_type, warehouses):
        return frappe._dict(
            doctype="Sales Order",
            custom_so_type=so_type,
            set_warehouse=warehouses[0] if warehouses else None,
            items=[frappe._dict(warehouse=value) for value in warehouses[1:]],
        )

    def test_so_type_normalization(self):
        self.assertEqual(_get_so_type_province_requirement("LOCAL"), 1)
        self.assertEqual(_get_so_type_province_requirement("FOB"), 0)
        self.assertEqual(_get_so_type_province_requirement("FOB Direct"), 0)
        self.assertEqual(_get_so_type_province_requirement("FOB-DIRECT"), 0)
        self.assertIsNone(_get_so_type_province_requirement("REGULAR"))

    def test_local_rejects_non_provincial_warehouse(self):
        doc = self._sales_order("LOCAL", ["FG - MC1"])
        rows = [frappe._dict(name="FG - MC1", custom_is_province=0)]
        with patch("qcmc_logic.customs.sales_order.frappe.get_all", return_value=rows):
            with self.assertRaises(frappe.ValidationError):
                validate_so_type_warehouses(doc)

    def test_fob_rejects_provincial_item_warehouse(self):
        doc = self._sales_order("FOB", ["FG - MC1", "FG - La Union - MC"])
        rows = [
            frappe._dict(name="FG - MC1", custom_is_province=0),
            frappe._dict(name="FG - La Union - MC", custom_is_province=1),
        ]
        with patch("qcmc_logic.customs.sales_order.frappe.get_all", return_value=rows):
            with self.assertRaises(frappe.ValidationError):
                validate_so_type_warehouses(doc)

    def test_warehouse_query_intersects_user_access_and_so_type(self):
        with (
            patch(
                "qcmc_logic.customs.sales_order.get_user_allowed_warehouses",
                return_value=["FG - MC1", "FG - La Union - MC"],
            ),
            patch("qcmc_logic.customs.sales_order.frappe.db.sql", return_value=[]) as sql,
        ):
            get_so_type_warehouse_query(
                "Warehouse",
                "FG",
                "name",
                0,
                20,
                {"user": "myra@example.com", "custom_so_type": "LOCAL"},
            )

        query, values = sql.call_args.args
        self.assertIn("w.name in %(allowed_warehouses)s", query)
        self.assertIn("ifnull(w.custom_is_province, 0) = %(province_required)s", query)
        self.assertEqual(values["province_required"], 1)

    def test_work_order_selector_returns_all_submitted_company_orders(self):
        with (
            patch(
                "qcmc_logic.customs.manufacturing_warehouse_access.frappe.has_permission",
                side_effect=[True],
            ),
            patch(
                "qcmc_logic.customs.manufacturing_warehouse_access.frappe.db.sql",
                return_value=[],
            ) as sql,
        ):
            sales_order_reference_query(
                "Sales Order",
                "SO-",
                "name",
                0,
                20,
                {"company": "MC"},
            )

        query, values = sql.call_args.args
        self.assertIn("so.docstatus = 1", query)
        self.assertIn("so.company = %(company)s", query)
        self.assertNotIn("territory", query.lower())
        self.assertNotIn("warehouse", query.lower())
        self.assertEqual(values["company"], "MC")

    def test_work_order_selector_requires_work_order_permission(self):
        with patch(
            "qcmc_logic.customs.manufacturing_warehouse_access.frappe.has_permission",
            side_effect=[False, False],
        ):
            with self.assertRaises(frappe.PermissionError):
                sales_order_reference_query(
                    "Sales Order", "", "name", 0, 20, {"company": "MC"}
                )
