frappe.query_reports["SO DR Service Level"] = {
    filters: [
        {fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.month_start()},
        {fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.month_end()},
        {fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company"},
        {fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer"},
        {fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order"},
        {fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item"}
    ],
    formatter(value, row, column, data, default_formatter) {
        if (column.fieldname === "delivery_notes" && data && data.delivery_notes) {
            return String(data.delivery_notes).split(",").map(name => name.trim()).filter(Boolean).map(name => {
                const href = "/desk/delivery-note/" + encodeURIComponent(name);
                return '<a href="' + href + '" class="link-option">' + frappe.utils.escape_html(name) + '</a>';
            }).join(", ");
        }
        let out = default_formatter(value, row, column, data);
        if (column.fieldname === "otif" && data) {
            const cls = data.otif === "Pass" ? "text-success" : data.otif === "Not Yet Due" || data.otif === "Unreconciled" ? "text-muted" : "text-danger";
            out = '<span class="' + cls + '">' + out + '</span>';
        }
        return out;
    }
};