frappe.query_reports["Storage Location Summary"] = {
    tree: true,
    name_field: "node_id",
    parent_field: "parent_node",
    after_datatable_render(datatable) {
        datatable.rowmanager.expandAllNodes();
    },
    filters: [
        {
            fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse", reqd: 1,
            default: frappe.defaults.get_user_default("Warehouse"),
            get_query: () => ({filters: {is_group: 0, disabled: 0}}),
        },
        {
            fieldname: "storage_location", label: __("Storage Location Branch"), fieldtype: "Link", options: "Storage Location",
            get_query: () => ({filters: {disabled: 0}}),
        },
        {fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item"},
        {fieldname: "show_empty_locations", label: __("Show Empty Locations"), fieldtype: "Check", default: 0},
    ],
    onload(report) {
        report.page.add_inner_button(__("Storage Location Tree"), () => frappe.set_route("Tree", "Storage Location"));
        if (!report.get_filter_value("warehouse")) {
            frappe.call("qcmc_logic.utils.get_default_warehouse_for_user").then(response => {
                if (response.message && !report.get_filter_value("warehouse")) {
                    report.set_filter_value("warehouse", response.message);
                }
            });
        }
    },
    formatter(value, row, column, data, default_formatter) {
        if (["capacity", "available_capacity"].includes(column.fieldname) && data?.capacity_unlimited) return __("Unlimited");
        if (["capacity", "used_capacity", "available_capacity", "use_percentage"].includes(column.fieldname)) {
            if (data?.[column.fieldname] == null) return "";
            const formatted = default_formatter(value, row, column, data);
            return column.fieldname === "use_percentage" ? `${formatted}%` : formatted;
        }
        if (column.fieldname === "stock_qty" && data && data.stock_qty == null) return "";
        return default_formatter(value, row, column, data);
    },
};
