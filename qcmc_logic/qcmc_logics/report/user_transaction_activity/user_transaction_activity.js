frappe.query_reports["User Transaction Activity"] = {
    filters: [
        {fieldname: "created_from", label: __("Created From"), fieldtype: "Date"},
        {fieldname: "created_to", label: __("Created To"), fieldtype: "Date"},
    ],
};
