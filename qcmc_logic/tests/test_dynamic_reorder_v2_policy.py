"""V2 scope rules run without a site or database."""
import unittest
from datetime import date
from qcmc_logic import dynamic_reorder_policy as p


class TestMappingScope(unittest.TestCase):
    def mapping(self, **values):
        return dict(name="M", company="Co", enabled=1, inventory_group="FG", inventory_type="Local",
                    warehouses=[{"warehouse":"A"},{"warehouse":"B"}], replenishment_warehouse="A", **values)

    def test_explicit_scope(self):
        self.assertEqual(p.mapping_warehouses(self.mapping()), ["A","B"])
        for field in ("item_code","item_group","include_item_descendants","warehouse","include_warehouse_descendants"):
            with self.subTest(field=field):
                row=self.mapping(**{field:1})
                self.assertFalse(p.is_v2_mapping(row))
                row["legacy_scope_reviewed"]=1
                self.assertTrue(p.is_v2_mapping(row))
        self.assertFalse(p.is_v2_mapping({"warehouse":"A","enabled":1}))

    def test_validity(self):
        row=self.mapping(effective_from="2026-11-01",effective_to="2026-11-30")
        self.assertTrue(p.active_on(row,date(2026,11,1)))
        self.assertTrue(p.active_on(row,date(2026,11,30)))
        self.assertFalse(p.active_on(row,date(2026,12,1)))

    def test_conflict_requires_overlapping_warehouses(self):
        row=self.mapping()
        disjoint=dict(row,name="Other",warehouses=[{"warehouse":"C"}],replenishment_warehouse="C")
        self.assertFalse(p.mapping_conflicts(row,disjoint))
        other=dict(disjoint,warehouses=[{"warehouse":"B"},{"warehouse":"C"}])
        self.assertTrue(p.mapping_conflicts(row,other))
        self.assertTrue(p.mapping_conflicts(row,dict(disjoint,warehouses=[])))
        self.assertTrue(p.mapping_conflicts(row,dict(disjoint,warehouse="C")))
        self.assertTrue(p.classification_period_conflicts(row,disjoint))
        for field,value in (("company","Else"),("inventory_group","RM"),("inventory_type","Imported"),("enabled",0),("name","M")):
            with self.subTest(field=field):
                self.assertFalse(p.mapping_conflicts(row,dict(other,**{field:value})))

    def test_conflict_date_boundaries(self):
        a=self.mapping(effective_to="2026-11-30")
        b=dict(a,name="Other",effective_from="2026-11-30",effective_to=None)
        self.assertTrue(p.mapping_conflicts(a,b))
        self.assertFalse(p.mapping_conflicts(a,dict(b,effective_from="2026-12-01")))

    def test_scope_validation(self):
        row=self.mapping()
        warehouses={w:dict(company="Co",disabled=0,is_group=0) for w in ("A","B")}
        p.validate_scope(row,warehouses)
        for key,value in (("disabled",1),("is_group",1),("company","Other")):
            bad={**warehouses,"B":{**warehouses["B"],key:value}}
            with self.subTest(key=key),self.assertRaises(ValueError):
                p.validate_scope(row,bad)
        for values in ({"warehouses":[]},{"warehouses":[{"warehouse":"A"},{"warehouse":"A"}]},
                       {"replenishment_warehouse":"C"},{"effective_from":"2026-12-01","effective_to":"2026-11-01"}):
            with self.subTest(values=values),self.assertRaises(ValueError):
                p.validate_scope(dict(row,**values),warehouses)

    def test_reorder_row_scope_checks_leaf_and_group_ancestry(self):
        tree = [
            dict(name="Root", parent_warehouse=None),
            dict(name="A", parent_warehouse="Root"),
            dict(name="B", parent_warehouse="Root"),
            dict(name="Other", parent_warehouse=None),
            dict(name="C", parent_warehouse="Other"),
        ]
        scope = p.reorder_scope(["A", "B"], tree)
        for row in (
            dict(warehouse="A", warehouse_group="A"),
            dict(warehouse="B", warehouse_group=None),
            dict(warehouse="C", warehouse_group="Root"),
            dict(warehouse="C", warehouse_group="Unknown"),
        ):
            self.assertTrue(p.reorder_row_overlaps(row, ["A", "B"], scope))
        for row in (
            dict(warehouse="C", warehouse_group="C"),
            dict(warehouse="C", warehouse_group="Other"),
            dict(warehouse="C", warehouse_group=None),
        ):
            self.assertFalse(p.reorder_row_overlaps(row, ["A", "B"], scope))

    def test_reorder_scope_rejects_missing_or_cyclic_hierarchy(self):
        for tree in ([], [dict(name="A", parent_warehouse="A")],
                     [dict(name="A", parent_warehouse="Missing")]):
            with self.assertRaises(ValueError):
                p.reorder_scope(["A"], tree)

    def test_preserved_guyong_requires_exact_reviewed_pair(self):
        owned = dict(warehouse="FG - Sta Clara", material_request_type="Manufacture",
                     custom_managed_reorder=1, custom_reorder_mapping="M")
        row = dict(warehouse="FG - Guyong", warehouse_group="FG - Guyong",
                   material_request_type="Manufacture", custom_reorder_excluded_mapping="M")
        scope = ["FG - Sta Clara","FG - Guyong"]
        self.assertTrue(p.reviewed_preserved_row(row,owned,"M",scope))
        self.assertFalse(p.reviewed_preserved_row(row,None,"M",scope))
        self.assertFalse(p.reviewed_preserved_row(row,owned,"M",["FG - Sta Clara"]))
        self.assertFalse(p.reviewed_preserved_row(dict(row,custom_reorder_excluded_mapping=None),owned,"M",scope))
        self.assertFalse(p.reviewed_preserved_row(dict(row,custom_managed_reorder=1),owned,"M",scope))

    def test_production_mode(self):
        self.assertEqual(p.production_mode("FG"),"Make to Stock")
        for group in ("RM","Packaging","Raw Materials",None):
            self.assertEqual(p.production_mode(group),"Make to Order")

    def test_mapping_validation_reads_conflicts_under_row_locks(self):
        import frappe
        from unittest.mock import patch, MagicMock
        class Doc(frappe._dict):
            def as_dict(self): return dict(self)
        doc=Doc(self.mapping() | {"policy":"P"})
        policy=frappe._dict(inventory_category="FG",inventory_type="Local")
        with patch.object(frappe,"db",MagicMock()) as db,patch.object(frappe,"get_doc",return_value=policy) as get_doc, \
                patch.object(frappe,"get_all",return_value=[frappe._dict(name=w,company="Co",disabled=0,is_group=0) for w in ("A","B")]):
            db.sql.return_value=[]
            p.validate_mapping(doc)
            get_doc.assert_called_with("Reorder Policy","P",for_update=True)
            queries=" ".join(call.args[0] for call in db.sql.call_args_list)
            self.assertIn("tabCompany",queries)
            self.assertIn("tabReorder Policy Mapping",queries)
            self.assertIn("FOR UPDATE",queries)

    def test_mapping_validation_reads_other_child_scopes(self):
        import frappe
        from unittest.mock import patch, MagicMock
        class Doc(frappe._dict):
            def as_dict(self): return dict(self)
        doc = Doc(self.mapping() | {"policy":"P"})
        policy = frappe._dict(inventory_category="FG", inventory_type="Local")
        other = frappe._dict(name="Other", company="Co", enabled=1,
                            inventory_group="FG", inventory_type="Local",
                            replenishment_warehouse="C")
        with patch.object(frappe,"db",MagicMock()) as db, \
                patch.object(frappe,"get_doc",return_value=policy), \
                patch.object(frappe,"get_all",return_value=[
                    frappe._dict(name=w,company="Co",disabled=0,is_group=0) for w in ("A","B")]), \
                patch.object(frappe,"throw",side_effect=lambda message: (_ for _ in ()).throw(ValueError(message))):
            db.sql.side_effect = [[], [other.copy()], [{"warehouse":"C"}]]
            p.validate_mapping(doc)
            self.assertIn("tabReorder Mapping Warehouse", db.sql.call_args.args[0])
            self.assertIn("FOR UPDATE", db.sql.call_args.args[0])
            db.sql.side_effect = [[], [other.copy()], [{"warehouse":"C"},{"warehouse":"B"}]]
            with self.assertRaisesRegex(ValueError, "Overlapping"):
                p.validate_mapping(doc)

    def test_policy_edit_locks_before_checking_active_mapping(self):
        import frappe
        from unittest.mock import patch, MagicMock
        doc=MagicMock(name="P")
        doc.name="P"
        doc.get_doc_before_save.return_value={"inventory_category":"FG","inventory_type":"Local"}
        doc.get.side_effect=lambda field: {"inventory_category":"RM","inventory_type":"Local"}[field]
        with patch.object(frappe,"db",MagicMock()) as db,patch.object(frappe,"throw",side_effect=lambda message: (_ for _ in ()).throw(ValueError(message))):
            db.sql.side_effect=[[],[{"name":"M"}]]
            with self.assertRaisesRegex(ValueError,"Disable active mappings"):
                p.validate_policy(doc)
            self.assertTrue(all("FOR UPDATE" in c.args[0] for c in db.sql.call_args_list))
