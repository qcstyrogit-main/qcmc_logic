import json
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe

from qcmc_logic.customs import warehouse_transfer_events as wt_events


class _Meta:
    def __init__(self, fields):
        self.fields = set(fields)

    def has_field(self, fieldname):
        return fieldname in self.fields


class _SLE(frappe._dict):
    def __init__(self, **kwargs):
        fields = kwargs.pop("_fields", ())
        super().__init__(kwargs)
        self.meta = _Meta(fields)


class TestWarehouseTransferCancellation(unittest.TestCase):
    def doc(self, name="WT-TEST-0001", transfer_status="Transferred"):
        return frappe._dict(
            doctype="Warehouse Transfer",
            name=name,
            transfer_status=transfer_status,
            transfer_items=[
                frappe._dict(name="WT-DETAIL-1", item_code="ITEM-1", issued_qty=5, received_qty=0),
                frappe._dict(name="WT-DETAIL-2", item_code="ITEM-1", issued_qty=0, received_qty=5),
            ],
        )

    @patch("qcmc_logic.customs.warehouse_transfer_events.make_reverse_gl_entries")
    @patch("qcmc_logic.customs.warehouse_transfer_events.frappe.db.exists")
    def test_gl_reversal_uses_installed_named_api(self, exists, make_reverse):
        exists.return_value = "GLE-1"

        wt_events._reverse_warehouse_transfer_gl(self.doc())

        make_reverse.assert_called_once_with(
            voucher_type="Warehouse Transfer",
            voucher_no="WT-TEST-0001",
            update_outstanding="No",
        )

    @patch("qcmc_logic.customs.warehouse_transfer_events._stock_ledger_location_is_storage_location", return_value=True)
    @patch("qcmc_logic.customs.warehouse_transfer_events.nowtime", return_value="10:00:00")
    @patch("qcmc_logic.customs.warehouse_transfer_events.nowdate", return_value="2026-09-22")
    @patch("qcmc_logic.customs.warehouse_transfer_events.make_sl_entries")
    @patch("qcmc_logic.customs.warehouse_transfer_events.frappe.get_doc")
    @patch("qcmc_logic.customs.warehouse_transfer_events.frappe.get_all")
    def test_stock_reversal_uses_original_quantities_child_rows_and_single_cancel(
        self, get_all, get_doc, make_sl_entries, _nowdate, _nowtime, _location_field
    ):
        get_all.return_value = [{"name": "SLE-OUT"}, {"name": "SLE-IN"}]
        sles = {
            "SLE-OUT": _SLE(
                name="SLE-OUT",
                item_code="ITEM-1",
                warehouse="WH-A",
                voucher_detail_no="SLE-OUT",
                actual_qty=-5,
                company="QC",
                stock_uom="PCS",
                incoming_rate=0,
                outgoing_rate=12,
                valuation_rate=12,
                stock_value_difference=-60,
                location="LOC-A",
                _fields=("location",),
            ),
            "SLE-IN": _SLE(
                name="SLE-IN",
                item_code="ITEM-1",
                warehouse="WH-B",
                voucher_detail_no="SLE-IN",
                actual_qty=5,
                company="QC",
                stock_uom="PCS",
                incoming_rate=12,
                outgoing_rate=0,
                valuation_rate=12,
                stock_value_difference=60,
                location="LOC-B",
                _fields=("location",),
            ),
        }
        get_doc.side_effect = lambda _doctype, name: sles[name]

        wt_events._reverse_warehouse_transfer_stock(self.doc())

        make_sl_entries.assert_called_once()
        sl_entries, kwargs = make_sl_entries.call_args.args[0], make_sl_entries.call_args.kwargs
        self.assertEqual(kwargs, {"allow_negative_stock": True})
        self.assertEqual([row.actual_qty for row in sl_entries], [-5, 5])
        self.assertEqual([row.voucher_detail_no for row in sl_entries], ["WT-DETAIL-1", "WT-DETAIL-2"])
        self.assertTrue(all(row.is_cancelled for row in sl_entries))

    @patch("qcmc_logic.customs.warehouse_transfer_events.frappe.db.set_value")
    def test_cancel_status_is_displayed_without_touching_amended_from(self, set_value):
        doc = self.doc()

        wt_events._set_cancelled_transfer_status(doc)

        self.assertEqual(doc.transfer_status, "Cancelled")
        set_value.assert_called_once_with(
            "Warehouse Transfer",
            "WT-TEST-0001",
            "transfer_status",
            "Cancelled",
            update_modified=False,
        )

    @patch("qcmc_logic.customs.warehouse_transfer_events.update_pick_list_progress")
    @patch("qcmc_logic.customs.warehouse_transfer_events.update_material_request_progress")
    @patch("qcmc_logic.customs.warehouse_transfer_events._set_cancelled_transfer_status")
    @patch("qcmc_logic.customs.warehouse_transfer_events._reverse_warehouse_transfer_stock")
    @patch("qcmc_logic.customs.warehouse_transfer_events._reverse_warehouse_transfer_gl")
    @patch("qcmc_logic.customs.warehouse_transfer_events.frappe.log_error")
    @patch("qcmc_logic.customs.warehouse_transfer_events.frappe.db.rollback")
    @patch("qcmc_logic.customs.warehouse_transfer_events.frappe.db.savepoint")
    @patch("qcmc_logic.customs.warehouse_transfer_events.frappe.db.exists", return_value=False)
    def test_failure_rolls_back_and_re_raises(
        self, _exists, savepoint, rollback, log_error, reverse_gl, reverse_stock,
        set_status, update_mr, update_pick_list,
    ):
        reverse_stock.side_effect = RuntimeError("stock reversal failed")

        with self.assertRaises(RuntimeError):
            wt_events.on_cancel(self.doc(), None)

        savepoint.assert_called_once_with("warehouse_transfer_cancel")
        rollback.assert_called_once_with(save_point="warehouse_transfer_cancel")
        log_error.assert_called_once()
        set_status.assert_not_called()
        update_mr.assert_not_called()
        update_pick_list.assert_not_called()
        reverse_gl.assert_called_once()

    @patch("qcmc_logic.customs.warehouse_transfer_events.update_pick_list_progress")
    @patch("qcmc_logic.customs.warehouse_transfer_events.update_material_request_progress")
    @patch("qcmc_logic.customs.warehouse_transfer_events._set_cancelled_transfer_status")
    @patch("qcmc_logic.customs.warehouse_transfer_events.make_sl_entries")
    @patch("qcmc_logic.customs.warehouse_transfer_events.make_reverse_gl_entries")
    @patch("qcmc_logic.customs.warehouse_transfer_events.frappe.get_all", return_value=[])
    @patch("qcmc_logic.customs.warehouse_transfer_events.frappe.db.rollback")
    @patch("qcmc_logic.customs.warehouse_transfer_events.frappe.db.savepoint")
    @patch("qcmc_logic.customs.warehouse_transfer_events.frappe.db.exists", return_value=False)
    def test_repeated_cancellation_is_idempotent_for_ledgers(
        self, _exists, _savepoint, rollback, _get_all, make_reverse,
        make_sl_entries, _set_status, _update_mr, _update_pick_list,
    ):
        wt_events.on_cancel(self.doc(transfer_status="Cancelled"), None)

        make_reverse.assert_not_called()
        make_sl_entries.assert_not_called()
        rollback.assert_not_called()

    def test_workflow_cancelled_state_updates_transfer_status_and_preserves_amendments(self):
        workflow_path = Path(__file__).parents[1] / "fixtures" / "workflow.json"
        workflows = json.loads(workflow_path.read_text())
        workflow = next(row for row in workflows if row.get("name") == "WF_WarehouseTransfer")
        cancelled_state = next(row for row in workflow["states"] if row.get("state") == "Cancelled")

        self.assertEqual(workflow["workflow_state_field"], "transfer_status")
        self.assertEqual(cancelled_state["update_field"], "transfer_status")
        self.assertEqual(cancelled_state["update_value"], "Cancelled")
        self.assertNotEqual(cancelled_state["update_field"], "amended_from")

    @patch("qcmc_logic.customs.warehouse_transfer_events.create_intercompany_gl")
    @patch("qcmc_logic.customs.warehouse_transfer_events.update_pick_list_progress")
    @patch("qcmc_logic.customs.warehouse_transfer_events.update_material_request_progress")
    @patch("qcmc_logic.customs.warehouse_transfer_events.create_target_stock_entry")
    @patch("qcmc_logic.customs.warehouse_transfer_events.create_source_stock_entry")
    @patch("qcmc_logic.customs.warehouse_transfer_events.validate_update_after_submit")
    @patch("qcmc_logic.customs.warehouse_transfer_events.frappe.db.set_value")
    @patch("qcmc_logic.customs.warehouse_transfer_events.nowdate", return_value="2026-09-24")
    def test_receiving_sets_date_received_before_receive_side_posting(
        self, _nowdate, set_value, _validate, create_source, create_target,
        update_mr, update_pick_list, create_gl,
    ):
        previous = frappe._dict(transfer_status="Transferred")
        doc = frappe._dict(
            doctype="Warehouse Transfer",
            name="WT-TEST-0002",
            transfer_status="Received",
            date_received=None,
            source_company="QC",
            target_company="MC",
        )
        doc.get_doc_before_save = lambda: previous
        calls = []
        create_target.side_effect = lambda _name: calls.append(("target", doc.date_received))
        create_gl.side_effect = lambda _name, source: calls.append(("gl", doc.date_received, source))

        wt_events.on_update_after_submit(doc, None)

        self.assertEqual(doc.date_received, "2026-09-24")
        set_value.assert_called_once_with(
            "Warehouse Transfer",
            "WT-TEST-0002",
            "date_received",
            "2026-09-24",
            update_modified=False,
        )
        create_source.assert_called_once_with("WT-TEST-0002")
        update_mr.assert_called_once_with("WT-TEST-0002")
        update_pick_list.assert_called_once_with("WT-TEST-0002")
        self.assertEqual(calls, [("target", "2026-09-24"), ("gl", "2026-09-24", False)])
