"""Pure calculation primitives for QCMC Dynamic Reorder Management.

No Frappe dependency, database writes, or Material Request creation.
"""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING
from fractions import Fraction
from math import lcm


def number(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Non-finite quantity")
    return result


def historical_months(as_of, months=3):
    if not isinstance(months, int) or not 1 <= months <= 36:
        raise ValueError("Historical period must be 1–36 months")
    end = as_of.replace(day=1)
    result = []
    for _ in range(months):
        last = end - timedelta(days=1)
        start = last.replace(day=1)
        result.append((start, last))
        end = start
    return list(reversed(result))


def demand_period(as_of, method="Complete Calendar Months", months=3, rolling_days=90):
    """Return inclusive historical date segments, grouped by calendar month.
    The calculation date itself is excluded to avoid partial-day demand.
    """
    if method == "Complete Calendar Months":
        return historical_months(as_of, months)
    end = as_of - timedelta(days=1)
    if method == "Rolling Days":
        if not isinstance(rolling_days,int) or not 1 <= rolling_days <= 1096:
            raise ValueError("Rolling days must be 1–1096")
        start = as_of - timedelta(days=rolling_days)
    elif method == "Month-to-Date Inclusive":
        # Include previous N complete months plus elapsed current-month days.
        start = historical_months(as_of, months)[0][0]
    else:
        raise ValueError("Unknown demand period method")
    result=[]
    while start <= end:
        last=min(end,start.replace(day=monthrange(start.year,start.month)[1]))
        result.append((start,last))
        start=last+timedelta(days=1)
    return result


def seasonal_indices(history):
    """History: distinct complete months as (first_day, net_stock_qty)."""
    by_month = {}
    seen = set()
    for month, qty in history:
        if month.day != 1 or month in seen:
            raise ValueError("Expected distinct complete months")
        seen.add(month)
        days = monthrange(month.year, month.month)[1]
        q = number(qty)
        if q < 0:
            raise ValueError("Negative monthly demand requires review")
        by_month.setdefault(month.month, []).append((q, days))
    if len(seen) < 24 or any(len(by_month.get(m, [])) < 2 for m in range(1, 13)):
        return None
    averages = {m: sum(q for q, d in rows) / sum(d for q, d in rows)
                for m, rows in by_month.items()}
    mean = sum(averages.values()) / 12
    if mean <= 0 or any(v <= 0 for v in averages.values()):
        return None
    return {m: v / mean for m, v in averages.items()}


def round_up(value, *multiples):
    fractions = [Fraction(number(m)) for m in multiples if number(m) > 0]
    if not fractions:
        return number(value)
    step = Fraction(lcm(*(f.numerator for f in fractions)), 1)
    from math import gcd
    step /= gcd(*(f.denominator for f in fractions))
    units = Fraction(number(value)) / step
    rounded = ((units.numerator + units.denominator - 1) // units.denominator) * step
    return Decimal(rounded.numerator) / Decimal(rounded.denominator)


def change_percent(previous, proposed):
    previous, proposed = number(previous), number(proposed)
    if previous == 0:
        return Decimal(0) if proposed == 0 else None
    return (proposed - previous) * 100 / previous


def calculate(as_of, history, *, lead=7, safety=5, coverage=15,
              minimum=0, maximum=0, moq=0, multiple=0, batch=0,
              precision=0, indices=None, previous_level=0, previous_qty=0,
              projected=0, increase_limit=30, decrease_limit=20,
              preserve_no_demand=True, periods=None):
    """Return recommendation and review flags; history maps first days to net demand."""
    if not history:
        return {"status": "Skipped", "reason": "No valid demand history"}
    if not all(isinstance(v, int) and 0 <= v <= 3660 for v in (lead, safety, coverage)):
        raise ValueError("Invalid forecast horizon")
    if not isinstance(precision, int) or not 0 <= precision <= 9:
        raise ValueError("Invalid stock precision")
    for v in (minimum, maximum, moq, multiple, batch, previous_level, previous_qty,
              increase_limit, decrease_limit):
        if number(v) < 0:
            raise ValueError("Negative policy value")
    if number(maximum) and number(maximum) < number(minimum):
        raise ValueError("Maximum below minimum")
    if indices is not None and (set(indices) != set(range(1, 13)) or
                                any(number(v) <= 0 for v in indices.values())):
        raise ValueError("Seasonal indices must be positive for all 12 months")
    periods = historical_months(as_of, len(history)) if periods is None else list(periods)
    if not periods:
        raise ValueError("Empty historical period")
    expected = {start.replace(day=1) for start,_ in periods}
    if set(history) != expected or len(expected)!=len(periods):
        raise ValueError("History must match distinct period months")
    for i,(start,end) in enumerate(periods):
        if start>end or end>=as_of or start.replace(day=1)!=end.replace(day=1):
            raise ValueError("Invalid historical segment")
        if i and start!=periods[i-1][1]+timedelta(days=1):
            raise ValueError("Historical segments must be consecutive")
    days = sum((end-start).days+1 for start,end in periods)
    factor = lambda m: number(indices[m]) if indices else Decimal(1)
    total = sum(number(q) for q in history.values())
    if any(number(q) < 0 for q in history.values()):
        return {"status": "Pending Approval", "reason": "Negative monthly net demand"}
    if total == 0 and preserve_no_demand:
        return {"status": "Skipped", "reason": "Zero demand; existing settings preserved",
                "historical_days": days, "net_demand": total, "average_daily": Decimal(0)}
    baseline = sum(number(q) / factor(m.month) for m, q in history.items()) / days
    def forecast(start, horizon):
        return sum((baseline * factor((start + timedelta(days=i)).month)
                    for i in range(horizon)), Decimal(0))
    safety_qty = forecast(as_of + timedelta(days=lead), safety)
    quantum = Decimal(1).scaleb(-precision)
    level = round_up(max(number(minimum), forecast(as_of, lead) + safety_qty), quantum)
    demand_qty = forecast(as_of, coverage)
    qty = round_up(max(number(moq), demand_qty), quantum, multiple, batch) if demand_qty > 0 else Decimal(0)
    flags = []
    if number(maximum) and (level > number(maximum) or level + qty > number(maximum)):
        flags.append("Maximum stock requires review; standard ERPNext is not order-to-max")
    changes = [change_percent(previous_level, level), change_percent(previous_qty, qty)]
    if any(c is None or c > number(increase_limit) or c < -number(decrease_limit) for c in changes):
        flags.append("Change exceeds automatic limits or previous value was zero")
    projected = number(projected)
    suggested = max(qty, level - projected) if (level or qty) and projected <= level else Decimal(0)
    return {"status": "Pending Approval" if flags else "Preview", "reason": "; ".join(flags),
            "net_demand": total, "historical_days": days, "average_daily": total / days,
            "baseline_daily": baseline, "forecast_daily": baseline * factor(as_of.month),
            "safety_stock": safety_qty, "reorder_level": level, "reorder_qty": qty,
            "level_change_pct": changes[0], "qty_change_pct": changes[1],
            "suggested_replenishment": suggested}
