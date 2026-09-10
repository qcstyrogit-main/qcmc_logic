import json
import sqlite3
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import frappe

from qcmc_logic.customs.permissions import (
    material_request_has_permission,
    material_request_permission_query,
)


class TestMaterialRequestListPermissions(TestCase):
    def setUp(self):
        workflows = json.loads((Path(__file__).parents[1] / 'fixtures/workflow.json').read_text())
        workflow = next(w for w in workflows if w['name'] == 'Purchase Request')
        workflow = frappe._dict(states=[frappe._dict(s) for s in workflow['states']])
        patches = [
            patch('frappe.model.workflow.get_workflow', return_value=workflow),
            patch('qcmc_logic.customs.permissions.frappe.db',
                  frappe._dict(escape=lambda v: "'" + v.replace("'", "''") + "'")),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.rows = [
            ('receive', 'Purchase', 'To Receive', 'other'),
            ('received', 'Purchase', 'Received', 'other'),
            ('submitted', 'Purchase', 'Submitted', 'other'),
            ('draft', 'Purchase', 'Draft', 'user@example.com'),
            ('other_draft', 'Purchase', 'Draft', 'other'),
            ('pm', 'Purchase', 'Pending QC PM Approval', 'other'),
            ('mc_pm', 'Purchase', 'Pending MC PM Approval', 'other'),
            ('ppic', 'Purchase', 'Pending PPIC Supervisor', 'other'),
            ('mis', 'Purchase', 'Pending MIS Supervisor Approval', 'other'),
            ('unset', 'Purchase', None, 'user@example.com'),
            ('unknown', 'Purchase', 'Unknown', 'user@example.com'),
            ('transfer', 'Material Transfer', 'Submitted', 'other'),
        ]

    def visible_names(self, roles, warehouse_condition=''):
        with patch('qcmc_logic.customs.permissions.frappe.get_roles', return_value=roles), patch(
            'qcmc_logic.customs.permissions._warehouse_transaction_permission_query',
            return_value=warehouse_condition,
        ):
            condition = material_request_permission_query('user@example.com')
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE "tabMaterial Request" '
                       '(name TEXT, material_request_type TEXT, workflow_state TEXT, owner TEXT)')
            db.executemany('INSERT INTO "tabMaterial Request" VALUES (?, ?, ?, ?)', self.rows)
            return {r[0] for r in db.execute('SELECT name FROM "tabMaterial Request" WHERE ' + condition)}

    def test_each_role_only_sees_its_current_step(self):
        cases = [
            (['Stockroom_PR_QC_lv1'], {'draft', 'unset', 'transfer'}),
            (['RMFS_PR_QC_lv1'], {'draft', 'unset', 'transfer'}),
            (['Plant Manager QC'], {'pm', 'transfer'}),
            (['Plant Manager MC'], {'mc_pm', 'transfer'}),
            (['RMFS_PR_QC_lv2'], {'ppic', 'transfer'}),
            (['MIS Supervisor'], {'mis', 'transfer'}),
            (['Purchase User'], {'receive', 'received', 'submitted', 'transfer'}),
            (['Stock User'], {'draft', 'unset', 'transfer'}),
            (['Purchase Manager'], {'transfer'}),
        ]
        for roles, expected in cases:
            with self.subTest(roles=roles):
                self.assertEqual(self.visible_names(roles), expected | {'draft', 'unset', 'unknown'})

    def test_multiple_roles_combine_their_steps(self):
        self.assertEqual(self.visible_names(['Stockroom_PR_QC_lv1', 'Purchase User']),
                         {'draft', 'unset', 'unknown', 'receive', 'received', 'submitted', 'transfer'})

    def test_warehouse_restrictions_remain_required(self):
        self.assertEqual(self.visible_names(['Purchase User'], "name = 'received'"), {'received'})
        self.assertEqual(self.visible_names(['Purchase User'], '1=0'), set())
        self.assertEqual(self.visible_names(['Plant Manager QC'], "name = 'received'"), set())

    def test_direct_read_and_list_agree(self):
        for roles in (['Stockroom_PR_QC_lv1'], ['Purchase User'], ['RMFS_PR_QC_lv2']):
            visible = self.visible_names(roles)
            with patch('qcmc_logic.customs.permissions.frappe.get_roles', return_value=roles), patch(
                'qcmc_logic.customs.permissions.warehouse_transaction_has_permission', return_value=True
            ):
                for name, request_type, state, owner in self.rows:
                    doc = frappe._dict(name=name, material_request_type=request_type,
                                       workflow_state=state, owner=owner)
                    for ptype in ('read', 'select', 'print', 'email', 'export'):
                        with self.subTest(roles=roles, name=name, ptype=ptype):
                            self.assertEqual(material_request_has_permission(doc, ptype, 'user@example.com'),
                                             name in visible)

    def test_creator_keeps_access_throughout_approval(self):
        self.rows = [(name, kind, state, 'user@example.com')
                     for name, kind, state, owner in self.rows]
        self.assertEqual(self.visible_names(['Stockroom_PR_QC_lv1']),
                         {row[0] for row in self.rows})
        with patch('qcmc_logic.customs.permissions.frappe.get_roles', return_value=['Stockroom_PR_QC_lv1']), patch(
            'qcmc_logic.customs.permissions.warehouse_transaction_has_permission', return_value=True
        ):
            for name, kind, state, owner in self.rows:
                doc = frappe._dict(name=name, material_request_type=kind, workflow_state=state, owner=owner)
                self.assertTrue(material_request_has_permission(doc, 'read', owner))

    def test_transition_save_is_not_blocked_by_target_state_visibility(self):
        doc = frappe._dict(material_request_type='Purchase', workflow_state='To Receive')
        with patch('qcmc_logic.customs.permissions.warehouse_transaction_has_permission', return_value=True):
            self.assertTrue(material_request_has_permission(doc, 'write', 'user@example.com'))
