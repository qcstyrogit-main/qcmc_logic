frappe.pages["weekly-manpower-schedule-workbench"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Weekly Manpower Schedule Workbench"),
		single_column: true,
	});
	wrapper.weekly_manpower_schedule_workbench = new WeeklyManpowerScheduleWorkbench(page);
};

frappe.pages["weekly-manpower-schedule-workbench"].on_page_show = function (wrapper) {
	wrapper.weekly_manpower_schedule_workbench?.refresh_from_route();
};

const WMS_DAYS = [
	["monday", __("Mon")],
	["tuesday", __("Tue")],
	["wednesday", __("Wed")],
	["thursday", __("Thu")],
	["friday", __("Fri")],
	["saturday", __("Sat")],
	["sunday", __("Sun")],
];
const WMS_STATUSES = ["", "NW", "RD", "PW", "X"];
const WMS_COLUMN_WIDTHS = [
	50, 100, 60, 82,
	182, 190, ...Array(7).fill(45),
	182, 190, ...Array(7).fill(45),
	32,
];
const WMS_ROW_FIELDS = [
	"sortingno",
	"location",
	"section",
	"position",
	"machine",
	...["day_shift", "night_shift"].flatMap((shift) => [
		`${shift}_type`,
		`${shift}_employee`,
		`${shift}_ps`,
		`${shift}_nosched_code`,
		...WMS_DAYS.map(([day]) => `${shift}_${day}`),
	]),
];

class WeeklyManpowerScheduleWorkbench {
	constructor(page) {
		this.page = page;
		this.name = frappe.get_route()[1];
		this.rows = [];
		this.filters = {};
		this.load_sequence = 0;
		this.employees = [];
		this.shift_types = [];
		this.can_edit = false;
		this.dirty = false;
		this.saving = false;
		this.column_widths = [...WMS_COLUMN_WIDTHS];
		this.setup_actions();
		this.setup_body();
		window.addEventListener("beforeunload", (event) => {
			if (this.dirty || this.saving) {
				event.preventDefault();
				event.returnValue = "";
			}
		});
	}

	setup_actions() {
		this.page.set_primary_action(__("Save"), () => this.save(), "save");
		this.page.add_inner_button(__("Add Row"), () => this.add_row());
		this.page.add_inner_button(__("Load Active Employees"), () => this.load_active_employees());
		this.page.add_inner_button(__("Back to Schedule"), () => this.back_to_schedule());
	}

	setup_body() {
		this.page.main.html(`
			<div class="wms-workbench">
				<div class="wms-workbench-heading text-muted"></div>
				<div class="wms-schedule-selector"></div>
				<div class="wms-workbench-summary text-muted small"></div>
				<datalist id="wms-employee-options"></datalist>
				<div class="wms-workbench-table-wrapper">
					<table class="table table-bordered table-sm wms-workbench-table">
						<colgroup>${this.column_widths.map((width) => `<col style="width: ${width}px">`).join("")}</colgroup>
						<thead></thead>
						<tbody></tbody>
					</table>
				</div>
			</div>
		`);
		this.$schedule_selector = this.page.main.find(".wms-schedule-selector");
		this.$heading = this.page.main.find(".wms-workbench-heading");
		this.$summary = this.page.main.find(".wms-workbench-summary");
		this.$employee_list = this.page.main.find("#wms-employee-options");
		this.$thead = this.page.main.find("thead");
		this.$tbody = this.page.main.find("tbody");
		this.$table = this.page.main.find(".wms-workbench-table");
		this.set_table_width();
		this.setup_schedule_selector();
		this.add_styles();
		this.$thead.on("input change", "[data-filter-field]", (event) => {
			const fieldname = event.currentTarget.dataset.filterField;
			this.filters[fieldname] = event.currentTarget.value;
			this.render_rows();
			this.update_summary();
		});
		this.$thead.on("pointerdown", ".wms-column-resizer", (event) => this.start_column_resize(event));
		this.$thead.on("keydown", ".wms-column-resizer", (event) => this.resize_column_by_keyboard(event));
		this.$tbody.on("input change", "[data-row][data-field]", (event) => this.update_cell(event));
		this.$tbody.on("click", "[data-action='remove-row']", (event) => {
			const index = Number(event.currentTarget.dataset.row);
			this.rows.splice(index, 1);
			this.set_dirty();
			this.render();
		});
	}

	setup_schedule_selector() {
		this.schedule_control = frappe.ui.form.make_control({
			parent: this.$schedule_selector,
			df: {
				fieldname: "schedule",
				label: __("Weekly Manpower Schedule"),
				fieldtype: "Link",
				options: "Weekly Manpower Schedule",
				reqd: 1,
				change: () => {
					if (!this.setting_schedule_value) {
						this.select_schedule(this.schedule_control.get_value());
					}
				},
			},
			render_input: true,
		});
		this.set_schedule_value(this.name);
	}

	set_schedule_value(name) {
		this.setting_schedule_value = true;
		this.schedule_control.set_value(name || "");
		this.setting_schedule_value = false;
	}

	select_schedule(name) {
		if (!name) {
			this.set_schedule_value(this.name);
			return;
		}
		if (name === this.name) return;
		if (this.saving) {
			frappe.msgprint(__("Wait for the current schedule to finish saving before switching schedules."));
			this.set_schedule_value(this.name);
			return;
		}
		if (this.dirty) {
			frappe.confirm(
				__("Discard unsaved changes and open schedule {0}?", [name]),
				() => this.load(name),
				() => this.set_schedule_value(this.name),
			);
			return;
		}
		this.load(name);
	}

	refresh_from_route() {
		const name = frappe.get_route()[1];
		if (!name) return;
		if (this.skip_show_refresh === name) {
			this.skip_show_refresh = null;
			return;
		}
		if (this.saving) {
			frappe.msgprint(__("Wait for the current schedule to finish saving before switching schedules."));
			this.restore_route();
			return;
		}
		if (this.dirty) {
			frappe.confirm(
				__("Discard unsaved changes and reload schedule {0} from its parent record?", [name]),
				() => this.load(name),
				() => this.restore_route(),
			);
			return;
		}
		this.load(name);
	}

	restore_route() {
		this.set_schedule_value(this.name);
		if (frappe.get_route()[1] !== this.name) {
			this.skip_show_refresh = this.name;
			frappe.set_route("weekly-manpower-schedule-workbench", this.name);
		}
	}

	add_styles() {
		frappe.dom.set_style(`
			.wms-workbench-heading { margin-bottom: 8px; }
			.wms-schedule-selector {
				position: relative;
				z-index: 20;
				max-width: 420px;
				margin-bottom: 10px;
			}
			.wms-workbench-summary { margin-bottom: 10px; }
			.wms-workbench-table-wrapper {
				overflow: auto;
				max-height: calc(100vh - 230px);
				border: 1px solid var(--border-color);
				border-radius: 6px;
			}
			.wms-workbench-table {
				min-width: 0;
				margin-bottom: 0;
				background: var(--fg-color);
				font-size: 11px;
				border-collapse: separate;
				border-spacing: 0;
				table-layout: fixed;
			}
			.wms-workbench-table thead th {
				position: sticky;
				top: 0;
				z-index: 2;
				background: var(--gray-100);
				white-space: nowrap;
			}
			.wms-workbench-table thead tr:nth-child(2) th { top: 28px; }
			.wms-workbench-table thead tr.wms-filter-row th {
				top: 56px;
				z-index: 3;
			}
			.wms-workbench-table td,
			.wms-workbench-table th {
				padding: 3px 4px !important;
				vertical-align: middle !important;
			}
			.wms-workbench-table tbody td {
				padding-top: 0.5px !important;
				padding-bottom: 0.5px !important;
			}
			.wms-workbench-table tbody input:not([type="checkbox"]),
			.wms-workbench-table tbody select {
				min-width: 0;
				width: 100%;
				height: 26px;
				padding: 2px 4px;
				color: var(--text-color);
				background: var(--control-bg);
				border: 1px solid var(--border-color);
				border-radius: var(--border-radius-sm);
			}
			.wms-workbench-table .wms-filter-row input {
				height: 22px;
				padding: 1px 2px;
				font-size: 10px;
			}
			.wms-workbench-table .wms-location-cell input {
				box-sizing: border-box;
				min-width: 0;
				width: 100%;
				padding-left: 0;
				padding-right: 0;
			}
			.wms-workbench-table .wms-location-cell {
				box-sizing: border-box;
				width: 50px;
				min-width: 50px;
				max-width: 50px;
				overflow: hidden;
				white-space: nowrap;
				padding-left: 0 !important;
				padding-right: 0 !important;
			}
			.wms-workbench-table .wms-position-cell {
				box-sizing: border-box;
				width: 60px;
				min-width: 60px;
				max-width: 60px;
				overflow: hidden;
				white-space: nowrap;
				padding-left: 0 !important;
				padding-right: 0 !important;
			}
			.wms-workbench-table .wms-position-cell input {
				box-sizing: border-box;
				min-width: 0;
				width: 100%;
				padding-left: 0;
				padding-right: 0;
			}
			.wms-workbench-table .wms-day-column {
				box-sizing: border-box;
				min-width: 0;
				padding-left: 0 !important;
				padding-right: 0 !important;
			}
			.wms-workbench-table .wms-filter-row .wms-day-column input {
				box-sizing: border-box;
				min-width: 0;
				width: 100%;
				padding: 1px 0;
				appearance: none;
			}
			.wms-workbench-table .wms-column-header { padding-right: 10px !important; }
			.wms-workbench-table .wms-column-header.wms-day-column { padding-right: 0 !important; }
			.wms-workbench-table .wms-column-resizer {
				position: absolute;
				top: 0;
				right: 0;
				bottom: 0;
				width: 8px;
				cursor: col-resize;
				touch-action: none;
				z-index: 4;
			}
			.wms-workbench-table .wms-column-resizer:hover,
			.wms-workbench-table .wms-column-resizer:focus {
				background: var(--blue-200);
				outline: none;
			}
			.wms-workbench-table.wms-resizing,
			.wms-workbench-table.wms-resizing * {
				cursor: col-resize !important;
				user-select: none !important;
			}
			.wms-workbench-table .wms-employee-control {
				display: flex;
				gap: 3px;
				align-items: center;
			}
			.wms-workbench-table .wms-employee-control input:not([type="checkbox"]) {
				flex: 1;
				min-width: 0;
			}
			.wms-workbench-table .wms-ps-toggle {
				margin: 0;
				white-space: nowrap;
				font-size: 10px;
			}
			.wms-workbench-table .wms-employee-name {
				display: block;
				min-height: 16px;
				margin-top: 2px;
			}
			.wms-workbench-table .wms-status-cell select {
				box-sizing: border-box;
				min-width: 0;
				width: 100%;
				padding: 0;
				font-size: 10px;
			}
			.wms-workbench-table .wms-remove-cell { width: 32px; text-align: center; }
			.wms-workbench-table tbody tr:nth-child(even) td { background: var(--gray-50); }
			.wms-workbench-table tbody tr:hover td { background: var(--highlight-color); }
		`);
	}

	column_header(label, column_index, class_name = "", rowspan = 1, full_label = label) {
		const escaped_label = frappe.utils.escape_html(label);
		const escaped_full_label = frappe.utils.escape_html(full_label);
		const aria_label = frappe.utils.escape_html(
			__("Resize {0} column", [full_label || __("Remove Row")])
		);
		return `<th ${rowspan > 1 ? `rowspan="${rowspan}"` : ""} class="${class_name} wms-column-header" title="${escaped_full_label}">${escaped_label}<span class="wms-column-resizer" role="separator" aria-orientation="vertical" aria-label="${aria_label}" aria-valuenow="${this.column_widths[column_index]}" tabindex="0" data-column-index="${column_index}" title="${aria_label}"></span></th>`;
	}

	set_table_width() {
		const width = this.column_widths.reduce((total, column_width) => total + column_width, 0);
		this.$table.css("width", `${width}px`);
	}

	minimum_column_width(column_index) {
		if (column_index === 22) return 32;
		if (column_index === 0) return 50;
		if (column_index === 2) return 60;
		if ([5, 14].includes(column_index)) return 120;
		if ([6, 7, 8, 9, 10, 11, 12, 15, 16, 17, 18, 19, 20, 21].includes(column_index)) return 20;
		return 60;
	}

	start_column_resize(event) {
		event.preventDefault();
		const handle = event.currentTarget;
		const column_index = Number(handle.dataset.columnIndex);
		const start_x = event.clientX;
		const start_width = this.column_widths[column_index];
		const table = this.$thead.closest("table")[0];
		const column = table.querySelectorAll("colgroup col")[column_index];
		const min_width = this.minimum_column_width(column_index);

		table.classList.add("wms-resizing");
		const resize = (move_event) => {
			const width = Math.max(min_width, Math.min(600, start_width + move_event.clientX - start_x));
			this.column_widths[column_index] = width;
			column.style.width = `${width}px`;
			this.set_table_width();
			handle.setAttribute("aria-valuenow", width);
		};
		const finish = () => {
			table.classList.remove("wms-resizing");
			document.removeEventListener("pointermove", resize);
			document.removeEventListener("pointerup", finish);
			document.removeEventListener("pointercancel", finish);
		};

		document.addEventListener("pointermove", resize);
		document.addEventListener("pointerup", finish, { once: true });
		document.addEventListener("pointercancel", finish, { once: true });
	}

	resize_column_by_keyboard(event) {
		if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
		event.preventDefault();
		const handle = event.currentTarget;
		const column_index = Number(handle.dataset.columnIndex);
		const current_width = this.column_widths[column_index];
		const min_width = this.minimum_column_width(column_index);
		const change = event.key === "ArrowRight" ? 10 : -10;
		const width = Math.max(min_width, Math.min(600, current_width + change));
		this.column_widths[column_index] = width;
		this.$thead.closest("table").find("colgroup col").eq(column_index).css("width", `${width}px`);
		this.set_table_width();
		handle.setAttribute("aria-valuenow", width);
	}

	async load(name = this.name) {
		if (!name) {
			frappe.msgprint(__("Select a saved Weekly Manpower Schedule to load its workbench."));
			return;
		}
		const load_sequence = ++this.load_sequence;
		try {
			const response = await frappe.call({
				method: "qcmc_logic.qcmc_logics.page.weekly_manpower_schedule_workbench.weekly_manpower_schedule_workbench.get_data",
				args: { name },
				freeze: true,
				freeze_message: __("Loading schedule details..."),
			});
			const data = response.message;
			if (!data) throw new Error(__("The schedule data could not be loaded."));
			if (load_sequence !== this.load_sequence) return;
			const schedule_changed = this.name !== data.name;
			this.name = data.name;
			if (schedule_changed) {
				this.filters = {};
				this.dirty = false;
				this.set_schedule_value(this.name);
				this.skip_show_refresh = this.name;
				frappe.set_route("weekly-manpower-schedule-workbench", this.name);
			}
			this.schedule = data;
			this.rows = data.rows || [];
			this.employees = data.employees || [];
			this.shift_types = data.shift_types || [];
			this.can_edit = Boolean(data.can_edit);
			this.$heading.text(
				`${data.name} · ${data.section || ""} · ${data.week_start || ""} – ${data.week_end || ""} · ${data.workflow_state || ""}`
			);
			this.page.set_primary_action(
				__("Save"),
				() => this.save(),
				"save"
			);
			this.set_save_enabled(this.can_edit && this.dirty);
			this.render();
		} catch (error) {
			if (load_sequence !== this.load_sequence) return;
			this.set_schedule_value(this.name);
			frappe.msgprint({
				title: __("Unable to Load Schedule"),
				message: error.message || __("An error occurred while loading this schedule."),
				indicator: "red",
			});
		}
	}

	employee_options() {
		const options = new Map(this.employees.map((employee) => [
			employee.name,
			`${employee.name} - ${employee.employee_name || employee.name}`,
		]));
		for (const row of this.rows) {
			for (const shift of ["day_shift", "night_shift"]) {
				const code = row[`${shift}_employee`];
				if (code && !options.has(code)) {
					options.set(code, `${code} - ${row[`${shift}_employee_name`] || code}`);
				}
			}
		}
		return [...options.entries()].map(([value, label]) => ({ value, label }));
	}

	select_html(options, value, index, fieldname, disabled = false) {
		const escape = frappe.utils.escape_html;
		const items = options.map((option) => {
			const option_value = typeof option === "string" ? option : option.value;
			const label = typeof option === "string" ? option : option.label;
			const selected = String(value || "").toUpperCase() === String(option_value).toUpperCase();
			return `<option value="${escape(option_value)}" ${selected ? "selected" : ""}>${escape(label)}</option>`;
		}).join("");
		return `<select data-row="${index}" data-field="${fieldname}" ${disabled ? "disabled" : ""}>${items}</select>`;
	}

	text_input(value, index, fieldname, disabled = false) {
		return `<input type="text" data-row="${index}" data-field="${fieldname}" value="${frappe.utils.escape_html(value || "")}" ${disabled ? "disabled" : ""}>`;
	}

	employee_cell(row, index, shift) {
		const ps_field = `${shift}_ps`;
		const employee_field = `${shift}_employee`;
		const plan_stop = Number(row[ps_field]) === 1;
		const selected_name = plan_stop
			? ""
			: this.employees.find((item) => item.name === row[employee_field])?.employee_name
			|| row[`${shift}_employee_name`]
			|| "";
		return `<td class="wms-employee-cell">
			<div class="wms-employee-control">
				<label class="wms-ps-toggle"><input type="checkbox" data-row="${index}" data-field="${ps_field}" ${plan_stop ? "checked" : ""} ${this.can_edit ? "" : "disabled"}> ${__("PS (PLAN STOP)")}</label>
				${plan_stop
				? `<strong>${__("PLAN STOP")}</strong>`
				: this.text_input(row[employee_field], index, employee_field, !this.can_edit).replace("<input ", '<input list="wms-employee-options" ')}
			</div>
			<small class="text-muted wms-employee-name">${frappe.utils.escape_html(selected_name)}</small>
		</td>`;
	}

	status_cell(row, index, shift, day) {
		const fieldname = `${shift}_${day}`;
		return `<td class="wms-status-cell wms-day-column">${this.select_html(WMS_STATUSES, row[fieldname], index, fieldname, !this.can_edit)}</td>`;
	}

	filter_cell(fieldname, label) {
		const escaped_fieldname = frappe.utils.escape_html(fieldname);
		const aria_label = frappe.utils.escape_html(__("Filter {0}", [label]));
		const placeholder = frappe.utils.escape_html(__("Filter"));
		const is_day_filter = /_(monday|tuesday|wednesday|thursday|friday|saturday|sunday)$/.test(fieldname);
		const field_class = is_day_filter
			? "wms-status-cell wms-day-column"
			: fieldname === "location"
				? "wms-location-cell"
				: fieldname === "position"
					? "wms-position-cell"
					: "";
		return `<th class="${field_class}"><input type="search" data-filter-field="${escaped_fieldname}" aria-label="${aria_label}" placeholder="${is_day_filter ? "" : placeholder}" title="${aria_label}" value="${frappe.utils.escape_html(this.filters[fieldname] || "")}"></th>`;
	}

	render() {
		if (!this.$tbody) return;
		this.$employee_list.html(this.employee_options().map((employee) =>
			`<option value="${frappe.utils.escape_html(employee.value)}" label="${frappe.utils.escape_html(employee.label)}"></option>`
		).join(""));
		const compact_day_labels = ["M", "T", "W", "Th", "F", "Sa", "Su"];
		const day_filters = (shift) => WMS_DAYS.map(([day, label]) =>
			this.filter_cell(`${shift}_${day}`, label)
		).join("");
		this.$thead.html(`
			<tr>
				<th rowspan="2" class="wms-location-cell" title="${__("Location")}">${__("Location")}</th>
				${this.column_header(__("Section"), 1, "wms-section-cell", 2)}
				${this.column_header(__("Position"), 2, "wms-position-cell", 2)}
				${this.column_header(__("Machine"), 3, "wms-machine-cell", 2)}
				<th colspan="9" class="text-center">${__("Day Shift")}</th>
				<th colspan="9" class="text-center">${__("Night Shift")}</th>
				${this.column_header("", 22, "wms-remove-cell", 2)}
			</tr>
			<tr>
				${this.column_header(__("Shift Type"), 4, "wms-shift-type-cell")}
				${this.column_header(__("Employee / PS (PLAN STOP)"), 5, "wms-employee-cell")}
				${WMS_DAYS.map(([, label], index) => this.column_header(compact_day_labels[index], 6 + index, "wms-status-cell wms-day-column", 1, label)).join("")}
				${this.column_header(__("Shift Type"), 13, "wms-shift-type-cell")}
				${this.column_header(__("Employee / PS (PLAN STOP)"), 14, "wms-employee-cell")}
				${WMS_DAYS.map(([, label], index) => this.column_header(compact_day_labels[index], 15 + index, "wms-status-cell wms-day-column", 1, label)).join("")}
			</tr>
			<tr class="wms-filter-row">
				${this.filter_cell("location", __("Location"))}
				${this.filter_cell("section", __("Section"))}
				${this.filter_cell("position", __("Position"))}
				${this.filter_cell("machine", __("Machine"))}
				${this.filter_cell("day_shift_type", __("Day Shift Type"))}
				${this.filter_cell("day_shift_employee", __("Day Shift Employee"))}
				${day_filters("day_shift")}
				${this.filter_cell("night_shift_type", __("Night Shift Type"))}
				${this.filter_cell("night_shift_employee", __("Night Shift Employee"))}
				${day_filters("night_shift")}
				<th></th>
			</tr>
		`);
		this.render_rows();
		this.update_summary();
	}

	filtered_rows() {
		return this.rows
			.map((row, index) => ({ row, index }))
			.filter(({ row }) => Object.entries(this.filters).every(([fieldname, filter]) => {
				const query = String(filter || "").trim().toLocaleLowerCase();
				if (!query) return true;
				let value = String(row[fieldname] ?? "");
				if (fieldname.endsWith("_employee")) {
					const shift = fieldname.slice(0, -9);
					const plan_stop = Number(row[`${shift}_ps`]) === 1;
					value += ` ${row[`${shift}_employee_name`] || ""} ${plan_stop ? "PS PLAN STOP" : ""}`;
				}
				return value.toLocaleLowerCase().includes(query);
			}));
	}

	render_rows() {
		this.$tbody.html(this.filtered_rows().map(({ row, index }) => `
			<tr>
				<td class="wms-location-cell">${this.text_input(row.location, index, "location", !this.can_edit)}</td>
				<td class="wms-section-cell">${this.text_input(row.section, index, "section", !this.can_edit)}</td>
				<td class="wms-position-cell">${this.text_input(row.position, index, "position", !this.can_edit)}</td>
				<td class="wms-machine-cell">${this.text_input(row.machine, index, "machine", !this.can_edit)}</td>
				<td class="wms-shift-type-cell">${this.select_html([{ value: "", label: __("- Select Shift -") }, ...this.shift_types.map((item) => ({ value: item.name, label: item.name }))], row.day_shift_type, index, "day_shift_type", !this.can_edit)}</td>
				${this.employee_cell(row, index, "day_shift")}
				${WMS_DAYS.map(([day]) => this.status_cell(row, index, "day_shift", day)).join("")}
				<td class="wms-shift-type-cell">${this.select_html([{ value: "", label: __("- Select Shift -") }, ...this.shift_types.map((item) => ({ value: item.name, label: item.name }))], row.night_shift_type, index, "night_shift_type", !this.can_edit)}</td>
				${this.employee_cell(row, index, "night_shift")}
				${WMS_DAYS.map(([day]) => this.status_cell(row, index, "night_shift", day)).join("")}
				<td class="wms-remove-cell">${this.can_edit ? `<button class="btn btn-xs btn-default" data-action="remove-row" data-row="${index}" title="${__("Remove Row")}">${frappe.utils.icon("delete")}</button>` : ""}</td>
			</tr>
		`).join(""));
	}

	update_summary() {
		const state = this.dirty ? __("Unsaved changes") : __("All changes saved");
		this.$summary.text(__("{0} of {1} row(s) shown · {2}", [
			this.filtered_rows().length,
			this.rows.length,
			this.can_edit ? state : __("Read only"),
		]));
	}

	update_cell(event) {
		const target = event.currentTarget;
		const index = Number(target.dataset.row);
		const fieldname = target.dataset.field;
		const row = this.rows[index];
		if (!row || !fieldname) return;

		const value = target.type === "checkbox" ? Number(target.checked) : target.value;
		row[fieldname] = value;
		if (fieldname.endsWith("_ps")) {
			const shift = fieldname.slice(0, -3);
			if (value) {
				row[`${shift}_employee`] = "";
				row[`${shift}_employee_name`] = "";
				row[`${shift}_nosched_code`] = "NOSCHED";
				for (const [day] of WMS_DAYS) {
					row[`${shift}_${day}`] = "X";
				}
			} else {
				row[`${shift}_nosched_code`] = "";
			}
			const $row = $(target).closest("tr");
			$row.find(`[data-field^="${shift}_"]`).each((_, field) => {
				const day = field.dataset.field.slice(shift.length + 1);
				if (WMS_DAYS.some(([day_name]) => day_name === day)) {
					$(field).val(row[field.dataset.field]);
				}
			});
			$(target).closest("td").replaceWith(this.employee_cell(row, index, shift));
			this.set_dirty();
			return;
		}
		if (fieldname.endsWith("_employee")) {
			const shift = fieldname.slice(0, -9);
			row[`${shift}_employee_name`] = this.employees.find((item) => item.name === value)?.employee_name || "";
			$(target).closest("td").find(".wms-employee-name").text(row[`${shift}_employee_name`]);
		}
		this.set_dirty();
	}

	set_dirty() {
		this.dirty = true;
		this.update_summary();
		this.set_save_enabled(this.can_edit && !this.saving);
	}

	set_save_enabled(enabled) {
		this.page.btn_primary.prop("disabled", !enabled);
	}

	add_row() {
		if (!this.can_edit) return;
		const row = { day_shift_ps: 0, night_shift_ps: 0 };
		for (const fieldname of WMS_ROW_FIELDS) {
			if (row[fieldname] === undefined) {
				row[fieldname] = /_(monday|tuesday|wednesday|thursday|friday|saturday|sunday)$/.test(fieldname)
					? "X"
					: "";
			}
		}
		this.rows.push(row);
		this.set_dirty();
		this.render();
	}

	load_active_employees() {
		if (!this.can_edit) return;
		const replace = () => {
			this.rows = this.employees.map((employee) => {
				const row = { day_shift_employee: employee.name, day_shift_type: employee.default_shift || "" };
				for (const fieldname of WMS_ROW_FIELDS) {
					if (row[fieldname] === undefined) {
						row[fieldname] = /_(monday|tuesday|wednesday|thursday|friday|saturday|sunday)$/.test(fieldname)
							? "X"
							: "";
					}
				}
				row.location = employee.branch || "";
				row.position = employee.designation || "";
				row.day_shift_employee_name = employee.employee_name || "";
				return row;
			});
			this.set_dirty();
			this.render();
		};
		if (this.rows.length) {
			frappe.confirm(
				__("Replace the current {0} row(s) with {1} active employee(s)?", [this.rows.length, this.employees.length]),
				replace,
			);
		} else if (this.employees.length) {
			replace();
		} else {
			frappe.msgprint(__("No active employees were found for this Company and Section."));
		}
	}

	async save() {
		if (!this.can_edit || !this.dirty || this.saving) return;
		this.saving = true;
		this.set_save_enabled(false);
		try {
			const rows = this.rows.map((row) => Object.fromEntries(
				WMS_ROW_FIELDS.map((fieldname) => [fieldname, row[fieldname] ?? ""])
			));
			const response = await frappe.call({
				method: "qcmc_logic.qcmc_logics.page.weekly_manpower_schedule_workbench.weekly_manpower_schedule_workbench.save",
				args: { name: this.name, rows },
				freeze: true,
				freeze_message: __("Saving schedule details..."),
			});
			if (!response.message?.doc) throw new Error(__("The saved schedule could not be synchronized."));
			frappe.model.sync(response.message.doc);
			this.dirty = false;
			frappe.show_alert({ message: __("Schedule details saved."), indicator: "green" });
		} catch (error) {
			frappe.msgprint({
				title: __("Unable to Save Schedule"),
				message: error.message || __("An error occurred while saving schedule details."),
				indicator: "red",
			});
		} finally {
			this.saving = false;
			this.set_save_enabled(this.can_edit && this.dirty);
			this.render();
		}
	}

	back_to_schedule() {
		const navigate = () => frappe.set_route("Form", "Weekly Manpower Schedule", this.name);
		if (this.dirty) {
			frappe.confirm(__("Discard unsaved schedule changes and return to the document?"), navigate);
			return;
		}
		navigate();
	}
}
