frappe.ui.form.on("Employee Attendance Schedule", {
    async setup(frm) {
        setup_employee_attendance_defaults(frm);
        setup_employee_attendance_colored_viewer(frm);
    },

    async onload(frm) {
        setup_employee_attendance_defaults(frm);
        setup_employee_attendance_colored_viewer(frm);
    },

    async refresh(frm) {
        setup_employee_attendance_defaults(frm);
        setup_employee_attendance_colored_viewer(frm);
    }
});

async function setup_employee_attendance_defaults(frm) {
    setup_employee_attendance_payroll_options(frm);
    [100, 500, 1000].forEach((delay) => {
        setTimeout(() => setup_employee_attendance_defaults_once(frm), delay);
    });

    await setup_employee_attendance_defaults_once(frm);
}

function setup_employee_attendance_colored_viewer(frm) {
    hide_employee_attendance_exception_dashboard();
    [0, 100, 500].forEach((delay) => {
        setTimeout(() => {
            hide_employee_attendance_exception_dashboard();
            install_employee_attendance_colored_renderer(frm);
            apply_employee_attendance_table_colors(frm);
        }, delay);
    });
}

function hide_employee_attendance_exception_dashboard() {
    if (document.getElementById("eas-hide-exception-dashboard-style")) return;

    $('<style id="eas-hide-exception-dashboard-style">' +
        '.eas-exception-dashboard{display:none!important;}' +
    '</style>').appendTo("head");
}

function install_employee_attendance_colored_renderer(frm) {
    ensure_employee_attendance_viewer_style();
    setup_employee_attendance_color_observer(frm);

    if (window.__eas_colored_renderer_installed) return;

    window.__eas_colored_renderer_installed = true;
    window.render_attendance_viewer = function(form, rows) {
        const field = form.fields_dict.attendance_viewer;
        if (!field) return;

        if (typeof apply_payroll_period_visibility === "function") {
            apply_payroll_period_visibility(form);
        }

        if (!form.doc.payroll_period) {
            field.$wrapper.empty();
            return;
        }

        ensure_employee_attendance_viewer_style();

        if (!rows || !rows.length) {
            field.$wrapper.html(
                '<div class="eas-attendance-viewer">' +
                    '<div class="eas-attendance-empty">Select an employee to view the attendance schedule.</div>' +
                '</div>'
            );
            return;
        }

        const columns = [
            ["sched_date", "SchedDate"],
            ["day_of_week", "DayOfWeek"],
            ["sched_time_start", "SchedTimeStart"],
            ["sched_time_end", "SchedTimeEnd"],
            ["time_in", "Time In"],
            ["time_out", "Time Out"],
            ["late_hours", "Late (Hour)"],
            ["valid_ot", "Valid OT"],
            ["authorization_no", "AuthorizationNo"],
            ["rest_day", "RestDay"],
            ["holiday_type", "HolidayType"],
            ["leave_type", "LeaveType"],
            ["department", "Department"],
            ["shift", "Shift"]
        ];

        const header = columns.map((column) => {
            return "<th>" + frappe.utils.escape_html(column[1]) + "</th>";
        }).join("");

        const body = rows.map((row) => {
            const status = get_employee_attendance_row_status(row);
            const cells = columns.map((column) => {
                return "<td>" + format_employee_attendance_cell(row, column[0]) + "</td>";
            }).join("");

            return '<tr class="' + status.className + '">' + cells + "</tr>";
        }).join("");

        field.$wrapper.html(
            '<div class="eas-attendance-legend">' +
                '<span><i class="eas-legend-dot eas-legend-late"></i>Late</span>' +
                '<span><i class="eas-legend-dot eas-legend-absent"></i>Absent</span>' +
                '<span><i class="eas-legend-dot eas-legend-holiday"></i>Holiday / Rest Day</span>' +
            '</div>' +
            '<div class="eas-attendance-viewer">' +
                '<div class="eas-attendance-scroll">' +
                    '<table class="eas-attendance-table">' +
                        '<thead><tr>' + header + '</tr></thead>' +
                        '<tbody>' + body + '</tbody>' +
                    '</table>' +
                '</div>' +
            '</div>'
        );
    };
}

function setup_employee_attendance_color_observer(frm) {
    if (window.__eas_color_observer_installed || !frm.fields_dict.attendance_viewer) return;

    window.__eas_color_observer_installed = true;
    const wrapper = frm.fields_dict.attendance_viewer.wrapper;
    const observer = new MutationObserver(() => apply_employee_attendance_table_colors(frm));
    observer.observe(wrapper, { childList: true, subtree: true });
}

function apply_employee_attendance_table_colors(frm) {
    const field = frm.fields_dict.attendance_viewer;
    if (!field || !field.$wrapper) return;

    ensure_employee_attendance_viewer_style();

    const table = field.$wrapper.find(".eas-attendance-table");
    if (!table.length) return;

    ensure_employee_attendance_legend(field.$wrapper);

    const columnIndex = {};
    table.find("thead th").each(function(index) {
        const label = ($(this).text() || "").trim().toLowerCase();
        columnIndex[label] = index;
    });

    table.find("tbody tr").each(function() {
        const row = $(this);
        const cells = row.find("td");
        const rowData = {
            sched_time_start: get_employee_attendance_cell_text(cells, columnIndex, "schedtimestart"),
            time_in: get_employee_attendance_cell_text(cells, columnIndex, "time in"),
            late_hours: get_employee_attendance_cell_text(cells, columnIndex, "late (hour)"),
            rest_day: get_employee_attendance_cell_text(cells, columnIndex, "restday"),
            holiday_type: get_employee_attendance_cell_text(cells, columnIndex, "holidaytype"),
            leave_type: get_employee_attendance_cell_text(cells, columnIndex, "leavetype")
        };
        const status = get_employee_attendance_row_status(rowData);

        row.removeClass("eas-row-late eas-row-absent eas-row-holiday");
        if (status.className) {
            row.addClass(status.className);
        }
    });
}

function ensure_employee_attendance_legend(wrapper) {
    if (wrapper.find(".eas-attendance-legend").length) return;

    wrapper.find(".eas-attendance-viewer").before(
        '<div class="eas-attendance-legend">' +
            '<span><i class="eas-legend-dot eas-legend-late"></i>Late</span>' +
            '<span><i class="eas-legend-dot eas-legend-absent"></i>Absent</span>' +
            '<span><i class="eas-legend-dot eas-legend-holiday"></i>Holiday / Rest Day</span>' +
        '</div>'
    );
}

function get_employee_attendance_cell_text(cells, columnIndex, label) {
    const index = columnIndex[label];
    if (index == null) return "";

    return (cells.eq(index).text() || "").trim();
}

function get_employee_attendance_row_status(row) {
    const hasSchedule = !!row.sched_time_start;
    const hasTimeIn = !!row.time_in;
    const hasLeave = !!row.leave_type;
    const isHoliday = !!row.holiday_type || !!row.rest_day;
    const isLate = flt(row.late_hours) > 0;
    const isAbsent = row.attendance_status === "Absent" || (hasSchedule && !hasTimeIn && !hasLeave && !isHoliday);

    if (isHoliday) {
        return { className: "eas-row-holiday" };
    }
    if (isAbsent) {
        return { className: "eas-row-absent" };
    }
    if (isLate) {
        return { className: "eas-row-late" };
    }

    return { className: "" };
}

function ensure_employee_attendance_viewer_style() {
    $("#eas-attendance-viewer-style").remove();
    if (document.getElementById("eas-attendance-color-style")) return;

    $('<style id="eas-attendance-color-style">' +
        '.eas-attendance-legend{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:0 0 10px;color:#475569;font-size:12px;line-height:1.4;}' +
        '.eas-attendance-legend span{display:inline-flex;align-items:center;gap:6px;}' +
        '.eas-legend-dot{width:10px;height:10px;border-radius:50%;display:inline-block;border:1px solid rgba(15,23,42,0.16);}' +
        '.eas-legend-late{background:#fff4cc;}' +
        '.eas-legend-absent{background:#ffd6d6;}' +
        '.eas-legend-holiday{background:#dff3e6;}' +
        '.eas-attendance-viewer{border:1px solid #e5e7eb;border-radius:8px;background:#fff;overflow:hidden;}' +
        '.eas-attendance-scroll{overflow:auto;max-width:100%;}' +
        '.eas-attendance-table{width:100%;min-width:1500px;border-collapse:collapse;}' +
        '.eas-attendance-table th,.eas-attendance-table td{padding:9px 12px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top;white-space:nowrap;line-height:1.35;}' +
        '.eas-attendance-table th{position:sticky;top:0;background:#f8f9fb;font-weight:600;z-index:1;}' +
        '.eas-attendance-table th:nth-child(1),.eas-attendance-table td:nth-child(1){white-space:normal;min-width:190px;}' +
        '.eas-attendance-table th:nth-child(2),.eas-attendance-table td:nth-child(2){white-space:normal;min-width:180px;}' +
        '.eas-attendance-table th:nth-child(3),.eas-attendance-table td:nth-child(3),.eas-attendance-table th:nth-child(4),.eas-attendance-table td:nth-child(4){min-width:110px;}' +
        '.eas-attendance-table th:nth-child(5),.eas-attendance-table td:nth-child(5),.eas-attendance-table th:nth-child(6),.eas-attendance-table td:nth-child(6),.eas-attendance-table th:nth-child(7),.eas-attendance-table td:nth-child(7),.eas-attendance-table th:nth-child(8),.eas-attendance-table td:nth-child(8){min-width:92px;}' +
        '.eas-attendance-table tbody tr.eas-row-late td{background:#fff8db;}' +
        '.eas-attendance-table tbody tr.eas-row-absent td{background:#ffe4e4;}' +
        '.eas-attendance-table tbody tr.eas-row-holiday td{background:#e9f8ee;}' +
        '.eas-attendance-table tbody tr:hover td{filter:brightness(0.985);}' +
        '.eas-attendance-link{color:#2563eb;text-decoration:none;font-weight:500;}' +
        '.eas-attendance-link:hover{text-decoration:underline;}' +
        '.eas-attendance-empty{padding:18px;color:#64748b;}' +
    '</style>').appendTo("head");
}

function format_employee_attendance_cell(row, fieldname) {
    const value = row[fieldname] == null ? "" : String(row[fieldname]);
    const label = frappe.utils.escape_html(value);
    if (!value) return "";

    const linkDoctypes = {
        authorization_no: "Overtime Slip",
        leave_type: "Leave Type"
    };
    const doctype = linkDoctypes[fieldname];
    if (!doctype) return label;

    const href = "/app/" + frappe.router.slug(doctype) + "/" + encodeURIComponent(value);
    return '<a class="eas-attendance-link" href="' + href + '">' + label + "</a>";
}

async function setup_employee_attendance_defaults_once(frm) {
    setup_employee_attendance_payroll_options(frm);

    if (!frm.doc.payroll_period) {
        await frm.set_value("payroll_period", get_current_employee_attendance_payroll_period());
    }

    if (!frm.doc.from_date || !frm.doc.to_date || !frm.doc.pay_day) {
        await set_employee_attendance_period_dates(frm, frm.doc.payroll_period);
    }
}

function get_current_employee_attendance_payroll_period() {
    const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
    const year = today.getFullYear();
    const month = today.getMonth();
    const day = today.getDate();
    const payDay = day <= 15 ? 15 : Math.min(30, new Date(year, month + 1, 0).getDate());

    return `${month + 1}/${payDay}/${year}`;
}

function setup_employee_attendance_payroll_options(frm) {
    if (!frm.fields_dict.payroll_period) return;

    const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
    const options = [];

    for (let offset = -6; offset <= 6; offset++) {
        const base = new Date(today.getFullYear(), today.getMonth() + offset, 1);
        options.push(format_employee_attendance_payroll_date(new Date(base.getFullYear(), base.getMonth(), 15)));
        options.push(format_employee_attendance_payroll_date(new Date(
            base.getFullYear(),
            base.getMonth(),
            Math.min(30, new Date(base.getFullYear(), base.getMonth() + 1, 0).getDate())
        )));
    }

    const current = frm.doc.payroll_period || get_current_employee_attendance_payroll_period();
    if (!options.includes(current)) {
        options.push(current);
    }

    frm.set_df_property("payroll_period", "options", options.join("\n"));
}

function format_employee_attendance_payroll_date(dateObj) {
    return `${dateObj.getMonth() + 1}/${dateObj.getDate()}/${dateObj.getFullYear()}`;
}

async function set_employee_attendance_period_dates(frm, payrollPeriod) {
    const payDay = parse_employee_attendance_payroll_date(payrollPeriod);
    if (!payDay) return;

    let fromDate;
    let toDate;

    if (payDay.getDate() === 15) {
        fromDate = new Date(payDay.getFullYear(), payDay.getMonth() - 1, 23);
        toDate = new Date(payDay.getFullYear(), payDay.getMonth(), 7);
    } else {
        fromDate = new Date(payDay.getFullYear(), payDay.getMonth(), 8);
        toDate = new Date(payDay.getFullYear(), payDay.getMonth(), 22);
    }

    await frm.set_value("from_date", format_employee_attendance_iso_date(fromDate));
    await frm.set_value("to_date", format_employee_attendance_iso_date(toDate));
    await frm.set_value("pay_day", format_employee_attendance_iso_date(payDay));
}

function parse_employee_attendance_payroll_date(value) {
    if (!value) return null;

    const parts = String(value).split("/").map((part) => cint(part));
    if (parts.length !== 3 || !parts[0] || !parts[1] || !parts[2]) return null;

    return new Date(parts[2], parts[0] - 1, parts[1]);
}

function format_employee_attendance_iso_date(dateObj) {
    return [
        dateObj.getFullYear(),
        String(dateObj.getMonth() + 1).padStart(2, "0"),
        String(dateObj.getDate()).padStart(2, "0")
    ].join("-");
}
