"""Focused tests for the Sales-owned endorsement transition."""
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch
import frappe
from qcmc_logic.api import delivery_sales_planning as planning
from qcmc_logic.api import delivery_schedule_collaboration_v2 as collaboration


class TestSalesPlanning(TestCase):
    def test_unendorsed_rows_cannot_enter_collaboration(self):
        for status in ("For Planning", "Returned", None):
            with self.subTest(status=status), patch.object(planning, "_", side_effect=lambda value: value), patch.object(frappe, "throw", side_effect=frappe.ValidationError):
                with self.assertRaises(frappe.ValidationError):
                    planning.require_endorsed(frappe._dict(endorsement_status=status))
        planning.require_endorsed(frappe._dict(endorsement_status="Endorsed"))

    def test_original_commitment_conservation_guard(self):
        item = frappe._dict(name="SOI")
        state = {"schedules": [frappe._dict(history_status="Verified", original_qty=100)],
                 "planned_qty": Decimal(100), "ordered_qty": Decimal(100)}
        with patch.object(planning, "_unlinked_dn_exists", return_value=False), patch.object(planning, "_", side_effect=lambda value: value):
            self.assertEqual(planning._history_block(item, state), "")
            state["planned_qty"] = Decimal(90)
            self.assertTrue(planning._history_block(item, state))
            state["planned_qty"] = Decimal(100)
            state["schedules"][0].history_status = "Unreconciled"
            self.assertTrue(planning._history_block(item, state))

    def test_return_clears_approval_without_changing_original_promise(self):
        class Row(dict):
            __getattr__ = dict.get
            def __setattr__(self, key, value):
                self[key] = value
            def set(self, key, value):
                self[key] = value
            def add_comment(self, *args):
                pass
        row = Row(endorsement_status="Endorsed", original_qty=10000, current_total=10000,
                  original_promise_date="2026-11-24", final_qty=10000,
                  logistics_confirmed_by="warehouse", sales_confirmed_by="sales",
                  sales_remarks="Call first", confirmation_status="Finalized")
        with patch.object(collaboration, "_save"), patch.object(planning, "now_datetime", return_value="2026-11-25 10:00:00"), patch.object(frappe, "session", frappe._dict(user="warehouse")), patch.object(planning, "_", side_effect=lambda value: value):
            planning.mark_returned(row, "No stock", "SA", "No stock")
        self.assertEqual(row.endorsement_status, "Returned")
        self.assertEqual(row.return_reason, "No stock")
        self.assertEqual(row.logistics_reason, "SA")
        self.assertIsNone(row.final_qty)
        self.assertIsNone(row.logistics_confirmed_by)
        self.assertIsNone(row.sales_confirmed_by)
        self.assertEqual(row.current_total, 10000)
        self.assertEqual(row.original_qty, 10000)
        self.assertEqual(row.original_promise_date, "2026-11-24")
        self.assertEqual(row.sales_remarks, "Call first")

    def test_duplicate_batch_rows_are_rejected_before_writes(self):
        with patch.object(collaboration, "_require_role"), patch.object(planning, "_", side_effect=lambda value: value), patch.object(frappe, "throw", side_effect=frappe.ValidationError), patch.object(planning, "_plan") as plan:
            with self.assertRaises(frappe.ValidationError):
                planning.save_rows([{"schedule": "S1"}, {"schedule": "S1"}], True)
        plan.assert_not_called()
