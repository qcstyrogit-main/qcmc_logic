from unittest import TestCase

from frappe import _dict

from qcmc_logic.customs.bom_soph import apply_bom_soph_and_operation_time


class TestBOMSOPH(TestCase):
	def test_packing_operation_uses_machine_soph_when_pack_soph_is_blank(self):
		doc = _dict(
			doctype="BOM",
			quantity=1000,
			custom_number_of_cavity=1,
			custom_rate_per_minute=250,
			custom_pack_soph=0,
			operations=[_dict(operation="REPACKING", time_in_mins=0)],
		)

		apply_bom_soph_and_operation_time(doc)

		self.assertEqual(doc.custom_soph, 15000)
		self.assertEqual(doc.operations[0].time_in_mins, 4)

	def test_packing_operation_prefers_pack_soph_when_set(self):
		doc = _dict(
			doctype="BOM",
			quantity=1000,
			custom_number_of_cavity=1,
			custom_rate_per_minute=250,
			custom_pack_soph=3000,
			operations=[_dict(operation="PACKING", time_in_mins=0)],
		)

		apply_bom_soph_and_operation_time(doc)

		self.assertEqual(doc.operations[0].time_in_mins, 20)
