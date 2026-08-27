from unittest import TestCase
from unittest.mock import patch

from frappe import _dict

from qcmc_logic.api.work_order_job_card import create_next_job_card


class TestCreateNextJobCard(TestCase):
	def setUp(self):
		self.operation = _dict(
			name="WO-OP-1",
			operation="REPACKING",
			sequence_id=1,
			idx=1,
		)
		self.work_order = _dict(
			name="WO-TEST",
			docstatus=1,
			status="In Process",
			qty=50000,
			produced_qty=25000,
			operations=[self.operation],
		)

	@patch("qcmc_logic.api.work_order_job_card.user_can_transact_work_order", return_value=True)
	@patch("qcmc_logic.api.work_order_job_card.create_job_card")
	@patch("qcmc_logic.api.work_order_job_card.frappe")
	def test_creates_card_for_actual_remaining_quantity(self, frappe, create, _permission):
		frappe.db.exists.return_value = True
		frappe.get_doc.return_value = self.work_order
		frappe.db.get_value.return_value = None
		create.return_value = _dict(name="JC-NEXT")

		result = create_next_job_card("WO-TEST")

		self.assertEqual(result["remaining_qty"], 25000)
		self.assertTrue(result["created"])
		self.assertEqual(create.call_args.args[1].job_card_qty, 25000)

	@patch("qcmc_logic.api.work_order_job_card.user_can_transact_work_order", return_value=True)
	@patch("qcmc_logic.api.work_order_job_card.create_job_card")
	@patch("qcmc_logic.api.work_order_job_card.frappe")
	def test_reuses_existing_open_card(self, frappe, create, _permission):
		frappe.db.exists.return_value = True
		frappe.get_doc.return_value = self.work_order
		frappe.db.get_value.return_value = "JC-OPEN"

		result = create_next_job_card("WO-TEST")

		self.assertEqual(result["job_card"], "JC-OPEN")
		self.assertFalse(result["created"])
		create.assert_not_called()
