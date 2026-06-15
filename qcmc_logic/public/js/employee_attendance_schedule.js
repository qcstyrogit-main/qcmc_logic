frappe.ui.form.on("Employee Attendance Schedule", {
    async setup(frm) {
        setup_employee_attendance_defaults(frm);
    },

    async onload(frm) {
        setup_employee_attendance_defaults(frm);
    },

    async refresh(frm) {
        setup_employee_attendance_defaults(frm);
    }
});

async function setup_employee_attendance_defaults(frm) {
    setup_employee_attendance_payroll_options(frm);
    [100, 500, 1000].forEach((delay) => {
        setTimeout(() => setup_employee_attendance_defaults_once(frm), delay);
    });

    await setup_employee_attendance_defaults_once(frm);
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
