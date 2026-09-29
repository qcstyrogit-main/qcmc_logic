import frappe


CLIENT_SCRIPT = "PO Setting Default Print Format"

SCRIPT = """
frappe.ui.form.on("Purchase Order", {
    refresh(frm) {
        frm.page.remove_menu_item("Print");
        frm.page.add_menu_item(__("Print"), function() {
            frappe.call({
                method: "qcmc_logic.overrides.POPrint_Override.get_po_print_format",
                args: { doctype: frm.doc.doctype, name: frm.doc.name },
                callback(r) {
                    if (!r.message) {
                        frappe.msgprint("No print format returned.");
                        return;
                    }
                    const pdf_url = frappe.urllib.get_full_url(
                        "/api/method/frappe.utils.print_format.download_pdf?"
                        + "doctype=" + encodeURIComponent(frm.doc.doctype)
                        + "&name=" + encodeURIComponent(frm.doc.name)
                        + "&format=" + encodeURIComponent(r.message)
                        + "&no_letterhead=0"
                    );
                    window.open(pdf_url, "_blank");
                }
            });
        });
    }
});
""".strip()


def execute():
    """Use the server-generated PDF path for dot-matrix Purchase Order printing."""
    if not frappe.db.exists("Client Script", CLIENT_SCRIPT):
        return

    frappe.db.set_value(
        "Client Script",
        CLIENT_SCRIPT,
        {"enabled": 1, "script": SCRIPT},
        update_modified=False,
    )
    frappe.clear_cache(doctype="Client Script")
