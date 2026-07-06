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
    },

    async payroll_frequency(frm) {
        await handle_employee_attendance_payroll_frequency_change(frm);
    }
});

async function setup_employee_attendance_defaults(frm) {
    ensure_employee_attendance_payroll_frequency(frm);
    setup_employee_attendance_payroll_options(frm);
    ensure_employee_attendance_payroll_type(frm);
    [100, 500, 1000].forEach((delay) => {
        setTimeout(() => setup_employee_attendance_defaults_once(frm), delay);
    });

    await setup_employee_attendance_defaults_once(frm);
}

function setup_employee_attendance_colored_viewer(frm) {
    if (frm && frm.wrapper) {
        $(frm.wrapper).addClass("eas-viewer-compact");
    }
    install_employee_attendance_period_reload_watch(frm);
    install_employee_attendance_frequency_change_watch(frm);
    render_employee_attendance_period_toggle(frm);
    hide_employee_attendance_exception_dashboard();
    [0, 100, 500].forEach((delay) => {
        setTimeout(() => {
            install_employee_attendance_period_reload_watch(frm);
            install_employee_attendance_frequency_change_watch(frm);
            render_employee_attendance_period_toggle(frm);
            hide_employee_attendance_exception_dashboard();
            install_employee_attendance_table_picker(frm);
            install_employee_attendance_colored_renderer(frm);
            apply_employee_attendance_table_colors(frm);
        }, delay);
    });
}

function install_employee_attendance_frequency_change_watch(frm) {
    const field = frm && frm.fields_dict && frm.fields_dict.payroll_frequency;
    if (!field || !field.$input || field.$input.data("eas-frequency-watch")) return;

    field.$input.data("eas-frequency-watch", true);
    field.$input.on("change.eas_frequency_watch", function() {
        const value = $(this).val() || "Bimonthly";
        if (frm.doc.payroll_frequency !== value) {
            frm.doc.payroll_frequency = value;
            frm.refresh_field("payroll_frequency");
        }
        handle_employee_attendance_payroll_frequency_change(frm);
    });
}

function render_employee_attendance_period_toggle(frm) {
    if (!frm || !frm.wrapper || !frm.fields_dict || !frm.fields_dict.company) return;

    ensure_employee_attendance_period_toggle_style();

    const $layout = $(frm.wrapper).find(".form-layout").first();
    if (!$layout.length) return;

    let $toggle = $(frm.wrapper).find(".eas-period-toggle").first();
    if (!$toggle.length) {
        $toggle = $(
            '<div class="eas-period-toggle">' +
                '<div class="eas-period-toggle-main">' +
                    '<strong>Period Details</strong>' +
                    '<span class="eas-period-toggle-summary"></span>' +
                '</div>' +
                '<button class="btn btn-xs btn-default eas-period-toggle-button" type="button"></button>' +
            '</div>'
        );
        $layout.prepend($toggle);
        $toggle.on("click", ".eas-period-toggle-button", function() {
            frm.__period_details_collapsed = !frm.__period_details_collapsed;
            render_employee_attendance_period_toggle(frm);
        });
    }

    if (frm.__period_details_collapsed === undefined) {
        frm.__period_details_collapsed = !!frm.doc.payroll_period;
    }

    const collapsed = !!frm.__period_details_collapsed && !!frm.doc.payroll_period;
    const $periodSection = $(frm.fields_dict.company.wrapper).closest(".form-section");
    $periodSection.toggle(!collapsed);

    const parts = [
        frm.doc.payroll_period ? "Pay: " + frm.doc.payroll_period : "",
        frm.doc.from_date && frm.doc.to_date ? frm.doc.from_date + " to " + frm.doc.to_date : "",
        frm.doc.selected_employee_name ? "Employee: " + frm.doc.selected_employee_name : ""
    ].filter(Boolean);

    $toggle.toggle(!!frm.doc.payroll_period);
    $toggle.toggleClass("is-collapsed", collapsed);
    $toggle.find(".eas-period-toggle-summary").text(parts.join(" - "));
    $toggle.find(".eas-period-toggle-button").text(collapsed ? "Show" : "Hide");
}

function ensure_employee_attendance_period_toggle_style() {
    if (document.getElementById("eas-period-toggle-style")) return;

    $('<style id="eas-period-toggle-style">' +
        '.eas-period-toggle{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:8px auto 10px;max-width:870px;padding:8px 10px;border:1px solid #e5e7eb;border-radius:8px;background:#f8fafc;color:#334155;}' +
        '.eas-period-toggle-main{display:flex;align-items:center;gap:10px;min-width:0;}' +
        '.eas-period-toggle-main strong{font-size:12px;color:#0f172a;white-space:nowrap;}' +
        '.eas-period-toggle-summary{font-size:12px;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}' +
        '.eas-period-toggle-button{flex:0 0 auto;}' +
    '</style>').appendTo("head");
}

function install_employee_attendance_table_picker(frm) {
    if (window.render_employee_picker && window.render_employee_picker.__eas_table_picker) {
        window.render_employee_picker(frm);
        return;
    }
    if (typeof parse_employee_list !== "function" || typeof ensure_employee_directory !== "function") return;

    window.render_employee_picker = function(frm) {
        if (!frm.fields_dict.employee_list_html) return;

        if (typeof apply_payroll_period_visibility === "function") {
            apply_payroll_period_visibility(frm);
        }

        const field = frm.fields_dict.employee_list_html;
        if (!frm.doc.payroll_period) {
            field.$wrapper.empty();
            return;
        }

        let employees = has_current_employee_attendance_directory(frm) ? parse_employee_list(frm) : [];
        const wrapper = field.$wrapper;
        wrapper.off("click.eas_employee_table");

        ensure_employee_attendance_table_picker_style();

        if (frm.doc.selected_employee && !frm.__show_employee_picker) {
            render_employee_attendance_selected_card(frm, wrapper);
        } else {
            render_employee_attendance_table(frm, wrapper, employees, "");
        }

        if (!employees.length && (!frm.doc.selected_employee || frm.__show_employee_picker)) {
            ensure_employee_directory(frm, (loadedEmployees) => {
                employees = loadedEmployees || parse_employee_list(frm);
                render_employee_attendance_table(frm, wrapper, employees, "");
            });
        }

        wrapper.on("click.eas_employee_table", ".eas-employee-change", function() {
            frm.__show_employee_picker = true;
            render_employee_attendance_table(
                frm,
                wrapper,
                employees.length ? employees : (has_current_employee_attendance_directory(frm) ? parse_employee_list(frm) : []),
                ""
            );
            ensure_employee_directory(frm, (loadedEmployees) => {
                employees = loadedEmployees || [];
                render_employee_attendance_table(frm, wrapper, employees, "");
            });
        });

        wrapper.on("click.eas_employee_table", ".eas-employee-table-row", function() {
            const employee = $(this).attr("data-employee") || "";
            const employeeName = $(this).attr("data-employee-name") || "";
            frm.__employee_table_scroll_top = wrapper.find(".eas-employee-table-wrap").scrollTop() || 0;
            frm.__show_employee_picker = false;
            if (!employee) return;

            wrapper.find(".eas-employee-table-row").removeClass("is-selected");
            $(this).addClass("is-selected");
            frm.__eas_last_selected_employee = employee;
            frm.__eas_last_selected_employee_name = employeeName;
            frm.__period_details_collapsed = true;
            render_employee_attendance_period_toggle(frm);

            if (typeof load_employee_schedule === "function") {
                load_employee_schedule(frm, employee, employeeName);
            }
        });
    };

    window.render_employee_picker.__eas_table_picker = true;
    window.render_employee_picker(frm);
}

function install_employee_attendance_period_reload_watch(frm) {
    const field = frm && frm.fields_dict && frm.fields_dict.payroll_period;
    if (!field || !field.$input || field.$input.data("eas-selected-reload")) return;

    field.$input.data("eas-selected-reload", true);
    field.$input.on("change.eas_selected_reload", function() {
        const employee = get_employee_attendance_selected_employee(frm);
        const employeeName = frm.doc.selected_employee_name || frm.__eas_last_selected_employee_name || employee;
        if (!employee) return;

        frm.__eas_last_selected_employee = employee;
        frm.__eas_last_selected_employee_name = employeeName;

        const reloadKey = [employee, $(this).val() || frm.doc.payroll_period || ""].join("|");
        frm.__eas_selected_period_reload_key = reloadKey;

        [700, 1400].forEach((delay) => {
            setTimeout(() => {
                if (frm.__eas_selected_period_reload_key !== reloadKey) return;
                if (!frm.doc.payroll_period || typeof load_employee_schedule !== "function") return;

                frm.__eas_selected_period_reload_key = "";
                frm.__show_employee_picker = false;
                frm.__period_details_collapsed = true;
                frm.set_value("selected_employee", employee);
                frm.set_value("selected_employee_name", employeeName || employee);
                render_employee_attendance_period_toggle(frm);
                load_employee_schedule(frm, employee, employeeName || employee);
            }, delay);
        });
    });
}

function get_employee_attendance_selected_employee(frm) {
    const value = frm.doc.selected_employee || frm.__eas_last_selected_employee || "";
    if (value) return String(value).split(" - ")[0].trim();

    const label = frm.doc.selected_employee_name || "";
    const match = String(label).match(/HR-EMP-\d+/);
    return match ? match[0] : "";
}

function has_current_employee_attendance_directory(frm) {
    if (typeof has_current_employee_directory === "function") {
        return has_current_employee_directory(frm);
    }
    return true;
}

function ensure_employee_attendance_table_picker_style() {
    if (document.getElementById("eas-employee-table-picker-style")) return;

    $('<style id="eas-employee-table-picker-style">' +
        '.eas-viewer-compact .form-section{padding-top:8px!important;padding-bottom:8px!important;}' +
        '.eas-viewer-compact .section-body{padding-top:6px!important;padding-bottom:6px!important;}' +
        '.eas-viewer-compact .frappe-control{margin-bottom:8px!important;}' +
        '.eas-viewer-compact .control-label{margin-bottom:4px!important;}' +
        '.eas-viewer-compact .form-column{padding-top:0!important;padding-bottom:0!important;}' +
        '.eas-viewer-compact [data-fieldname="employees_section"] .section-head{margin-bottom:8px!important;}' +
        '.eas-viewer-compact [data-fieldname="attendance_section"] .section-head{display:none!important;}' +
        '.eas-employee-table-picker{max-width:520px;}' +
        '.eas-employee-count{font-size:12px;color:#64748b;margin:0 0 6px;}' +
        '.eas-employee-count strong{color:#0f172a;}' +
        '.eas-employee-selected-card{display:flex;align-items:center;gap:10px;max-width:520px;}' +
        '.eas-employee-selected-text{flex:1;min-width:0;padding:7px 10px;border:1px solid #e5e7eb;border-radius:8px;background:#f8fafc;color:#334155;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}' +
        '.eas-employee-change{flex:0 0 auto;}' +
        '.eas-employee-table-wrap{border:1px solid #e5e7eb;border-radius:8px;background:#fff;overflow:auto;max-height:210px;}' +
        '.eas-employee-table{width:100%;border-collapse:collapse;}' +
        '.eas-employee-table th,.eas-employee-table td{padding:9px 12px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:middle;line-height:1.35;word-break:break-word;}' +
        '.eas-employee-table th{position:sticky;top:0;background:#f8f9fb;font-weight:600;z-index:1;}' +
        '.eas-employee-table-row{cursor:pointer;}' +
        '.eas-employee-table-row:hover td{background:#f8fafc;}' +
        '.eas-employee-table-row.is-selected td{background:#eef6ff;}' +
        '.eas-employee-id{white-space:nowrap;font-weight:600;color:#334155;}' +
        '.eas-employee-status{display:inline-flex;padding:3px 8px;border-radius:999px;background:#f1f5f9;color:#334155;font-size:11px;white-space:nowrap;}' +
        '.eas-employee-status.no-shift{background:#fff7ed;color:#9a3412;}' +
        '.eas-employee-table-empty{padding:16px;color:#64748b;}' +
    '</style>').appendTo("head");
}

function render_employee_attendance_selected_card(frm, wrapper) {
    const label = frm.doc.selected_employee_name || frm.doc.selected_employee || "";
    wrapper.html(
        '<div class="eas-employee-selected-card">' +
            '<div class="eas-employee-selected-text">' + frappe.utils.escape_html(label) + '</div>' +
            '<button class="btn btn-xs btn-default eas-employee-change" type="button">Change</button>' +
        '</div>'
    );
}

function render_employee_attendance_table(frm, wrapper, employees, keyword) {
    const text = (keyword || "").toLowerCase().trim();
    const selectedEmployee = frm.doc.selected_employee || "";
    const rows = (employees || []).filter((employee) => {
        if (!text) return true;
        const haystack = [
            employee.employee,
            employee.employee_name,
            employee.department,
            employee.default_shift,
            employee.status
        ].filter(Boolean).join(" ").toLowerCase();
        return haystack.indexOf(text) !== -1;
    });

    const body = rows.map((employee) => {
        const status = employee.status || "";
        const statusClass = status === "No Shift Setup" ? " no-shift" : "";
        const selectedClass = employee.employee === selectedEmployee ? " is-selected" : "";

        return '<tr class="eas-employee-table-row' + selectedClass + '" data-employee="' + frappe.utils.escape_html(employee.employee || "") + '" data-employee-name="' + frappe.utils.escape_html(employee.employee_name || "") + '">' +
            '<td class="eas-employee-id">' + frappe.utils.escape_html(employee.employee || "") + '</td>' +
            '<td>' + frappe.utils.escape_html(employee.employee_name || "") + '</td>' +
        '</tr>';
    }).join("");

    const emptyHtml = '<div class="eas-employee-table-empty">' +
        (text ? "No employee found." : "Loading employees...") +
    '</div>';
    const totalCount = (employees || []).length;
    const countText = text && rows.length !== totalCount
        ? "Showing <strong>" + rows.length + "</strong> of <strong>" + totalCount + "</strong> employees"
        : "Employees: <strong>" + totalCount + "</strong>";

    wrapper.html(
        '<div class="eas-employee-table-picker">' +
            '<div class="eas-employee-count">' + countText + '</div>' +
            '<div class="eas-employee-table-wrap">' +
                (rows.length ? '<table class="eas-employee-table">' +
                    '<thead><tr>' +
                        '<th style="width:140px;">Employee ID</th>' +
                        '<th>Employee Name</th>' +
                    '</tr></thead>' +
                    '<tbody>' + body + '</tbody>' +
                '</table>' : emptyHtml) +
            '</div>' +
        '</div>'
    );

    const scrollTop = frm.__employee_table_scroll_top || 0;
    if (scrollTop) {
        wrapper.find(".eas-employee-table-wrap").scrollTop(scrollTop);
    }
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

    if (window.render_attendance_viewer && window.render_attendance_viewer.__eas_with_leave_summary) return;

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
            ["valid_ot", "OT Hours"],
            ["overtime_type", "OT Type"],
            ["night_diff_hours", "ND Hours"],
            ["authorization_no", "OT Slip"],
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

        const totalLate = rows.reduce((total, row) => total + flt(row.late_hours), 0);
        const totalOt = rows.reduce((total, row) => total + flt(row.valid_ot), 0);
        const overtimeTypeSummary = get_employee_attendance_overtime_type_summary(rows);
        const totalNightDiff = rows.reduce((total, row) => total + flt(row.night_diff_hours), 0);
        const nightDiffSummary = totalNightDiff
            ? '<span class="eas-attendance-total">Night Diff <strong>' + format_employee_attendance_total(totalNightDiff) + '</strong></span>'
            : "";
        const totalAbsent = rows.reduce((total, row) => {
            return total + (get_employee_attendance_row_status(row).className === "eas-row-absent" ? 1 : 0);
        }, 0);
        const totalLeave = rows.reduce((total, row) => {
            return total + (get_employee_attendance_row_status(row).className === "eas-row-leave" ? 1 : 0);
        }, 0);

        field.$wrapper.html(
            '<div class="eas-attendance-summary">' +
                '<span class="eas-attendance-total">Total Late <strong>' + format_employee_attendance_total(totalLate) + '</strong></span>' +
                '<span class="eas-attendance-total">Total OT <strong>' + format_employee_attendance_total(totalOt) + '</strong></span>' +
                overtimeTypeSummary +
                nightDiffSummary +
                '<span class="eas-attendance-total">Absent <strong>' + totalAbsent + '</strong> day' + (totalAbsent === 1 ? '' : 's') + '</span>' +
                '<span class="eas-attendance-total">Leave <strong>' + totalLeave + '</strong> day' + (totalLeave === 1 ? '' : 's') + '</span>' +
            '</div>' +
            '<div class="eas-attendance-legend">' +
                '<span><i class="eas-legend-dot eas-legend-late"></i>Late</span>' +
                '<span><i class="eas-legend-dot eas-legend-absent"></i>Absent</span>' +
                '<span><i class="eas-legend-dot eas-legend-leave"></i>Leave</span>' +
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
    window.render_attendance_viewer.__eas_with_leave_summary = true;
}

function get_employee_attendance_overtime_type_summary(rows) {
    const totals = {};
    (rows || []).forEach((row) => {
        const hours = flt(row.valid_ot);
        if (!hours) return;

        const type = (row.overtime_type || "No OT Type").trim();
        totals[type] = (totals[type] || 0) + hours;
    });

    const chips = Object.keys(totals).sort().map((type) => {
        return '<span class="eas-attendance-total eas-attendance-ot-type">' +
            frappe.utils.escape_html(type) +
            ' <strong>' + format_employee_attendance_total(totals[type]) + '</strong>' +
        '</span>';
    }).join("");

    if (!chips) return "";
    return '<span class="eas-attendance-breakdown-label">OT Breakdown</span>' + chips;
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

        row.removeClass("eas-row-late eas-row-absent eas-row-leave eas-row-holiday");
        if (status.className) {
            row.addClass(status.className);
        }
    });
}

function ensure_employee_attendance_legend(wrapper) {
    const existingLegend = wrapper.find(".eas-attendance-legend");
    if (existingLegend.length) {
        if (!existingLegend.find(".eas-legend-leave").length) {
            existingLegend.find(".eas-legend-absent").closest("span").after(
                '<span><i class="eas-legend-dot eas-legend-leave"></i>Leave</span>'
            );
        }
        return;
    }

    wrapper.find(".eas-attendance-viewer").before(
        '<div class="eas-attendance-legend">' +
            '<span><i class="eas-legend-dot eas-legend-late"></i>Late</span>' +
            '<span><i class="eas-legend-dot eas-legend-absent"></i>Absent</span>' +
            '<span><i class="eas-legend-dot eas-legend-leave"></i>Leave</span>' +
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
    if (hasLeave) {
        return { className: "eas-row-leave" };
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
        '.eas-attendance-summary{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 10px;}' +
        '.eas-attendance-total{display:inline-flex;align-items:baseline;gap:6px;padding:7px 10px;border:1px solid #e5e7eb;border-radius:6px;background:#f8fafc;color:#334155;font-size:12px;line-height:1.2;}' +
        '.eas-attendance-total strong{font-size:15px;color:#0f172a;font-weight:700;}' +
        '.eas-attendance-breakdown-label{display:inline-flex;align-items:center;color:#64748b;font-size:12px;font-weight:600;line-height:1.2;}' +
        '.eas-attendance-legend{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:0 0 10px;color:#475569;font-size:12px;line-height:1.4;}' +
        '.eas-attendance-legend span{display:inline-flex;align-items:center;gap:6px;}' +
        '.eas-legend-dot{width:10px;height:10px;border-radius:50%;display:inline-block;border:1px solid rgba(15,23,42,0.16);}' +
        '.eas-legend-late{background:#fff4cc;}' +
        '.eas-legend-absent{background:#ffd6d6;}' +
        '.eas-legend-leave{background:#e6e0ff;}' +
        '.eas-legend-holiday{background:#dff3e6;}' +
        '.eas-attendance-viewer{border:1px solid #e5e7eb;border-radius:8px;background:#fff;overflow:hidden;}' +
        '.eas-attendance-scroll{overflow:auto;max-width:100%;max-height:calc(100vh - 245px);}' +
        '.eas-attendance-table{width:100%;min-width:1500px;border-collapse:collapse;}' +
        '.eas-attendance-table th,.eas-attendance-table td{padding:9px 12px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top;white-space:nowrap;line-height:1.35;}' +
        '.eas-attendance-table th{position:sticky;top:0;background:#f8f9fb;font-weight:600;z-index:1;}' +
        '.eas-attendance-table th:nth-child(1),.eas-attendance-table td:nth-child(1){position:sticky;left:0;white-space:normal;min-width:190px;z-index:2;background:#fff;box-shadow:1px 0 0 #e5e7eb;}' +
        '.eas-attendance-table th:nth-child(1){z-index:4;background:#f8f9fb;}' +
        '.eas-attendance-table th:nth-child(2),.eas-attendance-table td:nth-child(2){white-space:normal;min-width:180px;}' +
        '.eas-attendance-table th:nth-child(3),.eas-attendance-table td:nth-child(3),.eas-attendance-table th:nth-child(4),.eas-attendance-table td:nth-child(4){min-width:110px;}' +
        '.eas-attendance-table th:nth-child(5),.eas-attendance-table td:nth-child(5),.eas-attendance-table th:nth-child(6),.eas-attendance-table td:nth-child(6),.eas-attendance-table th:nth-child(7),.eas-attendance-table td:nth-child(7),.eas-attendance-table th:nth-child(8),.eas-attendance-table td:nth-child(8){min-width:92px;}' +
        '.eas-attendance-table tbody tr.eas-row-late td{background:#fff8db;}' +
        '.eas-attendance-table tbody tr.eas-row-absent td{background:#ffe4e4;}' +
        '.eas-attendance-table tbody tr.eas-row-leave td{background:#f2edff;}' +
        '.eas-attendance-table tbody tr.eas-row-holiday td{background:#e9f8ee;}' +
        '.eas-attendance-table tbody tr.eas-row-late td:nth-child(1){background:#fff8db;}' +
        '.eas-attendance-table tbody tr.eas-row-absent td:nth-child(1){background:#ffe4e4;}' +
        '.eas-attendance-table tbody tr.eas-row-leave td:nth-child(1){background:#f2edff;}' +
        '.eas-attendance-table tbody tr.eas-row-holiday td:nth-child(1){background:#e9f8ee;}' +
        '.eas-attendance-table tbody tr:hover td{filter:brightness(0.985);}' +
        '.eas-attendance-link{color:#2563eb;text-decoration:none;font-weight:500;}' +
        '.eas-attendance-link:hover{text-decoration:underline;}' +
        '.eas-attendance-empty{padding:18px;color:#64748b;}' +
    '</style>').appendTo("head");
}

function format_employee_attendance_total(value) {
    const totalMinutes = Math.round(flt(value) * 60);
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;

    if (hours && minutes) return hours + "h " + minutes + "m";
    if (hours) return hours + "h";
    return minutes + "m";
}

function format_employee_attendance_cell(row, fieldname) {
    const value = row[fieldname] == null ? "" : String(row[fieldname]);
    const label = frappe.utils.escape_html(value);
    if (!value) return "";

    if (fieldname === "leave_type") {
        if (!row.leave_application) return label;
        const href = "/app/" + frappe.router.slug("Leave Application") + "/" + encodeURIComponent(row.leave_application);
        return '<a class="eas-attendance-link" href="' + href + '">' + label + "</a>";
    }

    const linkDoctypes = {
        authorization_no: "Overtime Slip"
    };
    const doctype = linkDoctypes[fieldname];
    if (!doctype) return label;

    const href = "/app/" + frappe.router.slug(doctype) + "/" + encodeURIComponent(value);
    return '<a class="eas-attendance-link" href="' + href + '">' + label + "</a>";
}

async function setup_employee_attendance_defaults_once(frm) {
    await ensure_employee_attendance_payroll_frequency(frm);
    setup_employee_attendance_payroll_options(frm);

    if (!frm.doc.from_date || !frm.doc.to_date || !frm.doc.pay_day) {
        await set_employee_attendance_period_dates(frm, frm.doc.payroll_period);
    }
}

async function ensure_employee_attendance_payroll_frequency(frm) {
    if (!frm.doc.payroll_frequency) {
        await frm.set_value("payroll_frequency", "Bimonthly");
    }
}

function get_employee_attendance_payroll_frequency(frm) {
    return (frm.doc.payroll_frequency || "Bimonthly").trim();
}

function get_employee_attendance_payroll_type(frm) {
    return get_employee_attendance_payroll_frequency(frm) === "Weekly" ? "Weekly" : "Monthly";
}

async function handle_employee_attendance_payroll_frequency_change(frm) {
    setup_employee_attendance_payroll_options(frm);
    if (frm.doc.payroll_period) {
        await frm.set_value("payroll_period", "");
    }
    if (frm.doc.from_date) await frm.set_value("from_date", "");
    if (frm.doc.to_date) await frm.set_value("to_date", "");
    if (frm.doc.pay_day) await frm.set_value("pay_day", "");
    if (typeof clear_generated_data === "function") {
        clear_generated_data(frm);
    }
    render_employee_attendance_period_toggle(frm);
}

function get_current_employee_attendance_payroll_period() {
    const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
    const year = today.getFullYear();
    const month = today.getMonth();
    const day = today.getDate();
    if (typeof cur_frm !== "undefined" && cur_frm && get_employee_attendance_payroll_frequency(cur_frm) === "Weekly") {
        const sunday = new Date(today);
        sunday.setDate(today.getDate() + ((7 - today.getDay()) % 7));
        return format_employee_attendance_payroll_date(sunday);
    }
    const payDay = day <= 15 ? 15 : Math.min(30, new Date(year, month + 1, 0).getDate());

    return `${month + 1}/${payDay}/${year}`;
}

function setup_employee_attendance_payroll_options(frm) {
    if (!frm.fields_dict.payroll_period) return;

    const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
    const options = [];
    const payrollType = get_employee_attendance_payroll_type(frm);

    for (let offset = -6; offset <= 6; offset++) {
        const base = new Date(today.getFullYear(), today.getMonth() + offset, 1);
        if (payrollType === "Monthly") {
            options.push(format_employee_attendance_payroll_date(new Date(base.getFullYear(), base.getMonth(), 15)));
            options.push(format_employee_attendance_payroll_date(new Date(
                base.getFullYear(),
                base.getMonth(),
                Math.min(30, new Date(base.getFullYear(), base.getMonth() + 1, 0).getDate())
            )));
        }
        if (payrollType === "Weekly") {
            add_employee_attendance_weekly_payroll_options(options, base);
        }
    }

    const uniqueOptions = Array.from(new Set(options));
    frm.set_df_property("payroll_period", "options", uniqueOptions.join("\n"));
    if (frm.fields_dict.payroll_period) {
        frm.fields_dict.payroll_period.df.options = uniqueOptions.join("\n");
        frm.fields_dict.payroll_period.refresh();
    }
}

function ensure_employee_attendance_payroll_type(frm) {
    if (frm.__employee_attendance_payroll_type_loaded || frm.__loading_employee_attendance_payroll_type) return;

    frm.__loading_employee_attendance_payroll_type = true;
    frappe.call({
        method: "qcmc_logic.api.employee_attendance_schedule.get_current_user_payroll_type",
        callback(r) {
            frm.__employee_attendance_payroll_type = ((r && r.message) || "").trim();
            frm.__employee_attendance_payroll_type_loaded = true;
            frm.__loading_employee_attendance_payroll_type = false;
            setup_employee_attendance_payroll_options(frm);
        },
        error() {
            frm.__loading_employee_attendance_payroll_type = false;
        }
    });
}

function format_employee_attendance_payroll_date(dateObj) {
    return `${dateObj.getMonth() + 1}/${dateObj.getDate()}/${dateObj.getFullYear()}`;
}

function add_employee_attendance_weekly_payroll_options(options, base) {
    const first = new Date(base.getFullYear(), base.getMonth(), 1);
    const last = new Date(base.getFullYear(), base.getMonth() + 1, 0);
    const sunday = new Date(first);
    sunday.setDate(first.getDate() + ((7 - first.getDay()) % 7));

    while (sunday <= last) {
        options.push(format_employee_attendance_payroll_date(new Date(sunday)));
        sunday.setDate(sunday.getDate() + 7);
    }
}

async function set_employee_attendance_period_dates(frm, payrollPeriod) {
    const payDay = parse_employee_attendance_payroll_date(payrollPeriod);
    if (!payDay) return;

    let fromDate;
    let toDate;

    if (get_employee_attendance_payroll_frequency(frm) === "Weekly") {
        fromDate = new Date(payDay.getFullYear(), payDay.getMonth(), payDay.getDate() - 6);
        toDate = payDay;
    } else if (payDay.getDate() === 15) {
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
