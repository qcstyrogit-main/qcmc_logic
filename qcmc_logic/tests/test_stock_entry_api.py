from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from frappe import _dict

from qcmc_logic.api.stock_entry import (
    _get_final_operation,
    _get_latest_actual_time_log,
    _get_unauthorized_pending_material_items,
    _is_final_operation_job_card,
    _pending_qty,
    _validate_pending_material_inventory_group_access,
    _validate_final_operation_job_card,
    get_fabricated_msjrs_for_stock_entry,
    make_material_receipt_from_fabricated_msjr,
)


def operation(name, operation_name, sequence_id, idx):
    return _dict(
        name=name,
        operation=operation_name,
        sequence_id=sequence_id,
        idx=idx,
    )


def work_order(*operations):
    return _dict(name="WO-TEST", operations=list(operations))


class TestFinalOperationJobCard(TestCase):
    def test_single_operation_is_allowed(self):
        injection = operation("WO-OP-1", "INJECTION", 1, 1)
        wo = work_order(injection)
        job_card = SimpleNamespace(operation_id=injection.name)

        self.assertTrue(_is_final_operation_job_card(job_card, wo))

    def test_only_highest_sequence_is_allowed(self):
        injection = operation("WO-OP-1", "INJECTION", 1, 1)
        drying = operation("WO-OP-2", "DRYING", 2, 2)
        packing = operation("WO-OP-3", "PACKING", 3, 3)
        wo = work_order(injection, drying, packing)

        self.assertEqual(_get_final_operation(wo).name, packing.name)
        self.assertFalse(
            _is_final_operation_job_card(
                SimpleNamespace(operation_id=injection.name),
                wo,
            )
        )
        self.assertFalse(
            _is_final_operation_job_card(
                SimpleNamespace(operation_id=drying.name),
                wo,
            )
        )
        self.assertTrue(
            _is_final_operation_job_card(
                SimpleNamespace(operation_id=packing.name),
                wo,
            )
        )

    def test_row_order_breaks_equal_sequence_ties(self):
        injection = operation("WO-OP-1", "INJECTION", 1, 1)
        drying = operation("WO-OP-2", "DRYING", 1, 2)
        packing = operation("WO-OP-3", "PACKING", 1, 3)
        wo = work_order(injection, drying, packing)

        self.assertEqual(_get_final_operation(wo).name, packing.name)

    def test_work_order_without_operations_does_not_restrict_job_card(self):
        wo = work_order()
        job_card = SimpleNamespace(operation_id=None)

        self.assertIsNone(_get_final_operation(wo))
        self.assertTrue(_is_final_operation_job_card(job_card, wo))

    def test_server_validation_rejects_non_final_operation(self):
        injection = operation("WO-OP-1", "INJECTION", 1, 1)
        packing = operation("WO-OP-2", "PACKING", 2, 2)
        wo = work_order(injection, packing)
        job_card = SimpleNamespace(operation_id=injection.name)

        with (
            patch("qcmc_logic.api.stock_entry._", side_effect=lambda message: message),
            patch(
                "qcmc_logic.api.stock_entry.frappe.throw",
                side_effect=RuntimeError,
            ) as throw,
        ):
            with self.assertRaises(RuntimeError):
                _validate_final_operation_job_card(job_card, wo)

        self.assertIn("final operation", throw.call_args.args[0])

    def test_latest_actual_time_row_is_selected(self):
        job_card = _dict(
            name="JC-TEST",
            time_logs=[
                _dict(name="TIME-1", idx=1),
                _dict(name="TIME-3", idx=3),
                _dict(name="TIME-2", idx=2),
            ],
        )

        self.assertEqual(_get_latest_actual_time_log(job_card).name, "TIME-3")


class TestManufacturePendingQty(TestCase):
    def test_manufacture_pending_qty_uses_completed_output(self):
        job_card = _dict(
            work_order="WO-TEST",
            finished_good=None,
            for_quantity=103000,
            total_completed_qty=8800,
            manufactured_qty=0,
            transferred_qty=103000,
        )

        with patch("qcmc_logic.api.stock_entry.frappe") as frappe:
            frappe.db.get_value.return_value = _dict(qty=203000, produced_qty=0)

            self.assertEqual(_pending_qty(job_card, "Manufacture"), 8800)

    def test_manufacture_pending_qty_subtracts_already_manufactured_output(self):
        job_card = _dict(
            work_order="WO-TEST",
            finished_good=None,
            for_quantity=103000,
            total_completed_qty=8800,
            manufactured_qty=3000,
            transferred_qty=103000,
        )

        with patch("qcmc_logic.api.stock_entry.frappe") as frappe:
            frappe.db.get_value.return_value = _dict(qty=203000, produced_qty=3000)

            self.assertEqual(_pending_qty(job_card, "Manufacture"), 5800)

    def test_manufacture_pending_qty_is_capped_by_work_order_remaining_qty(self):
        job_card = _dict(
            work_order="WO-TEST",
            finished_good=None,
            for_quantity=103000,
            total_completed_qty=8800,
            manufactured_qty=0,
            transferred_qty=103000,
        )

        with patch("qcmc_logic.api.stock_entry.frappe") as frappe:
            frappe.db.get_value.return_value = _dict(qty=203000, produced_qty=200000)

            self.assertEqual(_pending_qty(job_card, "Manufacture"), 3000)


class TestFabricatedMSJRSelector(TestCase):
    def test_lists_only_parts_with_remaining_output(self):
        request = _dict(
            name="MSJR-1",
            request="REQ-PARTS",
            item_code="ITEM-1",
            asset=None,
            asset_name="Fabricated Part",
            quantity_produced=10,
            company="Test Company",
            document_date="2026-08-06",
        )
        with patch("qcmc_logic.api.stock_entry.frappe") as frappe:
            frappe.session.user = "stockroom@example.com"
            frappe.get_roles.return_value = ["Stockroom_PR_EDSA_lv1"]
            frappe.get_list.return_value = [request]
            frappe.db.get_value.return_value = "PARTS FABRICATION"
            frappe.db.sql.return_value = [(4,)]

            rows = get_fabricated_msjrs_for_stock_entry()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "MSJR-1")
        self.assertEqual(rows[0]["remaining_qty"], 6)

    def test_excludes_fully_received_output(self):
        request = _dict(
            name="MSJR-1", request="REQ-PARTS", item_code="ITEM-1",
            asset=None, asset_name="", quantity_produced=10,
            company="Test Company", document_date="2026-08-06",
        )
        with patch("qcmc_logic.api.stock_entry.frappe") as frappe:
            frappe.session.user = "stockroom@example.com"
            frappe.get_roles.return_value = ["Stockroom_PR_EDSA_lv1"]
            frappe.get_list.return_value = [request]
            frappe.db.get_value.return_value = "PARTS FABRICATION"
            frappe.db.sql.return_value = [(10,)]

            self.assertEqual(get_fabricated_msjrs_for_stock_entry(), [])

    def test_receipt_creation_reuses_canonical_msjr_mapper(self):
        mapped = _dict(doctype="Stock Entry", purpose="Material Receipt")
        with patch(
            "qcmc_logic.utils.make_completed_output_stock_entry",
            return_value=_dict(as_dict=lambda: mapped),
        ) as mapper, patch("qcmc_logic.api.stock_entry.frappe") as frappe:
            frappe.session.user = "stockroom@example.com"
            frappe.get_roles.return_value = ["Stockroom_PR_EDSA_lv1"]
            result = make_material_receipt_from_fabricated_msjr("MSJR-1")

        mapper.assert_called_once_with("MSJR-1")
        self.assertEqual(result, mapped)

    def test_rejects_user_without_stockroom_role(self):
        with (
            patch("qcmc_logic.api.stock_entry.frappe") as frappe,
            patch("qcmc_logic.api.stock_entry._", side_effect=lambda message: message),
        ):
            frappe.session.user = "other@example.com"
            frappe.get_roles.return_value = ["Stock User"]
            frappe.bold.side_effect = lambda value: value
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                get_fabricated_msjrs_for_stock_entry()

        self.assertIn("Stockroom_PR_EDSA_lv1", frappe.throw.call_args.args[0])
