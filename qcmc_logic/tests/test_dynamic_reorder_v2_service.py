"""Exercise the real consolidation service with read-only database boundaries."""
import unittest
from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from unittest.mock import patch, MagicMock
import frappe
from qcmc_logic import dynamic_reorder_service as s


class TestMappingPreview(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack(); self.addCleanup(self.stack.close)
        self.mapping=frappe._dict(name="M",enabled=1,company="Co",policy="P",warehouses=[{"warehouse":"A"},{"warehouse":"B"}],replenishment_warehouse="A")
        self.policy=frappe._dict(name="P",enabled=1,inventory_category="FG",inventory_type="Local",historical_months=3,
            demand_period_method="Complete Calendar Months",rolling_days=90,lead_time=7,safety_days=5,coverage_days=15,
            demand_delivery=1,demand_manufacture=1,demand_intercompany=1,demand_provincial=1,preserve_no_demand=1,
            increase_limit=30,decrease_limit=20,material_request_type="Manufacture")
        self.item=frappe._dict(name="I",item_name="Item",item_group="Products",stock_uom="Nos",creation=date(2020,1,1),
            custom_inventory_group="FG",custom_inventory_type_="Local")
        self.overrides=[]; self.reorder=[]
        self.stock=[frappe._dict(item_code="I",warehouse="A",actual_qty=10,projected_qty=20),
                    frappe._dict(item_code="I",warehouse="B",actual_qty=30,projected_qty=50)]
        self.db=MagicMock(); self.db.get_default.return_value=3; self.db.get_value.return_value=1
        for target,value in (("db",self.db),("session",frappe._dict(user="Administrator"))):
            self.stack.enter_context(patch.object(frappe,target,value))
        self.stack.enter_context(patch.object(frappe,"throw",side_effect=lambda message,*a,**k: (_ for _ in ()).throw(ValueError(message))))
        self.stack.enter_context(patch.object(frappe,"get_doc",side_effect=self.get_doc))
        self.stack.enter_context(patch.object(frappe,"get_all",side_effect=self.get_all))
        self.stack.enter_context(patch.object(s,"business_date",return_value=date(2026,11,25)))
        self.stack.enter_context(patch.object(s,"check_warehouse_access",return_value=True))
        self.stack.enter_context(patch.object(s,"check_item_inventory_group_access",return_value=True))
        self.demand=self.stack.enter_context(patch.object(s,"monthly_demand",side_effect=self.monthly))

    def get_doc(self, dt, name=None):
        if dt=="Reorder Policy Mapping": return self.mapping
        if dt=="Reorder Policy": return self.policy
        if dt=="Seasonal Demand Profile": return self.profile
        raise AssertionError(dt)

    def get_all(self, dt, **kwargs):
        return {"Warehouse":[frappe._dict(name=w,company="Co",disabled=0,is_group=0) for w in ("A","B")],
                "Reorder Policy Mapping":[self.mapping],"Item":[self.item],"Item Reorder Override":self.overrides,
                "Item Reorder":self.reorder,"Bin":self.stock}[dt]

    def monthly(self, company, warehouses, items, start, end, deduct_returns=True, sources=None):
        from qcmc_logic.dynamic_reorder_calculation import demand_period
        return {("I",w,m.replace(day=1)):dict(gross=Decimal(310 if w=="A" else 620),returns=Decimal(0),net=Decimal(310 if w=="A" else 620))
                for w in warehouses for m,_ in demand_period(date(2026,11,1))}

    def preview(self, **kwargs):
        return s.preview_rows("Co",mapping="M",as_of=date(2026,11,1),**kwargs)

    def test_one_consolidated_result_without_override(self):
        rows=self.preview(); self.assertEqual(len(rows),1)
        r=rows[0]; self.assertEqual((r["mapping"],r["warehouses"]),("M",["A","B"]))
        self.assertEqual((r["actual_qty"],r["projected_qty"]),(40,70))
        self.assertEqual(r["net_demand"],2790)
        self.assertEqual(r["reorder_level"],364)
        self.assertEqual(r["reorder_qty"],455)
        self.assertTrue(r["preview_only"])
        self.assertEqual(r["production_mode"],"Make to Stock")
        self.assertEqual(self.demand.call_args.args[1],["A","B"])
        self.assertEqual(len(self.demand.call_args.kwargs["sources"]),4)
        self.db.set_value.assert_not_called()

    def test_mapping_scope_required_and_legacy_not_broadened(self):
        with self.assertRaisesRegex(ValueError,"Mapping"):
            s.preview_rows("Co",warehouse="A")
        self.mapping.item_code="I"
        with self.assertRaisesRegex(ValueError,"Legacy"):
            self.preview()

    def test_disjoint_mapping_is_allowed_but_shared_warehouse_blocks_preview(self):
        other = frappe._dict(name="Other", company="Co", enabled=1, policy="P",
                            replenishment_warehouse="C", warehouses=[{"warehouse":"C"}])
        get_all, get_doc = self.get_all, self.get_doc
        def all_docs(dt, **kwargs):
            if dt == "Reorder Policy Mapping":
                return [self.mapping, frappe._dict(name="Other", policy="P")]
            return get_all(dt, **kwargs)
        def get_document(dt, name=None):
            if dt == "Reorder Policy Mapping" and name == "Other":
                return other
            return get_doc(dt, name)
        with patch.object(frappe,"get_all",side_effect=all_docs), \
                patch.object(frappe,"get_doc",side_effect=get_document):
            self.assertEqual(len(self.preview()), 1)
            other.warehouses.append({"warehouse":"B"})
            with self.assertRaisesRegex(ValueError, "Overlapping"):
                self.preview()

    def test_optional_exclusion_override_and_conflicts(self):
        self.overrides=[frappe._dict(enabled=1,mapping="M",item_code="I",exclude_item=1)]
        self.assertEqual(self.preview()[0]["status"],"Skipped")
        self.overrides.append(self.overrides[0].copy())
        self.assertEqual(self.preview()[0]["status"],"Failed")

    def test_parameter_override_applies_to_combined_demand(self):
        self.overrides=[frappe._dict(enabled=1,mapping="M",item_code="I",override_parameters=1,
            historical_months=3,lead_time=1,safety_days=0,coverage_days=1)]
        r=self.preview()[0]
        self.assertEqual(r["reorder_level"],31)
        self.assertEqual(r["reorder_qty"],31)

    def test_fixed_override(self):
        self.overrides=[frappe._dict(enabled=1,mapping="M",item_code="I",fixed_reorder_values=1,fixed_reorder_level=10,fixed_reorder_qty=20)]
        r=self.preview()[0]
        self.assertEqual((r["reorder_level"],r["reorder_qty"]),(10,20))
        self.assertEqual(r["suggested_replenishment"],0)

    def test_non_fg_is_mto(self):
        self.item.custom_inventory_group="RM"; self.policy.inventory_category="RM"
        r=self.preview()[0]
        self.assertEqual(r["production_mode"],"Make to Order")
        self.assertIn("reorder_level",r)
        self.assertEqual(r["suggested_replenishment"],0)

    def test_only_mapping_owned_reorder_row_is_comparison(self):
        self.reorder=[frappe._dict(name="legacy",parent="I",warehouse="A",warehouse_reorder_level=999,warehouse_reorder_qty=999)]
        r=self.preview()[0]
        self.assertEqual(r["previous_level"],0)
        self.assertEqual(r["legacy_reorder_rows"],["legacy"])

    def test_outdated_or_future_mapping_and_wrong_company(self):
        self.mapping.effective_to=date(2026,10,31)
        self.assertEqual(self.preview(),[])
        self.mapping.effective_to=None; self.mapping.company="Other"
        with self.assertRaises(ValueError): self.preview()

    def test_manual_seasonal_profile_and_period_override(self):
        self.profile=frappe._dict(mode="Manual",**{"month_"+str(m):1 for m in range(1,13)})
        self.policy.seasonal_profile="Season"
        r=self.preview(period_method="Month-to-Date Inclusive")[0]
        self.assertEqual(len(r["seasonal_indices"]),12)
        self.assertEqual(r["demand_period_method"],"Month-to-Date Inclusive")

    def test_active_legacy_override_cannot_expand_to_entire_mapping(self):
        self.overrides=[frappe._dict(enabled=1,mapping="M",item_code="I",warehouse="A")]
        row=self.preview()[0]
        self.assertEqual(row["status"],"Failed")
        self.assertIn("Legacy",row["reason"])

    def test_expired_override_is_optional_and_ignored(self):
        self.overrides=[frappe._dict(enabled=1,mapping="M",item_code="I",exclude_item=1,effective_to=date(2026,10,31))]
        self.assertIn("reorder_level",self.preview()[0])

    def test_automatic_seasonal_profile_uses_combined_history(self):
        from calendar import monthrange
        from qcmc_logic.dynamic_reorder_calculation import historical_months
        self.profile=frappe._dict(mode="Automatic",history_months=24)
        self.policy.seasonal_profile="Season"
        def demand(company,warehouses,items,start,end,deduct_returns=True,sources=None):
            return {("I",w,m):dict(gross=monthrange(m.year,m.month)[1]*10,returns=0,net=monthrange(m.year,m.month)[1]*10)
                    for w in warehouses for m,_ in historical_months(date(2026,11,1),24) if start<=m<=end}
        self.demand.side_effect=demand
        r=self.preview()[0]
        self.assertEqual(r["seasonal_indices"],{m:Decimal(1) for m in range(1,13)})
        self.assertEqual(r["reorder_level"],240)
        self.assertEqual(r["reorder_qty"],300)
        self.assertEqual(self.demand.call_count,2)

    def test_no_demand_preserves_existing_configuration(self):
        self.demand.return_value={}; self.demand.side_effect=None
        r=self.preview()[0]
        self.assertEqual(r["status"],"Skipped")
        self.assertNotIn("reorder_level",r)

    def test_managed_row_comparison_is_per_mapping(self):
        self.reorder=[frappe._dict(name="managed",parent="I",warehouse="A",custom_reorder_mapping="M",custom_managed_reorder=1,
                                  warehouse_reorder_level=364,warehouse_reorder_qty=455)]
        r=self.preview()[0]
        self.assertEqual((r["previous_level"],r["previous_qty"]),(364,455))
        self.assertEqual(r["status"],"Preview")
        self.reorder.append(self.reorder[0].copy())
        self.assertEqual(self.preview()[0]["status"],"Failed")
