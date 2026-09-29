import frappe


PRINT_FORMAT = "PR_Form_Jinja"
OLD_ATTENTION = (
    '<div class="info-cell info-left"> <strong>Attention :</strong> '
    '</N> PROCUREMENT DEPT.</div>'
)
NEW_ATTENTION = '''{% set received_log = frappe.get_all("Comment", filters={"reference_doctype": "Material Request", "reference_name": doc.name, "comment_type": "Workflow", "content": ["like", "%Received%"]}, fields=["owner"], order_by="creation desc", limit=1) %}
    <div class="info-cell info-left"><strong>Attention :</strong> {{ frappe.db.get_value("User", received_log[0].owner, "full_name") if received_log else "" }}</div>'''


def execute():
    """Show the user who moved a Purchase Request to Received in Attention.

    Print Format fixtures are synchronized after normal migration patches. This
    function is therefore registered as an after_migrate hook, so it runs after
    the fixture has restored the standard template.
    """
    if not frappe.db.exists("Print Format", PRINT_FORMAT):
        return

    html = frappe.db.get_value("Print Format", PRINT_FORMAT, "html") or ""
    if NEW_ATTENTION in html or OLD_ATTENTION not in html:
        return

    frappe.db.set_value(
        "Print Format", PRINT_FORMAT, "html", html.replace(OLD_ATTENTION, NEW_ATTENTION)
    )
    frappe.clear_cache(doctype="Print Format")
