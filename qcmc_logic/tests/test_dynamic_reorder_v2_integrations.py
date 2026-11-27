"""No site mutation: audit, scheduler and migration boundaries are in-memory doubles."""
import json
import unittest
from datetime import date
from unittest.mock import MagicMock, patch
import frappe
from qcmc_logic import dynamic_reorder_audit as a, dynamic_reorder_scheduler as s, dynamic_reorder_v2_setup as setup


def fail(message,*args,**kwargs):
    raise ValueError(message)


class TestV2Integration(unittest.TestCase):
    def test_history_is_one_per_item_mapping_and_batch(self):
        with patch.object(frappe,"db",MagicMock()) as db, patch.object(frappe,"get_doc") as get_doc:
            db.get_value.return_value=None
            row=dict(item_code="I",warehouse="A",mapping="M",company="Co",status="Preview",preview_only=True)
            a.record(row,"batch",date(2026,11,1))
            first=get_doc.call_args.args[0]
            self.assertEqual(first["mapping"],"M")
            a.record(dict(row,warehouse="B"),"batch",date(2026,11,1))
            self.assertEqual(first["calculation_key"],get_doc.call_args.args[0]["calculation_key"])
            a.record(dict(row,mapping="N"),"batch",date(2026,11,1))
            self.assertNotEqual(first["calculation_key"],get_doc.call_args.args[0]["calculation_key"])
            db.get_value.return_value="existing"
            get_doc.reset_mock()
            self.assertEqual(a.record(row,"batch",date(2026,11,1)),"existing")
            get_doc.assert_not_called()

    def test_automatic_apply_unconditionally_blocked_before_reads_or_writes(self):
        with patch.object(frappe,"throw",side_effect=fail),patch.object(frappe,"db",MagicMock()) as db,patch.object(frappe,"get_single") as single:
            with self.assertRaisesRegex(ValueError,"preview-only"):
                a.apply_one("H",automatic=True)
            single.assert_not_called(); db.sql.assert_not_called(); db.set_value.assert_not_called()

    def test_manual_application_requires_explicit_settings(self):
        with patch.object(frappe,"throw",side_effect=fail),patch.object(frappe,"get_single",return_value=frappe._dict(enabled=1,preview_only=1,automatic_update_enabled=0)),patch.object(frappe,"db",MagicMock()) as db:
            with self.assertRaisesRegex(ValueError,"disable Preview Only"):
                a.validate_application(MagicMock(),MagicMock())
            db.set_value.assert_not_called()

    def test_native_auto_indent_blocks_manual_application(self):
        with patch.object(frappe,"throw",side_effect=fail),patch.object(frappe,"get_single",return_value=frappe._dict(enabled=1,preview_only=0,automatic_update_enabled=0)),patch.object(frappe,"db",MagicMock()) as db:
            db.get_single_value.return_value=1
            with self.assertRaisesRegex(ValueError,"Native automatic Material Requests"):
                a.validate_application(MagicMock(),MagicMock())
            db.set_value.assert_not_called()

    def test_scheduler_runs_once_per_mapping_and_preserves_policy_period(self):
        from qcmc_logic import dynamic_reorder_batch as batch
        day=date(2026,11,1)
        queued=frappe._dict(name="B",status="Queued")
        completed=frappe._dict(name="B",status="Pending Review",total_items=1,pending_items=1,failed_items=0)
        with patch.object(frappe,"db",MagicMock()),patch.object(frappe,"get_all",return_value=[frappe._dict(name="M",company="Co")]), \
                patch.object(batch,"create_batch",side_effect=[queued,completed]) as create, \
                patch.object(batch,"populate",return_value=dict(total_items=1,pending_items=1,failed_items=0)) as populate, \
                patch.object(s,"apply_one") as apply:
            settings=frappe._dict(enabled=1,preview_only=0,automatic_update_enabled=1)
            self.assertEqual(s.process_month(settings,day)["recorded"],1)
            self.assertEqual(s.process_month(settings,day)["duplicates"],1)
            expected=dict(trigger="Scheduled",name=a.key("mapping-schedule-v3",str(day),"M"))
            self.assertEqual(create.call_args_list[0].kwargs,expected)
            self.assertEqual(create.call_args_list[1].kwargs,expected)
            populate.assert_called_once_with("B")
            apply.assert_not_called()

    def test_migration_quarantines_legacy_even_with_partial_child_table(self):
        rows=[frappe._dict(name="old",enabled=1,item_code="I",warehouse="A",warehouses=[{"warehouse":"A"}]),
              frappe._dict(name="v2",enabled=1,warehouses=[{"warehouse":"A"}]),
              frappe._dict(name="empty",enabled=1,warehouses=[])]
        def get_all(dt,**kwargs):
            if dt=="Reorder Policy Mapping": return rows
            if dt=="Item Reorder Override": return [frappe._dict(name="O",mapping=None,enabled=1)]
            raise AssertionError(dt)
        with patch.object(frappe,"db",MagicMock()) as db,patch.object(frappe,"get_all",side_effect=get_all), \
                patch.object(frappe,"get_doc",side_effect=lambda dt,name: next(r for r in rows if r.name==name)):
            setup.migrate_legacy_scopes()
            changes={c.args[1]:c.args[2] for c in db.set_value.call_args_list}
            self.assertEqual(changes["old"]["enabled"],0)
            self.assertEqual(changes["old"]["migration_review_required"],1)
            self.assertEqual(changes["empty"]["enabled"],0)
            self.assertNotIn("v2",changes)
            self.assertEqual(changes["O"]["enabled"],0)
            self.assertEqual(rows[0].item_code,"I")
            db.delete.assert_not_called(); db.commit.assert_not_called()

    def test_schema_and_hooks_expose_mapping_integration(self):
        from qcmc_logic.dynamic_reorder_setup import SCHEMAS
        from qcmc_logic.dynamic_reorder_layout import LAYOUTS
        from qcmc_logic import hooks
        fields={f["fieldname"] for f in SCHEMAS["Reorder Policy Mapping"]}
        self.assertTrue({"inventory_group","inventory_type","migration_review_required","legacy_scope_reviewed"} <= fields)
        history_fields={f for _,*columns in LAYOUTS["Reorder Calculation History"] for col in columns for f in col}
        self.assertIn("mapping",history_fields)
        self.assertIn("validate",hooks.doc_events["Reorder Policy Mapping"])
        self.assertIn("validate",hooks.doc_events["Item Reorder Override"])
        self.assertIn("validate",hooks.doc_events["Reorder Policy"])

    def test_migration_disables_overrides_with_unreviewed_warehouse_scope(self):
        mapping=frappe._dict(name="M",warehouses=[{"warehouse":"A"},{"warehouse":"B"}])
        override=frappe._dict(name="O",mapping="M",warehouse="A",enabled=1)
        with patch.object(frappe,"db",MagicMock()) as db,patch.object(frappe,"get_all",side_effect=[[mapping],[override]]), \
                patch.object(frappe,"get_doc",return_value=mapping):
            setup.migrate_legacy_scopes()
            self.assertEqual(db.set_value.call_args.args[:2],("Item Reorder Override","O"))
            self.assertEqual(db.set_value.call_args.args[2]["enabled"],0)

    def test_legacy_migration_is_state_idempotent_and_preserves_scope(self):
        legacy=frappe._dict(name="L",enabled=1,item_group="Scoped Group",warehouse="Group W",include_warehouse_descendants=1)
        override=frappe._dict(name="O",enabled=1,mapping=None,warehouse="Single W")
        def get_all(dt,**kwargs):
            if dt=="Reorder Policy Mapping": return [legacy]
            return [override] if override.enabled else []
        def set_value(dt,name,values,**kwargs):
            (legacy if name=="L" else override).update(values)
        with patch.object(frappe,"db",MagicMock()) as db,patch.object(frappe,"get_all",side_effect=get_all),patch.object(frappe,"get_doc",return_value=legacy):
            db.set_value.side_effect=set_value
            setup.migrate_legacy_scopes()
            first=(dict(legacy),dict(override))
            setup.migrate_legacy_scopes()
            self.assertEqual(first,(dict(legacy),dict(override)))
            self.assertEqual(legacy.item_group,"Scoped Group")
            self.assertEqual(legacy.warehouse,"Group W")
            self.assertTrue(legacy.include_warehouse_descendants)
            self.assertIsNone(legacy.warehouses)
            db.delete.assert_not_called(); db.commit.assert_not_called()

    def test_readiness_missing_metadata_is_read_only(self):
        with patch.object(frappe,"db",MagicMock()) as db:
            db.exists.return_value=False
            result=setup.readiness()
            self.assertFalse(result["schema_ready"])
            self.assertIn("Reorder Mapping Warehouse",result["missing_metadata"])
            db.set_value.assert_not_called(); db.commit.assert_not_called()
