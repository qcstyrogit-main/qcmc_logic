import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from qcmc_logic.patches import add_lx310_raw_print_client_script as patch_module


class _FakeClientScript:
    def __init__(self):
        self.saved = False

    def update(self, values):
        for key, value in values.items():
            setattr(self, key, value)

    def save(self, **kwargs):
        self.saved = True
        self.save_kwargs = kwargs


class TestAddLx310RawPrintClientScript(TestCase):
    def test_execute_creates_missing_client_script_as_new_document(self):
        fixture_row = {
            "doctype": "Client Script",
            "dt": "Purchase Order",
            "enabled": 1,
            "name": "Purchase Order LX-310 Raw Print",
            "script": "frappe.ui.form.on('Purchase Order', {});",
            "view": "Form",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_dir = Path(tmpdir) / "fixtures"
            fixture_dir.mkdir()
            (fixture_dir / "client_script.json").write_text(json.dumps([fixture_row]))

            created_doc = _FakeClientScript()
            fake_frappe = SimpleNamespace()
            fake_frappe.get_app_path = lambda *parts: str(Path(tmpdir).joinpath(*parts[1:]))
            fake_frappe.clear_cache = lambda **kwargs: None
            fake_frappe.db = SimpleNamespace(exists=lambda doctype, name: False)

            def get_doc(*args):
                raise AssertionError("missing Client Script must be created with new_doc")

            fake_frappe.get_doc = get_doc
            fake_frappe.new_doc = lambda doctype: created_doc

            with patch.object(patch_module, "frappe", fake_frappe):
                patch_module.execute()

        self.assertEqual(created_doc.name, "Purchase Order LX-310 Raw Print")
        self.assertEqual(created_doc.dt, "Purchase Order")
        self.assertEqual(created_doc.view, "Form")
        self.assertEqual(created_doc.enabled, 1)
        self.assertEqual(created_doc.script, "frappe.ui.form.on('Purchase Order', {});")
        self.assertTrue(created_doc.saved)
        self.assertEqual(created_doc.save_kwargs, {"ignore_permissions": True})
