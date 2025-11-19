import frappe
import os
import json
from pyreportjasper.pyreportjasper import PyReportJasper
from datetime import date, datetime

@frappe.whitelist()
def generate_purchase_receipt_report(doc_name=None):
    try:
        jasper_folder = "/home/frappe/jasper_reports"
        template_file = os.path.join(jasper_folder, "Test.jrxml")  # JRXML file
        output_file = os.path.join(jasper_folder, f"{doc_name}.pdf")
        json_file = os.path.join("/tmp", f"purchase_receipt_data_{doc_name}.json")

        # Fetch data
        filters = {"name": doc_name} if doc_name else {}
        data = frappe.get_all(
            "Purchase Receipt",
            filters=filters,
            fields=["name", "supplier", "posting_date", "grand_total"],
            ignore_permissions=True
        )

        if not data:
            return f"No data found for {doc_name}"

        # Serialize dates to ISO format
        def default_serializer(obj):
            if isinstance(obj, (datetime, date)):
                return obj.isoformat()
            raise TypeError(f"Type {obj.__class__.__name__} not serializable")

        with open(json_file, "w", encoding="utf-8") as f:
            json.dump({"data": data}, f, default=default_serializer, ensure_ascii=False)

        # Generate PDF
        jasper = PyReportJasper()
        jasper.process(
            input_file=template_file,
            output_file=output_file,
            format_list=["pdf"],
            parameters={},
            db_connection={"driver": "json", "data_file": json_file}
        )

        # Attach PDF to Purchase Receipt
        with open(output_file, "rb") as f:
            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": f"{doc_name}.pdf",
                "attached_to_doctype": "Purchase Receipt",
                "attached_to_name": doc_name,
                "content": f.read(),
                "is_private": 0
            })
            file_doc.insert(ignore_permissions=True)

        return f"PDF report generated and attached for {doc_name}"

    except Exception as e:
        frappe.log_error(message=str(e), title="Jasper Report Error")
        raise
