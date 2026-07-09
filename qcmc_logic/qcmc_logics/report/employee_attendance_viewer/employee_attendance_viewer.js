frappe.query_reports["Employee Attendance Viewer"] = {
    filters: [
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Autocomplete",
            options: [],
            default: "QC Styropackaging Corporation",
            reqd: 1,
            on_change: function() {
                const report = frappe.query_report;
                apply_role_locked_filters(report);
                report.set_filter_value("employee", "");
                setup_employee_filter_options(report);
            }
        },
        {
            fieldname: "payroll_frequency",
            label: __("Payroll Frequency"),
            fieldtype: "Select",
            options: "Bimonthly\nWeekly",
            default: "Bimonthly",
            reqd: 1,
            on_change: function() {
                const report = frappe.query_report;
                apply_role_locked_filters(report);
                setup_payroll_period_filter(report, true);
                report.set_filter_value("employee", "");
                setup_employee_filter_options(report);
            }
        },
        {
            fieldname: "payroll_period",
            label: __("Payroll Period"),
            fieldtype: "Select",
            options: "",
            reqd: 1,
            on_change: function() {
                const report = frappe.query_report;
                report.set_filter_value("employee", "");
                setup_employee_filter_options(report);
            }
        },
        {
            fieldname: "payroll_period_mode",
            label: __("Payroll Period Mode"),
            fieldtype: "Data",
            hidden: 1
        },
        {
            fieldname: "employee",
            label: __("Employee"),
            fieldtype: "Autocomplete",
            options: []
        }
    ],

    onload(report) {
        apply_role_locked_filters(report);
        setup_payroll_period_filter(report, false);
        setup_employee_filter_options(report);
        install_employee_row_click(report);
        add_clear_employee_button(report);
        apply_attendance_viewer_style();
        render_attendance_legend(report);
    },

    refresh(report) {
        apply_role_locked_filters(report);
        setup_payroll_period_filter(report, false);
        setup_employee_filter_options(report);
        install_employee_row_click(report);
        add_clear_employee_button(report);
        apply_attendance_viewer_style();
        render_attendance_legend(report);
    },

    get_datatable_options(options) {
        options.disableReorderColumn = true;
        return options;
    },

    after_datatable_render(datatable) {
        render_attendance_legend(frappe.query_report);
        apply_schedule_row_colors(datatable);
        apply_frozen_schedule_columns(datatable);
        install_datatable_repaint(datatable);
    },

    formatter(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (!data) return value;

        if (data.employee && !data.sched_date) {
            return value;
        }

        if (column.fieldname === "leave_type" && data.leave_type && data.leave_application) {
            value = `<a href="/app/leave-application/${encodeURIComponent(data.leave_application)}">${frappe.utils.escape_html(data.leave_type)}</a>`;
        }

        const row_class = get_schedule_row_class(data);
        const background = get_schedule_row_color(row_class);
        return background ? format_colored_cell(value, background) : value;
    }
};

function apply_role_locked_filters(report) {
    const role_defaults = get_attendance_viewer_role_defaults(report);
    if (!role_defaults) {
        set_filter_value_if_changed(report, "payroll_period_mode", "");
        unlock_attendance_filter(report, "company");
        unlock_attendance_filter(report, "payroll_frequency");
        setup_allowed_company_filter(report, []);
        return;
    }

    const companies = role_defaults.companies || [];
    const payroll_frequencies = role_defaults.payroll_frequencies || [];
    const current_company = report.get_filter_value("company");
    set_filter_value_if_changed(report, "payroll_frequency", role_defaults.payroll_frequency);
    set_filter_value_if_changed(report, "payroll_period_mode", role_defaults.payroll_period_mode || "");

    if (companies.length && !companies.includes(current_company)) {
        set_filter_value_if_changed(report, "company", companies[0]);
    }

    const frequency_filter = report.get_filter("payroll_frequency");
    if (frequency_filter) {
        frequency_filter.df.options = payroll_frequencies.join("\n");
        frequency_filter.refresh();
    }

    if (payroll_frequencies.length === 1) {
        lock_attendance_filter(report, "payroll_frequency");
    } else {
        unlock_attendance_filter(report, "payroll_frequency");
        if (frequency_filter) {
            frequency_filter.df.options = payroll_frequencies.join("\n");
            frequency_filter.refresh();
        }
    }

    setup_allowed_company_filter(report, companies);
    if (companies.length === 1) {
        lock_attendance_filter(report, "company");
    } else {
        unlock_attendance_filter(report, "company");
    }
}

function get_attendance_viewer_role_defaults(report) {
    if (frappe.session && frappe.session.user === "Administrator") {
        return null;
    }

    if (!frappe.user || !frappe.user.has_role) {
        return null;
    }

    const rules = get_attendance_viewer_ui_role_rules().filter((rule) => frappe.user.has_role(rule.role));
    if (!rules.length) {
        return null;
    }

    const payroll_frequencies = Array.from(new Set(rules.map((rule) => rule.payroll_frequency)));
    const current_frequency = report ? report.get_filter_value("payroll_frequency") : "";
    const payroll_frequency = payroll_frequencies.includes(current_frequency)
        ? current_frequency
        : payroll_frequencies[0];
    const matching_frequency_rules = rules.filter((rule) => rule.payroll_frequency === payroll_frequency);
    const companies = Array.from(new Set(matching_frequency_rules.map((rule) => rule.company)));
    const payroll_period_mode = matching_frequency_rules.some((rule) => rule.payroll_period_mode === "calendar_bimonthly")
        ? "calendar_bimonthly"
        : "";

    return {
        companies,
        payroll_frequency,
        payroll_frequencies,
        payroll_period_mode
    };
}

function get_attendance_viewer_ui_role_rules() {
    return [
        { role: "Monthly QC", company: "QC Styropackaging Corporation", payroll_frequency: "Bimonthly" },
        { role: "Monthly MC", company: "Multiplast Corporation", payroll_frequency: "Bimonthly" },
        { role: "Monthly SMB", company: "QC Styropackaging Corporation", payroll_frequency: "Bimonthly" },
        { role: "Monthly VAL", company: "Multiplast Corporation", payroll_frequency: "Bimonthly" },
        { role: "MC Prov Merch", company: "Multiplast Corporation", payroll_frequency: "Bimonthly", payroll_period_mode: "calendar_bimonthly" },
        { role: "Weekly QC EDSA", company: "QC Styropackaging Corporation", payroll_frequency: "Weekly" },
        { role: "Weekly MC EDSA", company: "Multiplast Corporation", payroll_frequency: "Weekly" },
        { role: "Weekly QC Agency", company: "QC Styropackaging Corporation", payroll_frequency: "Weekly" },
        { role: "Weekly QC SMB", company: "QC Styropackaging Corporation", payroll_frequency: "Weekly" },
        { role: "Weekly MC VAL", company: "Multiplast Corporation", payroll_frequency: "Weekly" },
        { role: "Weekly QC Prov", company: "QC Styropackaging Corporation", payroll_frequency: "Weekly" },
        { role: "Weekly MC Prov", company: "Multiplast Corporation", payroll_frequency: "Weekly" },
        { role: "Weekly MC Prov Agency", company: "Multiplast Corporation", payroll_frequency: "Weekly" },
    ];
}

function setup_allowed_company_filter(report, companies) {
    const filter = report.get_filter("company");
    if (!filter) return;

    if (!companies || !companies.length) {
        setup_all_company_filter_options(report, filter);
        return;
    }

    const options = companies.map((company) => ({
        label: company,
        value: company
    }));
    filter.df.options = options;
    filter.refresh();
    if (filter.set_data) {
        filter.set_data(options);
    }
}

function setup_all_company_filter_options(report, filter) {
    const request_key = "all";
    if (report.__employee_attendance_company_options_key === request_key) return;
    report.__employee_attendance_company_options_key = request_key;

    frappe.db.get_list("Company", {
        fields: ["name"],
        limit: 500,
        order_by: "name asc"
    }).then((companies) => {
        const options = (companies || []).map((company) => ({
            label: company.name,
            value: company.name
        }));
        filter.df.options = options;
        filter.refresh();
        if (filter.set_data) {
            filter.set_data(options);
        }
    });
}

function set_filter_value_if_changed(report, fieldname, value) {
    if (value !== undefined && value !== null && report.get_filter_value(fieldname) !== value) {
        report.set_filter_value(fieldname, value);
    }
}

function lock_attendance_filter(report, fieldname) {
    const filter = report.get_filter(fieldname);
    if (!filter) return;

    filter.df.read_only = 1;
    filter.refresh();
    set_filter_disabled_state(filter, true);
}

function unlock_attendance_filter(report, fieldname) {
    const filter = report.get_filter(fieldname);
    if (!filter) return;

    filter.df.read_only = 0;
    if (fieldname === "payroll_frequency") {
        filter.df.options = "Bimonthly\nWeekly";
    }
    filter.refresh();
    set_filter_disabled_state(filter, false);
}

function set_filter_disabled_state(filter, disabled) {
    if (filter.$input) {
        filter.$input.prop("disabled", disabled);
    }
    if (filter.$wrapper) {
        filter.$wrapper
            .toggleClass("eav-filter-locked", disabled)
            .find("input, select, textarea, button")
            .prop("disabled", disabled);
    }
}

function setup_payroll_period_filter(report, clear_value) {
    const filter = report.get_filter("payroll_period");
    if (!filter) return;

    const options = get_payroll_period_options(
        report.get_filter_value("payroll_frequency"),
        report.get_filter_value("payroll_period_mode")
    );
    filter.df.options = options.join("\n");
    filter.refresh();

    const current = report.get_filter_value("payroll_period");
    if (clear_value || (current && !options.includes(current))) {
        report.set_filter_value("payroll_period", "");
    }
}

function setup_employee_filter_options(report) {
    const filter = report.get_filter("employee");
    if (!filter) return;

    const company = report.get_filter_value("company");
    const payroll_period = report.get_filter_value("payroll_period");
    const payroll_frequency = report.get_filter_value("payroll_frequency");
    const payroll_period_mode = report.get_filter_value("payroll_period_mode");
    if (!company || !payroll_period) {
        update_employee_filter_options(report, []);
        return;
    }

    const request_key = [company, payroll_frequency, payroll_period_mode, payroll_period].join("|");
    if (report.__employee_attendance_employee_options_key === request_key) return;
    report.__employee_attendance_employee_options_key = request_key;

    frappe.call({
        method: "qcmc_logic.api.employee_attendance_schedule.get_employee_directory",
        args: {
            company,
            payroll_period,
            payroll_frequency,
            payroll_period_mode
        },
        callback: function(response) {
            const employees = (response.message && response.message.employees) || [];
            const options = employees.map((employee) => {
                const employee_name = employee.employee_name || "";
                return {
                    label: `${employee.employee} - ${employee_name}`.trim(),
                    value: employee.employee,
                    description: [
                        employee.department,
                        employee.branch,
                        employee.default_shift || employee.shift,
                    ].filter(Boolean).join(" | ")
                };
            });
            update_employee_filter_options(report, options);
        }
    });
}

function update_employee_filter_options(report, options) {
    const filter = report.get_filter("employee");
    if (!filter) return;

    const current = parse_employee_filter_value(report.get_filter_value("employee"));
    filter.df.options = options;
    filter.refresh();
    if (filter.set_data) {
        filter.set_data(options);
    }

    if (current && !options.some((option) => option.value === current)) {
        report.set_filter_value("employee", "");
    } else if (current && current !== report.get_filter_value("employee")) {
        report.set_filter_value("employee", current);
    }
}

function parse_employee_filter_value(value) {
    return (value || "").split(" - ", 1)[0].trim();
}

function get_payroll_period_options(frequency, payroll_period_mode) {
    const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
    const options = [];
    const is_weekly = frequency === "Weekly";

    for (let offset = -6; offset <= 6; offset++) {
        const base = new Date(today.getFullYear(), today.getMonth() + offset, 1);
        if (is_weekly) {
            add_weekly_options(options, base);
        } else if (payroll_period_mode === "calendar_bimonthly") {
            options.push(format_payroll_date(new Date(base.getFullYear(), base.getMonth(), 16)));
            options.push(format_payroll_date(new Date(
                base.getFullYear(),
                base.getMonth(),
                new Date(base.getFullYear(), base.getMonth() + 1, 0).getDate()
            )));
        } else {
            options.push(format_payroll_date(new Date(base.getFullYear(), base.getMonth(), 15)));
            options.push(format_payroll_date(new Date(
                base.getFullYear(),
                base.getMonth(),
                Math.min(30, new Date(base.getFullYear(), base.getMonth() + 1, 0).getDate())
            )));
        }
    }
    return Array.from(new Set(options));
}

function add_weekly_options(options, base) {
    const first = new Date(base.getFullYear(), base.getMonth(), 1);
    const last = new Date(base.getFullYear(), base.getMonth() + 1, 0);
    const sunday = new Date(first);
    sunday.setDate(first.getDate() + ((7 - first.getDay()) % 7));

    while (sunday <= last) {
        options.push(format_payroll_date(new Date(sunday)));
        sunday.setDate(sunday.getDate() + 7);
    }
}

function format_payroll_date(date_obj) {
    return `${date_obj.getMonth() + 1}/${date_obj.getDate()}/${date_obj.getFullYear()}`;
}

function install_employee_row_click(report) {
    if (report.__employee_attendance_click_installed) return;
    report.__employee_attendance_click_installed = true;

    $(report.page.wrapper).on("click", ".dt-row", function() {
        const row_index = $(this).attr("data-row-index");
        if (row_index == null || row_index < 0) return;

        const row = report.data && report.data[Number(row_index)];
        if (!row || !row.employee || row.sched_date) return;

        report.set_filter_value("employee", row.employee);
        setTimeout(() => report.refresh(), 50);
    });
}

function add_clear_employee_button(report) {
    if (report.__employee_attendance_clear_button) return;
    report.__employee_attendance_clear_button = true;

    report.page.add_inner_button(__("Show Employees"), function() {
        report.set_filter_value("employee", "");
        setTimeout(() => report.refresh(), 50);
    });
}

function render_attendance_legend(report) {
    if (!report || !report.page || !report.page.main) return;

    const has_schedule_rows = (report.data || []).some((row) => row && row.sched_date);
    let wrapper = $(report.page.main).find(".employee-attendance-viewer-legend");

    if (!has_schedule_rows) {
        wrapper.remove();
        return;
    }

    const table_left = get_report_table_left_offset(report);
    const legend_style = `display:block;width:calc(100% - ${table_left}px);margin:8px 0 10px ${table_left}px;padding:0;font-size:12px;line-height:1.4;color:var(--text-muted,#6b7280);clear:both;`;

    const legend_html = [
        ["Late", "#fff8db", "#ead58f"],
        ["Absent", "#ffe4e4", "#e8a4a4"],
        ["Leave", "#f2edff", "#c9bff3"],
        ["Holiday / Rest Day", "#e9f8ee", "#a9dcc0"],
    ].map(([label, fill, border]) => (
        `<span class="eav-legend-item" style="display:inline-flex;align-items:center;gap:5px;margin-right:12px;white-space:nowrap;vertical-align:middle;">` +
            `<span class="eav-legend-dot" style="width:10px;height:10px;min-width:10px;border-radius:50%;border:1px solid ${border};background:${fill};display:inline-block;box-sizing:border-box;"></span>` +
            `<span class="eav-legend-label" style="display:inline-block;">${__(label)}</span>` +
        `</span>`
    )).join("");

    if (!wrapper.length) {
        wrapper = $(
            `<div class="employee-attendance-viewer-legend" aria-label="${__("Attendance Legend")}" ` +
            `style="${legend_style}">` +
            `${legend_html}</div>`
        );
        const summary = $(report.page.main).find(".report-summary, .summary-section, .report-summary-wrapper").last();
        if (summary.length) {
            wrapper.insertAfter(summary);
        } else {
            wrapper.prependTo(report.page.main);
        }
    } else {
        wrapper.attr("style", legend_style);
        wrapper.html(legend_html);
    }
}

function get_report_table_left_offset(report) {
    const main = report && report.page && report.page.main;
    if (!main) return 0;

    const table = $(main).find(".datatable").first();
    if (!table.length) return 0;

    const table_left = table.offset().left;
    const main_left = $(main).offset().left;
    return Math.max(0, Math.round(table_left - main_left));
}

function apply_attendance_viewer_style() {
    if (document.getElementById("employee-attendance-viewer-report-style")) return;

    $("<style id='employee-attendance-viewer-report-style'>" +
        ".query-report .dt-row{cursor:pointer;}" +
        ".employee-attendance-viewer-legend{display:block!important;width:100%;margin:8px 0 10px 0!important;padding:0!important;font-size:12px;line-height:1.4;color:var(--text-muted,#6b7280);clear:both;}" +
        ".employee-attendance-viewer-legend .eav-legend-item{display:inline-flex!important;align-items:center;gap:5px;margin-right:12px;white-space:nowrap;vertical-align:middle;}" +
        ".employee-attendance-viewer-legend .eav-legend-dot{width:10px!important;height:10px!important;min-width:10px;border-radius:50%;border:1px solid;display:inline-block!important;box-sizing:border-box;}" +
        ".employee-attendance-viewer-legend .eav-legend-label{display:inline-block;}" +
        ".query-report .eav-filter-locked input,.query-report .eav-filter-locked select{background:var(--disabled-control-bg,#f3f3f3)!important;color:var(--text-muted,#6b7280)!important;cursor:not-allowed!important;}" +
        ".query-report .dt-cell.eav-freeze-serial,.query-report .dt-cell.eav-freeze-date,.query-report .dt-cell.eav-freeze-day{position:relative!important;z-index:50!important;will-change:transform;}" +
        ".query-report .dt-cell.eav-freeze-day{box-shadow:1px 0 0 var(--border-color,#e5e5e5);}" +
        ".query-report .dt-cell.eav-freeze-serial .dt-cell__content,.query-report .dt-cell.eav-freeze-date .dt-cell__content,.query-report .dt-cell.eav-freeze-day .dt-cell__content{background:inherit;}" +
        ".query-report .dt-row-header .dt-cell--col-0,.query-report .dt-row-header .dt-cell--col-1,.query-report .dt-row-header .dt-cell--col-2,.query-report .dt-row-filter .dt-cell--col-0,.query-report .dt-row-filter .dt-cell--col-1,.query-report .dt-row-filter .dt-cell--col-2{z-index:6;background:var(--control-bg,#f3f3f3);}" +
        ".query-report .dt-cell.eav-row-late .dt-cell__content{background:#fff8db!important;}" +
        ".query-report .dt-cell.eav-row-absent .dt-cell__content{background:#ffe4e4!important;}" +
        ".query-report .dt-cell.eav-row-leave .dt-cell__content{background:#f2edff!important;}" +
        ".query-report .dt-cell.eav-row-holiday .dt-cell__content{background:#e9f8ee!important;}" +
        ".query-report .dt-row-header .dt-cell.eav-freeze-serial,.query-report .dt-row-filter .dt-cell.eav-freeze-serial,.query-report .dt-row-header .dt-cell.eav-freeze-date,.query-report .dt-row-filter .dt-cell.eav-freeze-date,.query-report .dt-row-header .dt-cell.eav-freeze-day,.query-report .dt-row-filter .dt-cell.eav-freeze-day{z-index:60!important;background:var(--control-bg,#f3f3f3)!important;}" +
    "</style>").appendTo("head");
}

function format_colored_cell(value, background) {
    const content = value || "&nbsp;";
    return `<div style="background:${background};margin:-8px -10px;padding:8px 10px;min-height:33px;box-sizing:border-box;">${content}</div>`;
}

function get_schedule_row_color(row_class) {
    return {
        "eav-row-late": "#fff8db",
        "eav-row-absent": "#ffe4e4",
        "eav-row-leave": "#f2edff",
        "eav-row-holiday": "#e9f8ee"
    }[row_class] || "";
}

function apply_schedule_row_colors(datatable) {
    const report = frappe.query_report;
    const rows = report && report.data ? report.data : [];
    const wrapper = datatable && datatable.wrapper;
    if (!wrapper) return;

    $(wrapper).find(".dt-cell").removeClass(
        "eav-row-late eav-row-absent eav-row-leave eav-row-holiday eav-freeze-serial eav-freeze-date eav-freeze-day"
    );

    $(wrapper).find(".dt-cell--col-0").addClass("eav-freeze-serial");
    $(wrapper).find(".dt-cell--col-1").addClass("eav-freeze-date");
    $(wrapper).find(".dt-cell--col-2").addClass("eav-freeze-day");

    $(wrapper).find(".dt-row:not(.dt-row-header):not(.dt-row-filter)").each(function() {
        const row_index = Number($(this).attr("data-row-index"));
        const data = rows[row_index];
        if (!data || !data.sched_date) return;

        const row_class = get_schedule_row_class(data);
        if (row_class) {
            $(this).find(".dt-cell").addClass(row_class);
        }
    });
}

function apply_frozen_schedule_columns(datatable) {
    const wrapper = datatable && datatable.wrapper;
    if (!wrapper) return;

    const scroll_left = datatable.bodyScrollable ? datatable.bodyScrollable.scrollLeft : 0;
    const transform = scroll_left ? `translateX(${scroll_left}px)` : "";

    $(wrapper).find(".dt-cell--col-0")
        .addClass("eav-freeze-serial")
        .css({
            left: "",
            transform,
            "z-index": 52,
            background: "var(--fg-color, #fff)"
        });

    $(wrapper).find(".dt-cell--col-1")
        .addClass("eav-freeze-date")
        .css({
            left: "",
            transform,
            "z-index": 51,
            background: "var(--fg-color, #fff)"
        });

    $(wrapper).find(".dt-cell--col-2")
        .addClass("eav-freeze-day")
        .css({
            left: "",
            transform,
            "z-index": 50,
            background: "var(--fg-color, #fff)"
        });

    $(wrapper).find(".dt-row-header .dt-cell--col-0,.dt-row-filter .dt-cell--col-0,.dt-row-header .dt-cell--col-1,.dt-row-filter .dt-cell--col-1,.dt-row-header .dt-cell--col-2,.dt-row-filter .dt-cell--col-2")
        .css({
            "z-index": 61,
            background: "var(--control-bg, #f3f3f3)"
        });
}

function install_datatable_repaint(datatable) {
    if (!datatable || !datatable.bodyScrollable || datatable.__employee_attendance_repaint) return;
    datatable.__employee_attendance_repaint = true;

    let repaint_timer = null;
    $(datatable.bodyScrollable).on("scroll.employee_attendance_viewer", function() {
        window.requestAnimationFrame(() => apply_frozen_schedule_columns(datatable));
        clearTimeout(repaint_timer);
        repaint_timer = setTimeout(() => {
            apply_schedule_row_colors(datatable);
            apply_frozen_schedule_columns(datatable);
        }, 40);
    });
}

function get_schedule_row_class(row) {
    const is_holiday = !!row.holiday_type || !!row.rest_day;
    const is_absent = row.attendance_status === "Absent" ||
        (!!row.sched_time_start && !row.time_in && !row.leave_type && !is_holiday);

    if (is_holiday) return "eav-row-holiday";
    if (row.leave_type) return "eav-row-leave";
    if (is_absent) return "eav-row-absent";
    if (flt(row.late_hours) > 0) return "eav-row-late";
    return "";
}
