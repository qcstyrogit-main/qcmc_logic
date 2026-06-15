frappe.listview_settings["Employee Attendance Schedule"] = {
    onload(listview) {
        setup_attendance_schedule_viewer_list(listview);
    },

    refresh(listview) {
        setup_attendance_schedule_viewer_list(listview);
    }
};

function setup_attendance_schedule_viewer_list(listview) {
    apply_viewer_list_titles(listview);
    prevent_attendance_schedule_navigation();
    redirect_to_attendance_schedule_viewer();
}

function is_attendance_schedule_list_route() {
    const route = frappe.get_route ? frappe.get_route() : [];
    return route && route[0] === "List" && route[1] === "Employee Attendance Schedule";
}

function apply_viewer_list_titles(listview) {
    const sourceTitle = "Employee Attendance Schedule";
    const viewerTitle = __("Employee Attendance Viewer");

    if (listview && listview.page && listview.page.set_title) {
        listview.page.set_title(viewerTitle);
    }

    [0, 100, 300, 800].forEach((delay) => {
        setTimeout(() => neutralize_attendance_schedule_list_chrome(sourceTitle, viewerTitle), delay);
    });

    if (window.__eas_viewer_list_observer) {
        return;
    }

    window.__eas_viewer_list_observer = new MutationObserver(() => {
        if (is_attendance_schedule_list_route()) {
            neutralize_attendance_schedule_list_chrome(sourceTitle, viewerTitle);
        }
    });
    window.__eas_viewer_list_observer.observe(document.body, { childList: true, subtree: true });
}

function neutralize_attendance_schedule_list_chrome(sourceTitle, viewerTitle) {
    if (!is_attendance_schedule_list_route()) {
        return;
    }

    [
        ".breadcrumb .breadcrumb-item.active",
        ".page-breadcrumbs .breadcrumb-item.active",
        ".page-head .title-text"
    ].forEach((selector) => {
        $(selector).each(function() {
            const text = ($(this).text() || "").trim();
            if (text === sourceTitle) {
                $(this).text(viewerTitle);
            }
        });
    });

    $(".breadcrumb a, .page-breadcrumbs a").each(function() {
        const text = ($(this).text() || "").trim();
        if (text !== sourceTitle && text !== viewerTitle) return;

        $(this).replaceWith(
            $("<span class=\"eas-viewer-breadcrumb-text\"></span>").text(viewerTitle)
        );
    });

    $(".frappe-list a, .result a, .list-row-container a").each(function() {
        const href = $(this).attr("href") || "";
        const route = $(this).attr("data-route") || "";
        if (!href.includes("/app/employee-attendance-schedule/") && !route.includes("Employee Attendance Schedule")) {
            return;
        }

        $(this)
            .removeAttr("href")
            .removeAttr("data-route")
            .css({ cursor: "default", color: "inherit" });
    });
}

function prevent_attendance_schedule_navigation() {
    if (window.__eas_viewer_list_click_guard) {
        return;
    }

    window.__eas_viewer_list_click_guard = true;
    document.addEventListener("click", (event) => {
        if (!is_attendance_schedule_list_route()) {
            return;
        }

        const target = event.target;
        if ($(target).closest("input, button, select, textarea, .btn, .dropdown-menu, .filter-box, .list-paging-area, .list-row-checkbox, .checkbox, .avatar").length) {
            return;
        }

        const docLink = $(target).closest("a[href*='/app/employee-attendance-schedule/'], a[data-route*='Employee Attendance Schedule']");
        const docRow = $(target).closest(".list-row-container, .list-row, [data-name]");
        if (!docLink.length && !docRow.closest(".frappe-list, .result").length) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        neutralize_attendance_schedule_list_chrome(
            "Employee Attendance Schedule",
            __("Employee Attendance Viewer")
        );
    }, true);
}

function redirect_to_attendance_schedule_viewer() {
    if (!is_attendance_schedule_list_route() || window.__eas_viewer_redirecting) {
        return;
    }

    window.__eas_viewer_redirecting = true;

    frappe.db.get_list("Employee Attendance Schedule", {
        fields: ["name"],
        limit: 1,
        order_by: "creation asc"
    }).then((rows) => {
        if (rows && rows.length) {
            frappe.set_route("Form", "Employee Attendance Schedule", rows[0].name);
            return;
        }

        window.__eas_viewer_redirecting = false;
    }).catch(() => {
        window.__eas_viewer_redirecting = false;
    });

    setTimeout(() => {
        window.__eas_viewer_redirecting = false;
    }, 1500);
}
