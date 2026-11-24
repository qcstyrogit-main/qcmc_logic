// Operational picking status is independent from ERPNext document status.
frappe.provide("qcmc_logic.picking_status");

qcmc_logic.picking_status.refresh = async function(frm) {
    const supported = frm.doctype === "Delivery Note"
        ? !frm.doc.is_return
        : frm.doctype === "Stock Entry" &&
          ["Material Issue", "Material Transfer for Manufacture"].includes(frm.doc.stock_entry_type) &&
          frm.doc.purpose === frm.doc.stock_entry_type;
    const selector = ".qcmc-picking-status-indicator";
    frm.dashboard?.stats_area_row?.find(selector).remove();
    if (!supported || frm.is_new()) return;
    const name = frm.doc.name;
    try {
        const result = await frappe.xcall("qcmc_logic.picking_status.get_status", {
            doctype: frm.doctype, name,
        });
        if (name !== frm.doc.name || frm.is_new()) return;
        const value = result?.status || "Not Started";
        const palette = {
            "Not Started": "grey",
            "Not Required": "grey",
            "Pending Picking": "orange",
            "Picking Completed": "green",
            "Submitted": "blue",
            "Cancelled": "red",
        };
        // This is a presentation-only update: never dirty a draft.
        frm.doc.custom_picking_status = value;
        const instruction = value === "Picking Completed"
            ? (frm.doctype === "Delivery Note"
                ? __("Picking Completed — Ready for Stock Confirmation")
                : __("Picking Completed — Ready for Submission"))
            : __("Read-only picking progress, independent of document workflow status.");
        frm.set_df_property("custom_picking_status", "description", instruction);
        frm.refresh_field("custom_picking_status");
        frm.dashboard?.stats_area_row?.find(selector).remove();
        const display = value === "Picking Completed"
            ? (frm.doctype === "Delivery Note"
                ? __("Picking Completed — Ready for Stock Confirmation")
                : __("Picking Completed — Ready for Submission"))
            : __("Picking Status") + ": " + __(value);
        frm.dashboard?.add_indicator(
            frappe.utils.escape_html(display),
            palette[value] || "grey"
        )?.addClass("qcmc-picking-status-indicator");
    } catch (error) {
        console.warn("Unable to load picking status", error);
    }
};
