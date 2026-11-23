"""Create the WTS-specific handover record, reusing existing Assign Checker IDs.

Registered in patches.txt for automatic deployment. To run manually:
bench --site erp.qcstyro.local execute qcmc_logic.patches.setup_wts_handover_doctype.execute

This is an additive custom DocType; it does not migrate or modify the
existing Manufacturing handovers or Warehouse Transfer stock ledgers.
"""
import frappe


FIELDS = [
    ("warehouse_transfer", "Link", "Warehouse Transfer", 1),
    ("status", "Select", "CHECKED\nALLOCATION_CREATED\nCOMPLETED\nCANCELLED", 1),
    ("source_warehouse", "Link", "Warehouse", 1),
    ("target_warehouse", "Link", "Warehouse", 1),
    ("checker", "Link", "Assign Checker", 1),
    ("checker_employee", "Link", "Employee", 0),
    ("checker_user", "Link", "User", 1),
    ("checked_at", "Datetime", None, 1),
    ("verified_quantities_json", "Long Text", None, 1),
    ("extra_items_json", "Long Text", None, 0),
    ("check_date", "Date", None, 0),
    ("has_discrepancy", "Check", None, 0),
    ("source_fingerprint", "Data", None, 1),
    ("handover_token", "Password", None, 1),
    ("expires_at", "Datetime", None, 1),
    ("picker", "Link", "Employee", 0),
    ("device_id", "Data", None, 0),
    ("completed_at", "Datetime", None, 0),
]


def execute():
    name = "Scanner WTS Handover"
    if frappe.db.exists("DocType", name):
        doc = frappe.get_doc("DocType", name)
        fields = {field.fieldname for field in doc.fields}
        optional_additions = {"extra_items_json", "check_date", "has_discrepancy"}
        missing = [fieldname for fieldname, *_ in FIELDS if fieldname not in fields]
        unknown = set(missing) - optional_additions
        if unknown:
            raise RuntimeError("Existing Scanner WTS Handover is missing original fields: " + ", ".join(sorted(unknown)))
        changed = False
        for fieldname, fieldtype, options, _required in FIELDS:
            if fieldname in missing:
                doc.append("fields", {
                    "fieldname": fieldname, "label": fieldname.replace("_", " ").title(),
                    "fieldtype": fieldtype,
                    **({"options": options} if options else {}),
                    "read_only": 1,
                })
                changed = True
        checker_employee = next((field for field in doc.fields if field.fieldname == "checker_employee"), None)
        if checker_employee and checker_employee.reqd:
            checker_employee.reqd = 0
            changed = True
        if changed:
            doc.save(ignore_permissions=True)
            frappe.db.commit()
            frappe.clear_cache(doctype=name)
            print("Updated Scanner WTS Handover for discrepancy recording")
        else:
            print(name + " already exists, schema preserved")
        return {"created": False, "updated": changed}
    doc = frappe.get_doc({
        "doctype": "DocType",
        "name": name,
        "module": "QCMC Logics",
        "custom": 1,
        "autoname": "field:warehouse_transfer",
        "track_changes": 1,
        "fields": [
            {
                "fieldname": fieldname,
                "label": fieldname.replace("_", " ").title(),
                "fieldtype": fieldtype,
                **({"options": options} if options else {}),
                **({"reqd": 1} if required and fieldname not in {"handover_token", "source_fingerprint"} else {}),
                **({"hidden": 1} if fieldname in {"handover_token", "source_fingerprint"} else {}),
                **({"read_only": 1} if fieldname not in {"device_id"} else {}),
            }
            for fieldname, fieldtype, options, required in FIELDS
        ],
        "permissions": [
            {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "Stock Manager", "read": 1, "write": 1, "create": 1},
            {"role": "Warehouse Checker", "read": 1},
            {"role": "Warehouse Picker", "read": 1},
        ],
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache(doctype=name)
    print("Created custom DocType " + name)
    return {"created": True}
