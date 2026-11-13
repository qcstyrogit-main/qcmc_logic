import importlib
import sys
import types
import unittest
from copy import deepcopy
from unittest.mock import patch

frappe = types.ModuleType('frappe')
frappe.PermissionError = type('PermissionError', (Exception,), {})
frappe.throw = lambda message, exc: (_ for _ in ()).throw(exc(message))
frappe.get_roles = lambda: []
frappe.utils = types.SimpleNamespace(today=lambda: '2026-10-09')
naming = types.ModuleType('frappe.model.naming')
naming.make_autoname = lambda *a, **k: ''
from pathlib import Path
spec = importlib.util.spec_from_file_location(
    'maintenance_controls', Path(__file__).resolve().parents[1] / 'customs' / 'maintenance_job_order.py')
m = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'frappe': frappe, 'frappe.model': types.ModuleType('frappe.model'),
                             'frappe.model.naming': naming}):
    spec.loader.exec_module(m)

class Doc(types.SimpleNamespace):
    def get(self, key):
        return getattr(self, key, None)
    def get_doc_before_save(self):
        return self.old

def document(section, state):
    names = ['section', 'workflow_state', 'work_instruction', 'breakdown_code', 'requested_by']
    return Doc(section=section, workflow_state=state, work_instruction='done', breakdown_code='A',
               requested_by='worker', document_date='2026-10-09', docstatus=0, old=None,
               meta=types.SimpleNamespace(fields=[types.SimpleNamespace(fieldname=n, fieldtype='Data') for n in names]))

class Controls(unittest.TestCase):
    def validate(self, doc, role):
        with patch.object(frappe, 'get_roles', return_value=[role]):
            m.validate(doc)
    def test_all_routes_and_field_guards(self):
        for section in m.SECTION_ROUTES:
            roles = m.state_roles(section)
            for index, state in enumerate(m.STATES):
                old = document(section, state)
                doc = deepcopy(old); doc.old = old
                self.validate(doc, roles[index])
                for wrong in set(m.MAINTENANCE_ROLES.values()) - {roles[index]}:
                    with self.assertRaises(frappe.PermissionError): self.validate(doc, wrong)
                if index < 3:
                    doc.workflow_state = m.STATES[index + 1]
                    self.validate(doc, roles[index])
            old = document(section, 'Approved')
            for status in (0, 1):
                old.docstatus = status
                doc = deepcopy(old); doc.old = old
                doc.work_instruction = 'fixed'; doc.breakdown_code = 'B'
                self.validate(doc, roles[2])
                doc.requested_by = 'tampered'
                with self.assertRaises(frappe.PermissionError): self.validate(doc, roles[2])
            doc = deepcopy(old); doc.old = old; doc.workflow_state = 'Active'; doc.requested_by = 'tampered'
            with self.assertRaises(frappe.PermissionError): self.validate(doc, roles[2])
    def test_no_skips_or_section_swap(self):
        old = document('GUYONG - RM', 'Draft')
        doc = deepcopy(old); doc.old = old; doc.workflow_state = 'Active'
        with self.assertRaises(frappe.PermissionError): self.validate(doc, 'RM - SMB')
        doc.workflow_state = 'Draft'; doc.section = 'MC - RM'
        with self.assertRaises(frappe.PermissionError): self.validate(doc, 'RM - SMB')
        doc.old = None; doc.workflow_state = 'Approved'
        with self.assertRaises(frappe.PermissionError): self.validate(doc, 'RM - MC')

if __name__ == '__main__':
    unittest.main()
