from __future__ import annotations

import frappe
from frappe.model.document import Document
class GenerateLogs(Document):
    @frappe.whitelist()
    def generate_logs(self):
        self.set("logs", [])

        conditions = []
        params = {}

        if self.employee:
            conditions.append("ec.employee = %(employee)s")
            params["employee"] = self.employee

        if self.from_date:
            conditions.append("DATE(ec.time) >= %(from_date)s")
            params["from_date"] = self.from_date

        if self.to_date:
            conditions.append("DATE(ec.time) <= %(to_date)s")
            params["to_date"] = self.to_date

        where_sql = ""
        if conditions:
            where_sql = "WHERE " + " AND ".join(conditions)

        rows = frappe.db.sql(
            f"""
            SELECT
                sp.name AS area,
                e.employee_name AS employee_name,
                ec.log_type AS log_type,
                ec.time AS time,
                ec.creation AS creation,
                COALESCE(ec.custom_address, ec.custom_location_name) AS location
            FROM `tabEmployee Checkin` ec
            INNER JOIN `tabSales Person` sp ON sp.employee = ec.employee
            LEFT JOIN `tabEmployee` e ON e.name = ec.employee
            {where_sql}
            ORDER BY sp.name, e.employee_name, ec.time, ec.creation
            """,
            params,
            as_dict=True,
        )

        for row in rows:
            time_value = row.get("time") or row.get("creation")
            self.append(
                "logs",
                {
                    "area": row.get("area"),
                    "employee_name": row.get("employee_name"),
                    "log_type": row.get("log_type"),
                    "log_time": time_value,
                    "location": row.get("location"),
                },
            )

        self.save()
        return {"count": len(rows)}


@frappe.whitelist()
def generate_logs(name=None):
    if not name:
        name = frappe.form_dict.get("name") or frappe.form_dict.get("docname")
    if not name and frappe.form_dict.get("doc"):
        try:
            doc = frappe.get_doc(frappe.parse_json(frappe.form_dict.get("doc")))
            name = doc.name
        except Exception:
            name = None

    if not name:
        frappe.throw("Document name is required to generate logs.")

    doc = frappe.get_doc("Generate Logs", name)
    return doc.generate_logs()
