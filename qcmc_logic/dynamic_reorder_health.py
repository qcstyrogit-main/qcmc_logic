"""Read-only inventory health classification using recommended thresholds."""
from qcmc_logic.dynamic_reorder_calculation import number

HEALTH = ("Critical Stock", "Reorder Required", "Healthy Stock", "Overstock", "No Demand", "Not Evaluated")

def classify(row):
    if row.get("status") == "Failed" or row.get("net_demand") is None:
        return "Not Evaluated", "No reliable demand calculation"
    net = number(row["net_demand"])
    if net < 0:
        return "Not Evaluated", "Negative net demand requires review"
    if net == 0:
        return "No Demand", "No qualifying net historical demand"
    required = ("projected_qty", "actual_qty", "safety_stock", "reorder_level", "forecast_daily")
    if any(row.get(k) is None for k in required):
        return "Not Evaluated", "Incomplete stock or recommendation values"
    policy = row.get("policy_snapshot") or {}
    projected = number(row["projected_qty"])
    actual = number(row["actual_qty"])
    safety = number(row["safety_stock"])
    rol = number(row["reorder_level"])
    daily = number(row["forecast_daily"])
    maximum = number(policy.get("maximum_stock") or 0)
    raw_limit = policy.get("overstock_coverage_days")
    limit = number(90 if raw_limit is None else raw_limit)
    if limit < 0 or maximum < 0 or daily <= 0:
        return "Not Evaluated", "Invalid inventory health thresholds or forecast"
    if projected <= safety:
        return "Critical Stock", "Projected stock at or below safety stock"
    if projected <= rol:
        return "Reorder Required", "Projected stock at or below recommended reorder level"
    if maximum > 0 and max(actual, projected) > maximum:
        return "Overstock", "Actual or projected stock exceeds maximum stock"
    if limit > 0 and max(actual, projected) / daily > limit:
        return "Overstock", "Actual or projected stock coverage exceeds configured days"
    return "Healthy Stock", "Projected stock above reorder level and within enabled limits"
