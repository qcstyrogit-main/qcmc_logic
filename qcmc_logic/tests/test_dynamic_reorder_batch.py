"""Pure and mocked tests for compact batch processing; no site writes."""
import unittest
from unittest.mock import MagicMock,patch
import frappe
from qcmc_logic import dynamic_reorder_batch as b

class TestBatch(unittest.TestCase):
    def row(self,**changes):
        return dict(dict(status="Preview",production_mode="Make to Stock",reorder_row="R",
            previous_level=10,previous_qty=20,reorder_level=10,reorder_qty=20),**changes)

    def test_storage_number_handles_missing_values(self):
        self.assertEqual(b.storage_number(None),0)
        self.assertEqual(b.storage_number(12.5),12.5)
        self.assertEqual(b.storage_number(0),0)

    def test_unchanged(self):
        self.assertEqual(b.classify(self.row()),"Unchanged")

    def test_unchanged_adopted_row_requires_first_approval(self):
        self.assertEqual(b.classify(self.row(requires_initial_approval=True)), "Pending Approval")
        self.assertEqual(b.classify(self.row(requires_initial_approval=False)), "Unchanged")
        self.assertEqual(b.classify(self.row(requires_initial_approval=True, status="Skipped")), "Skipped")

    def test_changed_qty_only(self):
        self.assertEqual(b.classify(self.row(reorder_qty=21)),"Pending Approval")

    def test_new_configuration(self):
        self.assertEqual(b.classify(self.row(reorder_row=None)),"New Configuration")

    def test_failed_and_skipped_preserved(self):
        for status in ("Failed","Skipped"):
            self.assertEqual(b.classify(self.row(status=status)),status)

    def test_missing_values_fail_closed(self):
        self.assertEqual(b.classify(self.row(reorder_level=None)),"Review Required")

    def test_conflicting_legacy_row_blocks_approval(self):
        self.assertEqual(b.classify(self.row(legacy_reorder_rows=["OLD"])),"Review Required")

    def test_mto_not_approved(self):
        self.assertEqual(b.classify(self.row(production_mode="Make to Order")),"Make to Order")

    def test_pagination_is_bounded_and_scoped(self):
        with patch.object(frappe,"session",frappe._dict(user="Administrator")),patch.object(frappe,"get_doc",return_value=frappe._dict(status="Completed")),patch.object(frappe,"get_all",return_value=[]) as query,patch.object(frappe,"db",MagicMock()) as db:
            db.count.return_value=0
            b.page("B",offset=-10,limit=10000,status="Failed",search="ABC")
            args=query.call_args.kwargs
            self.assertEqual(args["limit_start"],0)
            self.assertEqual(args["limit_page_length"],100)
            self.assertEqual(args["filters"],dict(batch="B",status="Failed",item_code=["like","%ABC%"]))

    def test_summary_after_rollback(self):
        with patch.object(frappe,"db",MagicMock()) as db:
            db.count.side_effect=[0,2,1]
            b.refresh_counts("B")
            self.assertEqual(db.set_value.call_args.args,(b.BATCH,"B",dict(pending_items=0,approved_items=2,reverted_items=1,status="Completed")))
