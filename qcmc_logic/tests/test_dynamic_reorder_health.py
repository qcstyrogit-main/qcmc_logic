import unittest
from qcmc_logic.dynamic_reorder_health import classify

class TestInventoryHealth(unittest.TestCase):
    def row(self, projected=200, actual=200, **kwargs):
        return dict(status="Preview",net_demand=1000,projected_qty=projected,
            actual_qty=actual,safety_stock=50,reorder_level=120,forecast_daily=10,
            policy_snapshot={"maximum_stock":0,"overstock_coverage_days":90},**kwargs)
    def test_critical_boundary(self):
        self.assertEqual(classify(self.row(50))[0],"Critical Stock")
    def test_reorder_boundary(self):
        self.assertEqual(classify(self.row(120))[0],"Reorder Required")
    def test_healthy(self):
        self.assertEqual(classify(self.row())[0],"Healthy Stock")
    def test_overstock_days(self):
        self.assertEqual(classify(self.row(901))[0],"Overstock")
        self.assertEqual(classify(self.row(900))[0],"Healthy Stock")
    def test_maximum(self):
        r=self.row()
        r["policy_snapshot"]["maximum_stock"]=199
        self.assertEqual(classify(r)[0],"Overstock")
    def test_disabled_limits(self):
        r=self.row(5000)
        r["policy_snapshot"]["overstock_coverage_days"]=0
        self.assertEqual(classify(r)[0],"Healthy Stock")
    def test_no_demand(self):
        r=self.row()
        r["net_demand"]=0
        self.assertEqual(classify(r)[0],"No Demand")
    def test_missing(self):
        self.assertEqual(classify({"status":"Skipped"})[0],"Not Evaluated")
    def test_sample(self):
        r=self.row(7549860,7549860)
        r["forecast_daily"]=4000/90
        self.assertEqual(classify(r)[0],"Overstock")
