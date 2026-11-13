(() => {
    const settings = frappe.listview_settings["Material Request"] || {};
    const original_onload = settings.onload;
    settings.onload = function (listview) {
        original_onload?.call(this, listview);
        if (listview.qcmc_approval_history) return;
        listview.qcmc_approval_history = true;
        let ready = false;
        let saved_value = 0;
        // Remove any invalid filter retained from the earlier toolbar control.
        const get_filters = listview.get_filters_for_args.bind(listview);
        listview.get_filters_for_args = function () {
            return get_filters().filter(filter =>
                filter[filter.length >= 4 ? 1 : 0] !== "qcmc_include_previously_approved"
            );
        };
        // Count caching cannot distinguish personal visibility preferences.
        listview.count_upper_bound = 0;
        listview.page.show_form();
        // add_check deliberately does not register in page.fields_dict, which
        // Frappe treats as database filters. This is a preference, not a field.
        const checkbox = listview.page.add_check(__("Include requests I previously approved"));
        checkbox.closest(".checkbox").css({
            flex: "0 0 100%",
            maxWidth: "100%",
            whiteSpace: "normal",
        });
        checkbox.prop("disabled", true);
        checkbox.on("change", async () => {
            if (!ready) return;
            const enabled = checkbox.prop("checked") ? 1 : 0;
            ready = false;
            checkbox.prop("disabled", true);
            try {
                const response = await frappe.call({
                    method: "qcmc_logic.customs.purchase_request_history.set_history_preference",
                    args: { enabled },
                });
                saved_value = response.message;
                listview.start = 0;
                listview.last_args = null;
                await listview.refresh();
                if (saved_value) {
                    const { message: count } = await frappe.call({
                        method: "qcmc_logic.customs.purchase_request_history.get_previous_approval_count",
                    });
                    frappe.show_alert({
                        message: count
                            ? __("Your recorded previous approvals are included. Existing list filters still apply.")
                            : __("No recorded previous approvals were found for your account. The list is unchanged."),
                        indicator: count ? "green" : "orange",
                    }, 8);
                } else {
                    frappe.show_alert({
                        message: __("Showing your usual accessible requests."),
                        indicator: "green",
                    });
                }
            } finally {
                checkbox.prop("checked", Boolean(saved_value)).prop("disabled", false);
                ready = true;
            }
        });
        frappe.call({
            method: "qcmc_logic.customs.purchase_request_history.get_history_preference",
        }).then(({ message }) => {
            saved_value = message || 0;
            checkbox.prop("checked", Boolean(saved_value)).prop("disabled", false);
            ready = true;
            listview.last_args = null;
            listview.refresh();
        });
    };
    frappe.listview_settings["Material Request"] = settings;
})();
