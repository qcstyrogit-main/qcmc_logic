import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe
from qcmc_logic.customs.mc_maintenance_purchase_request import (
    ROLE, STATE, REQUESTER, REQUIRED, APPROVED_BY, eligible, validate_maintenance,
)
from qcmc_logic.customs.mc_purchase_request import MANAGER, requires_mc_ppic, restrict_mc_permission
from qcmc_logic.patches.add_mc_maintenance_head_purchase_request import update_workflow, ACTION
from qcmc_logic.patches.add_mc_maintenance_head_purchase_request import assign_approver, ROLE_PROFILE


class TestMCMaintenancePurchaseRequest(TestCase):
    def setUp(self):
        self.roles=[REQUESTER]
        for target,value in (
            ('frappe.session',frappe._dict(user='creator@example.com')),
            ('frappe.get_roles',lambda *a:self.roles),
            ('frappe.throw',Mock(side_effect=frappe.ValidationError)),
            ('qcmc_logic.customs.mc_maintenance_purchase_request.now_datetime',lambda:datetime(2026,11,26,10)),
        ):
            p=patch(target,value);p.start();self.addCleanup(p.stop)
        self.workflow=next(w for w in json.loads((Path(__file__).parents[1]/'fixtures/workflow.json').read_text())
                           if w['name']=='Purchase Request')

    def document(self,**values):
        doc=frappe._dict(material_request_type='Purchase',company='Multiplast Corporation',owner='creator@example.com',
                         workflow_state='Draft',custom_request_type='Stockroom',custom_pr_mc_rmfs_creator=0,
                         custom_pr_provincial_creator=0,docstatus=0)
        doc.update(values)
        return doc

    def change(self,old,**values):
        doc=deepcopy(old);doc.update(values)
        doc.get_doc_before_save=lambda:old
        doc.set=lambda field,value:doc.update({field:value})
        return doc

    def test_stockroom_route_inserts_head_and_retains_existing_condition(self):
        rows=[r for r in self.workflow['transitions'] if r['state']=='Draft' and r['allowed']==REQUESTER]
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['action'],rows[0]['next_state']),(ACTION,STATE))
        for values,allowed in [({},True),({'company':'QC Styropackaging Corporation'},False),
                               ({'custom_pr_mc_rmfs_creator':1},False),
                               ({'custom_pr_provincial_creator':1,'custom_request_type':'MIS'},False)]:
            self.assertEqual(bool(eval(rows[0]['condition'],{'__builtins__':{}},{'doc':self.document(**values)})),allowed)

    def test_only_stockroom_creator_can_enter_head_stage(self):
        old=self.document();doc=self.change(old,workflow_state=STATE)
        validate_maintenance(doc)
        self.assertEqual(doc.get(REQUIRED),1)
        self.roles=[]
        with self.assertRaises(frappe.ValidationError):validate_maintenance(self.change(old,workflow_state=STATE))
        self.roles=[REQUESTER]
        with self.assertRaises(frappe.ValidationError):validate_maintenance(self.change(old,workflow_state=STATE,company='Other'))
        with patch('frappe.session',frappe._dict(user='other@example.com')):
            with self.assertRaises(frappe.ValidationError):validate_maintenance(self.change(old,workflow_state=STATE))

    def test_head_approval_requires_role_and_records_evidence(self):
        old=self.document(workflow_state=STATE,custom_pr_mc_maintenance_required=1)
        with self.assertRaises(frappe.ValidationError):validate_maintenance(self.change(old,workflow_state=MANAGER))
        self.roles=[ROLE]
        doc=self.change(old,workflow_state=MANAGER);validate_maintenance(doc)
        self.assertEqual(doc.get(APPROVED_BY),'creator@example.com')
        self.assertIsNotNone(doc.custom_pr_mc_maintenance_approved_on)
        validate_maintenance(self.change(old,workflow_state='Cancelled Before Submission'))

    def test_submission_and_wrong_next_stage_cannot_bypass_head(self):
        with self.assertRaises(frappe.ValidationError):validate_maintenance(self.change(self.document(),docstatus=1))
        old=self.document(workflow_state=STATE,custom_pr_mc_maintenance_required=1)
        for values in ({'docstatus':1},{'workflow_state':'To Receive'},{'workflow_state':'Pending Network Admin Evaluation'}):
            with self.assertRaises(frappe.ValidationError):validate_maintenance(self.change(old,**values))

    def test_evidence_is_server_owned_and_required_downstream(self):
        old=self.document()
        with self.assertRaises(frappe.ValidationError):validate_maintenance(self.change(old,custom_pr_mc_maintenance_required=1))
        new=self.change(old,custom_pr_mc_maintenance_approved_by='forged');new.get_doc_before_save=lambda:None
        with self.assertRaises(frappe.ValidationError):validate_maintenance(new)
        old=self.document(workflow_state=MANAGER,custom_pr_mc_maintenance_required=1)
        with self.assertRaises(frappe.ValidationError):validate_maintenance(self.change(old,workflow_state='To Receive'))
        old.custom_pr_mc_maintenance_approved_by='head@example.com'
        validate_maintenance(self.change(old,workflow_state='To Receive'))
        with self.assertRaises(frappe.ValidationError):validate_maintenance(self.change(old,company='Other'))

    def test_mc_ppic_provincial_and_legacy_routes_remain(self):
        ppic=self.document(custom_pr_mc_rmfs_creator=1)
        self.assertTrue(requires_mc_ppic(ppic));self.assertFalse(eligible(ppic))
        for request_type in ('MIS','Office Supplies & Equipment','Motorpool'):
            self.assertFalse(eligible(self.document(custom_pr_provincial_creator=1,custom_request_type=request_type)))
        validate_maintenance(self.change(self.document(workflow_state=MANAGER),workflow_state='To Receive'))
        self.assertTrue(any(r['state']=='Pending MC PPIC Supervisor' and r['next_state']==MANAGER for r in self.workflow['transitions']))
        self.assertEqual(update_workflow(self.workflow),self.workflow)

    def test_head_grant_is_purchase_only_and_current_stage_only(self):
        self.roles=[ROLE]
        with patch('frappe.get_meta',return_value=frappe._dict(permissions=[])):
            self.assertFalse(restrict_mc_permission(self.document(material_request_type='Material Transfer'),'read','creator@example.com'))
            doc=self.document(name='PR-1')
            with patch('frappe.db',frappe._dict(get_value=lambda *a:STATE)):
                self.assertIsNone(restrict_mc_permission(doc,'write','creator@example.com'))
            with patch('frappe.db',frappe._dict(get_value=lambda *a:MANAGER)):
                self.assertFalse(restrict_mc_permission(doc,'write','creator@example.com'))

    def test_profile_managed_approver_keeps_existing_profiles(self):
        user=Mock()
        user.role_profiles=[frappe._dict(role_profile='Existing maintenance profile')]
        user.get=lambda key:user.role_profiles
        user.append.side_effect=lambda key,value:user.role_profiles.append(frappe._dict(value))
        profile=frappe._dict(roles=[frappe._dict(role=ROLE)])
        with patch('frappe.get_doc',side_effect=[user,profile]), patch('frappe.db',frappe._dict(exists=lambda *a:True)):
            assign_approver('head@example.com')
        self.assertEqual([r.role_profile for r in user.role_profiles],['Existing maintenance profile',ROLE_PROFILE])
        user.save.assert_called_once_with(ignore_permissions=True)
        user.add_roles.assert_not_called()
