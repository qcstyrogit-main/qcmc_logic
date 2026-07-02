"""
Create Job Card Downtime Custom DocType and wire up Job Card client script.
Run with: bench --site erp.qcstyro.local execute qcmc_logic.setup_job_card_downtime.run
"""
import frappe


def run():
    _set_downtime_reason_title_field()
    _create_doctype()
    _add_doctype_link()
    _create_client_script()
    frappe.db.commit()
    frappe.clear_cache()
    print("Job Card Downtime setup complete.")


# ---------------------------------------------------------------------------
# 1. Make Downtime Reason show description in Link search results
# ---------------------------------------------------------------------------

def _set_downtime_reason_title_field():
    if not frappe.db.exists("DocType", "Downtime Reason"):
        print("Downtime Reason not found — skipping title_field update.")
        return
    frappe.db.set_value("DocType", "Downtime Reason", "title_field", "description")
    frappe.clear_cache(doctype="Downtime Reason")
    print("Downtime Reason title_field set to 'description'.")


# ---------------------------------------------------------------------------
# 2. Create Job Card Downtime DocType
# ---------------------------------------------------------------------------

def _create_doctype():
    if frappe.db.exists("DocType", "Job Card Downtime"):
        print("DocType 'Job Card Downtime' already exists — skipping creation.")
        return

    dt = frappe.get_doc({
        "doctype": "DocType",
        "name": "Job Card Downtime",
        "module": "QCMC Logics",
        "custom": 1,
        "autoname": "JCD-.YY.-.####",
        "is_submittable": 0,
        "track_changes": 1,
        "search_fields": "job_card,work_order,downtime_reason",
        "title_field": "downtime_reason",
        "fields": [
            # ── Job Card Reference ─────────────────────────────────────────
            {
                "fieldname": "job_card",
                "label": "Job Card",
                "fieldtype": "Link",
                "options": "Job Card",
                "reqd": 1,
                "in_list_view": 1,
                "bold": 1,
                "columns": 2,
            },
            {
                "fieldname": "work_order",
                "label": "Work Order",
                "fieldtype": "Link",
                "options": "Work Order",
                "fetch_from": "job_card.work_order",
                "read_only": 1,
                "in_list_view": 1,
                "columns": 2,
            },
            {
                "fieldname": "operation",
                "label": "Operation",
                "fieldtype": "Data",
                "fetch_from": "job_card.operation",
                "read_only": 1,
            },
            {
                "fieldname": "workstation",
                "label": "Workstation",
                "fieldtype": "Link",
                "options": "Workstation",
                "fetch_from": "job_card.workstation",
                "read_only": 1,
            },
            {
                "fieldname": "company",
                "label": "Company",
                "fieldtype": "Link",
                "options": "Company",
                "fetch_from": "job_card.company",
                "read_only": 1,
            },
            {
                "fieldname": "posting_date",
                "label": "Date",
                "fieldtype": "Date",
                "reqd": 1,
                "default": "Today",
                "in_list_view": 1,
                "columns": 1,
            },
            {"fieldname": "col_break_1", "fieldtype": "Column Break"},
            # ── Time ──────────────────────────────────────────────────────
            {
                "fieldname": "from_time",
                "label": "From Time",
                "fieldtype": "Datetime",
                "reqd": 1,
                "in_list_view": 1,
                "columns": 2,
            },
            {
                "fieldname": "to_time",
                "label": "To Time",
                "fieldtype": "Datetime",
                "in_list_view": 1,
                "columns": 2,
            },
            {
                "fieldname": "duration_minutes",
                "label": "Duration (minutes)",
                "fieldtype": "Float",
                "read_only": 1,
                "in_list_view": 1,
                "columns": 1,
            },
            # ── Downtime Details ──────────────────────────────────────────
            {"fieldname": "sec_downtime", "label": "Downtime Details", "fieldtype": "Section Break"},
            {
                "fieldname": "downtime_reason",
                "label": "Downtime Reason",
                "fieldtype": "Link",
                "options": "Downtime Reason",
                "reqd": 1,
                "in_list_view": 1,
                "bold": 1,
                "columns": 2,
            },
            {
                "fieldname": "category",
                "label": "Category",
                "fieldtype": "Data",
                "read_only": 1,
                "in_list_view": 0,
            },
            {
                "fieldname": "subcategory",
                "label": "Sub-Category",
                "fieldtype": "Data",
                "read_only": 1,
                "in_list_view": 0,
            },
            {"fieldname": "col_break_2", "fieldtype": "Column Break"},
            {
                "fieldname": "remarks",
                "label": "Remarks",
                "fieldtype": "Small Text",
            },
        ],
        "permissions": [
            {
                "role": "System Manager",
                "permlevel": 0,
                "read": 1, "write": 1, "create": 1, "delete": 1,
                "print": 1, "email": 1, "report": 1, "export": 1,
            },
            {
                "role": "Manufacturing User",
                "permlevel": 0,
                "read": 1, "write": 1, "create": 1,
                "print": 1, "email": 1, "report": 1, "export": 1,
            },
            {
                "role": "Manufacturing Manager",
                "permlevel": 0,
                "read": 1, "write": 1, "create": 1, "delete": 1,
                "print": 1, "email": 1, "report": 1, "export": 1,
            },
            {
                "role": "All",
                "permlevel": 0,
                "read": 1,
            },
        ],
    })
    dt.insert(ignore_permissions=True)
    print("DocType 'Job Card Downtime' created.")


# ---------------------------------------------------------------------------
# 3. Wire Job Card → Job Card Downtime in the connections panel
# ---------------------------------------------------------------------------

def _add_doctype_link():
    exists = frappe.db.exists(
        "DocType Link",
        {"parent": "Job Card", "link_doctype": "Job Card Downtime"},
    )
    if exists:
        print("DocType Link (Job Card → Job Card Downtime) already exists.")
        return

    frappe.get_doc({
        "doctype": "DocType Link",
        "parent": "Job Card",
        "parenttype": "DocType",
        "parentfield": "links",
        "link_doctype": "Job Card Downtime",
        "link_fieldname": "job_card",
        "group": "Downtime",
    }).insert(ignore_permissions=True)
    print("DocType Link added: Job Card → Job Card Downtime.")


# ---------------------------------------------------------------------------
# 4. Client script: Log Downtime button on Job Card
# ---------------------------------------------------------------------------

CLIENT_SCRIPT_NAME = "Job Card - Log Downtime Button"

CLIENT_SCRIPT_JS = r"""
frappe.ui.form.on("Job Card", {
    refresh(frm) {
        if (frm.is_new() || frm.doc.docstatus === 2) return;

        frm.add_custom_button(__("Log Downtime"), function () {
            frappe.new_doc("Job Card Downtime", {
                job_card:     frm.doc.name,
                work_order:   frm.doc.work_order,
                operation:    frm.doc.operation,
                workstation:  frm.doc.workstation,
                company:      frm.doc.company,
                posting_date: frappe.datetime.get_today(),
                from_time:    frappe.datetime.now_datetime(),
            });
        }, __("Downtime"));

        frm.add_custom_button(__("View Downtime Log"), function () {
            frappe.set_route("List", "Job Card Downtime", { job_card: frm.doc.name });
        }, __("Downtime"));
    },
});
"""


def _create_client_script():
    if frappe.db.exists("Client Script", CLIENT_SCRIPT_NAME):
        cs = frappe.get_doc("Client Script", CLIENT_SCRIPT_NAME)
        cs.script = CLIENT_SCRIPT_JS
        cs.enabled = 1
        cs.flags.ignore_permissions = True
        cs.save()
        print(f"Client Script '{CLIENT_SCRIPT_NAME}' updated.")
    else:
        frappe.get_doc({
            "doctype": "Client Script",
            "name": CLIENT_SCRIPT_NAME,
            "dt": "Job Card",
            "script": CLIENT_SCRIPT_JS,
            "enabled": 1,
            "view": "Form",
        }).insert(ignore_permissions=True)
        print(f"Client Script '{CLIENT_SCRIPT_NAME}' created.")
