"""Single business calendar for dynamic reorder; independent of site timezone."""
from datetime import datetime
from zoneinfo import ZoneInfo

def business_now():
    return datetime.now(ZoneInfo("Asia/Manila"))

def business_date():
    return business_now().date()
