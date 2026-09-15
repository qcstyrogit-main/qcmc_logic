from inspect import unwrap
from unittest import TestCase
from unittest.mock import patch

import frappe

from qcmc_logic.customs.warehouse_transfer_events import validate_transfer_type_rules
from qcmc_logic.utils import (
    _get_transfer_type_for_warehouses,
    _is_same_location_provincial_transfer,
    get_target_warehouse_query,
)


WAREHOUSES = {
    "FG - Laguna - QC": frappe._dict(
        company="QC", warehouse_type="Finished Goods",
        custom_is_province=1, custom_location="Laguna",
    ),
    "FG - Laguna - MC": frappe._dict(
        company="MC", warehouse_type="Finished Goods",
        custom_is_province=1, custom_location="Laguna",
    ),
    "FG - Cebu - MC": frappe._dict(
        company="MC", warehouse_type="Finished Goods",
        custom_is_province=1, custom_location="Cebu",
    ),
}


def warehouse_values(warehouse, fields):
    values = WAREHOUSES[warehouse]
    return frappe._dict({field: values.get(field) for field in fields})


class TestWarehouseTransferProvince(TestCase):
    @patch("qcmc_logic.utils._get_warehouse_values", side_effect=warehouse_values)
    def test_provincial_warehouses_with_same_location_are_allowed(self, _values):
        self.assertTrue(
            _is_same_location_provincial_transfer(
                "FG - Laguna - QC", "FG - Laguna - MC"
            )
        )

    @patch("qcmc_logic.utils._get_warehouse_values", side_effect=warehouse_values)
    def test_provincial_warehouses_with_different_locations_are_rejected(self, _values):
        self.assertFalse(
            _is_same_location_provincial_transfer(
                "FG - Laguna - QC", "FG - Cebu - MC"
            )
        )

    @patch("qcmc_logic.utils._get_warehouse_values", side_effect=warehouse_values)
    def test_cross_company_provincial_pair_is_intercompany(self, _values):
        self.assertEqual(
            _get_transfer_type_for_warehouses(
                "FG - Laguna - QC", "FG - Laguna - MC"
            ),
            "Intercompany Warehouse Transfer",
        )

    @patch("qcmc_logic.utils.frappe.db.sql", return_value=[])
    @patch("qcmc_logic.utils._get_warehouse_values", side_effect=warehouse_values)
    def test_target_query_filters_province_by_source_location(self, _values, sql):
        unwrap(get_target_warehouse_query)(
            "Warehouse", "Laguna", "name", 0, 20,
            {
                "source_warehouse": "FG - Laguna - QC",
                "transfer_type": "Intercompany Warehouse Transfer",
            },
        )

        query, values = next(
            call.args for call in sql.call_args_list if "from `tabWarehouse` w" in call.args[0]
        )
        self.assertIn("ifnull(w.custom_is_province, 0) = 1", query)
        self.assertIn("w.custom_location = %(source_location)s", query)
        self.assertEqual(values["source_location"], "Laguna")

    @patch("qcmc_logic.customs.warehouse_transfer_events.validate_pick_list_references")
    @patch("qcmc_logic.customs.warehouse_transfer_events._validate_material_request_references")
    @patch("qcmc_logic.customs.warehouse_transfer_events._validate_source_warehouse_access")
    @patch("qcmc_logic.customs.warehouse_transfer_events._set_company_fields")
    @patch("qcmc_logic.customs.warehouse_transfer_events.frappe.db.get_value")
    @patch(
        "qcmc_logic.customs.warehouse_transfer_events._is_same_location_provincial_transfer",
        return_value=True,
    )
    @patch(
        "qcmc_logic.customs.warehouse_transfer_events._get_warehouse_is_province",
        return_value=1,
    )
    def test_server_validation_accepts_same_location_provincial_transfer(
        self, _province, _same_location, get_value, _set_companies,
        _source_access, _material_requests, _pick_lists,
    ):
        get_value.side_effect = ["Finished Goods", "Finished Goods"]
        doc = frappe._dict(
            transfer_type="Intercompany Warehouse Transfer",
            source_warehouse="FG - Laguna - QC",
            target_warehouse="FG - Laguna - MC",
            source_company="QC",
            target_company="MC",
        )

        validate_transfer_type_rules(doc)
