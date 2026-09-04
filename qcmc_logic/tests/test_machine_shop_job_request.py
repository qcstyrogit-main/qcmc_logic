from unittest import TestCase
from unittest.mock import MagicMock, patch

from frappe import _dict

from qcmc_logic.customs.machine_shop_job_request import (
    _validate_completion_output,
    _validate_linked_project_completed,
    _validate_output_item,
    _validate_fabrication_request_quantities,
    _validate_quantity_produced_permission,
    _normalize_non_fabrication_quantity_produced,
)
from qcmc_logic.utils import make_completed_output_stock_entry


def output_doc(**values):
    defaults = {
        "request": "REQ-PARTS",
        "item_code": None,
        "quantity_produced": 1,
        "quantity_request": 1,
        "not_in_master_file": 0,
        "proposed_output_code": None,
        "output_description": None,
    }
    defaults.update(values)
    return _dict(defaults)


class TestMachineShopCompletionValidation(TestCase):
    def test_non_fabrication_quantity_produced_is_normalized_to_zero(self):
        doc = output_doc(request="REQ-REPAIR", quantity_produced=5)
        _normalize_non_fabrication_quantity_produced(doc, "REPAIR OF MACHINE")
        self.assertEqual(doc.quantity_produced, 0)

    def test_non_fabrication_completion_does_not_require_quantity_produced(self):
        doc = output_doc(request="REQ-REPAIR", item_code="MACHINE-1", quantity_produced=0)
        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.db.get_value.return_value = "REPAIR OF MACHINE"
            _validate_completion_output(doc)

        frappe.throw.assert_not_called()

    def test_machine_shop_foreman_can_change_quantity_produced(self):
        doc = output_doc(name="MSJR-1", quantity_produced=3)
        doc.is_new = lambda: False
        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.session.user = "foreman@example.com"
            frappe.db.get_value.return_value = 1
            frappe.get_roles.return_value = ["Machine Shop Foreman"]
            _validate_quantity_produced_permission(doc, "FABRICATION - ITEM")

        frappe.throw.assert_not_called()

    def test_unauthorized_role_cannot_change_quantity_produced(self):
        doc = output_doc(name="MSJR-1", quantity_produced=3)
        doc.is_new = lambda: False
        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.session.user = "other@example.com"
            frappe.db.get_value.return_value = 1
            frappe.get_roles.return_value = ["Stock User"]
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_quantity_produced_permission(doc, "FABRICATION - ITEM")

        self.assertIn("modify Quantity Produced", frappe.throw.call_args.args[0])

    def test_item_fabrication_can_be_created_without_item_code(self):
        doc = output_doc(item_code=None, quantity_request=2)
        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.db.get_value.return_value = "FABRICATION - ITEM"
            _validate_fabrication_request_quantities(doc)
            _validate_output_item(doc)

        frappe.throw.assert_not_called()

    def test_item_fabrication_requires_request_quantity(self):
        doc = output_doc(quantity_request=0)
        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.db.get_value.return_value = "FABRICATION - MACHINE PART"
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_fabrication_request_quantities(doc)

        self.assertIn("Quantity Request", frappe.throw.call_args.args[0])

    def test_mould_fabrication_can_be_created_without_item(self):
        doc = output_doc(request="REQ-MOULD", item_code=None)
        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.db.get_value.return_value = "FABRICATION - MOULD"
            _validate_fabrication_request_quantities(doc)

        frappe.throw.assert_not_called()

    def test_new_item_fabrication_requires_item_only_at_completion(self):
        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.db.get_value.return_value = "FABRICATION - ITEM"
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_completion_output(output_doc(item_code=None))

        self.assertIn("Item Code is required", frappe.throw.call_args.args[0])

    def test_new_mould_fabrication_requires_item_only_at_completion(self):
        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.db.get_value.return_value = "FABRICATION - MOULD"
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_completion_output(output_doc(request="REQ-MOULD", item_code=None))

        self.assertIn("Item Code is required", frappe.throw.call_args.args[0])

    def _request_and_item_value(self, doctype, name, fieldname):
        if doctype == "Machine Shop Request Code":
            return "PARTS FABRICATION"
        if doctype == "Item":
            return "CMMS"
        return None

    def test_parts_fabrication_requires_item_code(self):
        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.db.get_value.side_effect = self._request_and_item_value
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_completion_output(output_doc())

        self.assertIn("Item Code is required", frappe.throw.call_args.args[0])

    def test_non_parts_request_requires_item(self):
        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.db.get_value.return_value = "REPAIR OF MACHINE"
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_completion_output(output_doc(request="REQ-REPAIR"))

        self.assertIn("Item Code is required", frappe.throw.call_args.args[0])

    def test_missing_master_accepts_proposed_code(self):
        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.db.get_value.return_value = "PARTS FABRICATION"
            _validate_completion_output(
                output_doc(
                    quantity_produced=2,
                    not_in_master_file=1,
                    proposed_output_code="PROPOSED-001",
                )
            )

        frappe.throw.assert_not_called()

    def test_quantity_produced_must_be_positive(self):
        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.db.get_value.return_value = "PARTS FABRICATION"
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_completion_output(output_doc(quantity_produced=0))

        self.assertIn("greater than zero", frappe.throw.call_args.args[0])

    def test_item_must_belong_to_supported_inventory_group(self):
        def get_value(doctype, name, fieldname):
            return "PARTS FABRICATION" if doctype == "Machine Shop Request Code" else "OTHER"

        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.db.get_value.side_effect = get_value
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_output_item(output_doc(item_code="ITEM-001"))

        self.assertIn("MOULD, MACHINE, or CMMS", frappe.throw.call_args.args[0])

    def test_completion_requires_a_linked_project(self):
        doc = output_doc(name="MSJR-001")
        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.get_all.return_value = []
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_linked_project_completed(doc)

        self.assertIn("Generate and complete", frappe.throw.call_args.args[0])

    def test_completion_rejects_active_project(self):
        doc = output_doc(name="MSJR-001")
        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.get_all.return_value = [
                _dict(name="MSRP-001", workflow_state="Active")
            ]
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_linked_project_completed(doc)

        self.assertIn("MSRP-001", frappe.throw.call_args.args[0])

    def test_completion_accepts_completed_project(self):
        doc = output_doc(name="MSJR-001")
        with patch("qcmc_logic.customs.machine_shop_job_request.frappe") as frappe:
            frappe.get_all.return_value = [
                _dict(name="MSRP-001", workflow_state="Completed")
            ]
            _validate_linked_project_completed(doc)

        frappe.throw.assert_not_called()


class TestMachineShopOutputStockEntry(TestCase):
    def test_maps_remaining_quantity_to_material_receipt(self):
        msjr = _dict(
            name="MSJR-001",
            workflow_state="Completed",
            item_code="ITEM-001",
            quantity_produced=10,
            company="Test Company",
        )
        target = MagicMock()
        project = _dict(rework_history=[])

        with patch("qcmc_logic.utils.frappe") as frappe:
            frappe.session.user = "Administrator"
            frappe.get_doc.side_effect = [msjr, project]
            frappe.new_doc.return_value = target
            frappe.db.sql.return_value = [(3,)]
            frappe.db.get_value.side_effect = ["MSRP-001", "PROCESS-FINAL", "DJR-FINAL"]

            result = make_completed_output_stock_entry("MSJR-001")

        self.assertIs(result, target)
        self.assertEqual(target.stock_entry_type, "Material Receipt")
        self.assertEqual(target.purpose, "Material Receipt")
        self.assertEqual(target.company, "Test Company")
        self.assertEqual(target.msjr_no, "MSJR-001")
        self.assertEqual(target.custom_msrp_no, "MSRP-001")
        self.assertEqual(target.custom_final_process, "PROCESS-FINAL")
        self.assertEqual(target.custom_daily_job_report, "DJR-FINAL")
        self.assertEqual(target.custom_rework_cycle, 0)
        target.append.assert_called_once_with(
            "items", {"item_code": "ITEM-001", "qty": 7.0}
        )

    def test_direct_mapper_rejects_user_without_stockroom_role(self):
        with patch("qcmc_logic.utils.frappe") as frappe:
            frappe.session.user = "other@example.com"
            frappe.get_roles.return_value = ["Stock User"]
            frappe.throw.side_effect = RuntimeError

            with self.assertRaises(RuntimeError):
                make_completed_output_stock_entry("MSJR-003")

        self.assertIn("Stockroom_PR_EDSA_lv1", frappe.throw.call_args.args[0])
        frappe.get_doc.assert_not_called()
