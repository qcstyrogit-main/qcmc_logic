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

    def test_conflict_is_classification_wide_even_disjoint_warehouses(self):
        row=self.mapping()
        other=dict(row,name="Other",warehouses=[{"warehouse":"C"}])
        self.assertTrue(p.mapping_conflicts(row,other))
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
