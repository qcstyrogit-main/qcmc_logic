"""
Set search_fields = "machine" on Machine Shop Repairs and Project Process doctype
so the machine name appears as secondary text in the Process link field dropdown.

Run with:
    bench --site erp.qcstyro.local execute qcmc_logic.patch_process_search_fields.run
"""
import json
import os
import frappe

DOCTYPE_NAME = "Machine Shop Repairs and Project Process"
SEARCH_FIELDS = "machine"


def run():
    # Update DB
    frappe.db.set_value("DocType", DOCTYPE_NAME, "search_fields", SEARCH_FIELDS, update_modified=False)
    frappe.db.commit()
    frappe.clear_cache(doctype=DOCTYPE_NAME)
    print(f"DB updated: search_fields = '{SEARCH_FIELDS}' on {DOCTYPE_NAME}")

    # Update fixture
    app_path = frappe.get_app_path("qcmc_logic")
    fixture_path = os.path.join(app_path, "fixtures", "doctype.json")
    with open(fixture_path) as f:
        docs = json.load(f)

    updated = False
    for d in docs:
        if d.get("name") == DOCTYPE_NAME:
            d["search_fields"] = SEARCH_FIELDS
            updated = True
            break

    if not updated:
        print(f"WARNING: {DOCTYPE_NAME} not found in fixture — no fixture change made.")
    else:
        with open(fixture_path, "w") as f:
            json.dump(docs, f, indent=1, ensure_ascii=False)
        print("Fixture doctype.json updated.")

    print("Done.")
