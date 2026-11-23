frappe.pages["process-card-workbench"].ui_version = "pcw-create-ui-20261110-4";

frappe.pages["process-card-workbench"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Process Card Workbench"), single_column: true });
	wrapper.process_card_workbench = new ProcessCardWorkbench(page);
};

frappe.pages["process-card-workbench"].on_page_show = function (wrapper) {
	const workbench = wrapper.process_card_workbench;
	const route_card = frappe.get_route()[1] || frappe.route_options?.process_card || null;
	if (workbench && workbench.route_key !== route_card) workbench.load_from_route();
};

const PROCESS_CARD_WORKBENCH_API = "qcmc_logic.api.process_card_workbench.";
const JOB_CARD_TIME_LOG_API = "qcmc_logic.api.job_card_time_log.";
const pcwEscape = value => frappe.utils.escape_html(String(value ?? ""));

class ProcessCardWorkbench {
	constructor(page) {
		this.page = page;
		this.process_card = null;
		this.context = null;
		this.load_sequence = 0;
		this.loading = false;
		this.error = null;
		this.output_pending = false;
		this.encoding_mode = "mobile";
		this.history_filter = {job_card: "", date: ""};
		this.batch = null;
		this.batch_pending = false;
		this.creation = null;
		this.creation_pending = false;
		this.page.main.html(`<div class="pcw"><div class="pcw-state" role="status"></div><div class="pcw-content"></div></div>${ProcessCardWorkbench.css}`);
		this.$root = this.page.main.find(".pcw");
		this.page.add_inner_button(__("Back to Floor Navigator"), () => this.return_to_floor());
		this.page.add_inner_button(__("Refresh"), () => this.load_from_route());
		this.$root.on("click", "[data-action]", event => this.handle_action(event.currentTarget.dataset.action, event.currentTarget.dataset.id));
		this.$root.on("change", ".pcw-output-from, .pcw-output-to, .pcw-output-job, .pcw-output-good, .pcw-output-rejected, .pcw-output-remarks", () => { this.remember_mobile_entry(); this.render_mobile_quantity_balance(); this.preview_mobile_metrics(); });
		this.$root.on("input", ".pcw-output-good, .pcw-output-rejected, .pcw-output-from, .pcw-output-to", () => this.preview_mobile_metrics());
		this.$root.on("change input", ".pcw-batch-date, .pcw-batch-building, .pcw-batch-from, .pcw-batch-to", () => this.remember_batch_period());
		this.$root.on("change", ".pcw-history-job, .pcw-history-date", event => {
			this.history_filter = {job_card: this.$root.find(".pcw-history-job").val() || "", date: this.$root.find(".pcw-history-date").val() || ""};
			this.render_history();
		});
		this.$root.on("input change", ".pcw-batch-cell", event => this.update_batch_cell(event.currentTarget));
		this.$root.on("change", ".pcw-create-shift-date, .pcw-create-shift-start, .pcw-create-shift-end, .pcw-create-remarks", event => {
			const action = event.currentTarget.dataset.action;
			if (action) this.handle_action(action, event.currentTarget.dataset.id);
		});
		this.load_from_route();
	}

	async call(method, args = {}) {
		const response = await frappe.call({method: PROCESS_CARD_WORKBENCH_API + method, args, type: "GET"});
		return response.message;
	}

	async call_output(method, args = {}) {
		const response = await frappe.call({method: JOB_CARD_TIME_LOG_API + method, args, type: "POST"});
		if (response.message?.success === false) throw new Error(response.message.message || __("Output could not be saved."));
		return response.message;
	}

	async call_post(method, args = {}) {
		const response = await frappe.call({method: PROCESS_CARD_WORKBENCH_API + method, args, type: "POST"});
		return response.message;
	}

	async load_from_route() {
		const name = frappe.get_route()[1] || frappe.route_options?.process_card;
		this.route_key = name || null;
		const sequence = this.load_sequence = (this.load_sequence || 0) + 1;
		if (name === "new") {
			this.process_card = null;
			this.context = null;
			this.creation = null;
			this.error = null;
			this.loading = true;
			this.render();
			try {
				const saved = sessionStorage.getItem("qcmc_process_card_create_context");
				if (!saved) throw new Error(__("Open Process Card creation from a selected machine in the Production Floor Navigator."));
				const defaults = JSON.parse(saved);
				const context = await this.call("get_process_card_creation_context", {
					company: defaults.company, site: defaults.site, workstation: defaults.workstation,
					shift_date: defaults.shift_date, shift_type: defaults.shift_type || null,
				});
				if (sequence !== this.load_sequence || frappe.get_route()[1] !== "new") return;
				this.creation = {...defaults, ...context, selected_job_cards: [], search: "", remarks: ""};
				this.apply_shift_type_times(false);
			} catch (error) {
				if (sequence !== this.load_sequence) return;
				this.error = error?.message || __("Could not open Process Card creation. Check machine and create permissions.");
			} finally {
				if (sequence === this.load_sequence) {
					this.loading = false;
					try {
						this.render();
					} catch (renderError) {
						this.creation = null;
						this.error = renderError?.message || __("Could not render Process Card creation. Refresh the page and try again.");
						this.$root.find(".pcw-state").html(`<div class="alert alert-danger">${pcwEscape(this.error)}</div>`);
						this.$root.find(".pcw-content").empty();
					}
				}
			}
			return;
		}
		if (name === "batch") {
			this.creation = null;
			this.process_card = null;
			this.context = null;
			this.error = null;
			this.batch = this.batch || this.load_batch_defaults();
			this.encoding_mode = "batch";
			this.loading = false;
			this.render();
			return;
		}
		this.creation = null;
		this.process_card = name || null;
		this.encoding_mode = name ? this.load_encoding_mode(name) : "mobile";
		this.context = null;
		this.error = null;
		if (!name) { this.render(); return; }
		this.loading = true; this.render();
		try {
			const context = await this.call("get_process_card_context", {process_card: name});
			if (sequence !== this.load_sequence || name !== (frappe.get_route()[1] || name)) return;
			this.context = context;
		} catch (error) {
			if (sequence !== this.load_sequence) return;
			this.error = __("Could not load this Process Card. Check your access or refresh to try again.");
		} finally {
			if (sequence === this.load_sequence) { this.loading = false; this.render(); }
		}
	}

	apply_shift_type_times(force = true) {
		if (!this.creation) return;
		const shift = (this.creation.shift_types || []).find(row => row.name === this.creation.shift_type);
		if (!shift?.start_time || !shift?.end_time) return;
		const shiftDate = this.creation.shift_date;
		const startTime = this.time_value(shift.start_time);
		let endDate = shiftDate;
		if (this.time_value(shift.end_time) <= startTime) {
			const next = new Date(`${shiftDate}T00:00:00`);
			next.setDate(next.getDate() + 1);
			endDate = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}-${String(next.getDate()).padStart(2, "0")}`;
		}
		if (force || !this.creation.shift_start) this.creation.shift_start = `${shiftDate}T${startTime}`;
		if (force || !this.creation.shift_end) this.creation.shift_end = `${endDate}T${this.time_value(shift.end_time)}`;
	}

	change_creation_shift_type(value) {
		if (!this.creation) return;
		const shiftType = value || "";
		if (shiftType === (this.creation.shift_type || "")) return;
		this.creation.shift_type = shiftType;
		this.creation.shift_start = "";
		this.creation.shift_end = "";
		this.apply_shift_type_times(false);
		// Keep the active Link input mounted while updating its dependent fields.
		this.$root.find(".pcw-create-shift-start").val(this.creation.shift_start || "");
		this.$root.find(".pcw-create-shift-end").val(this.creation.shift_end || "");
	}

	time_value(value) {
		const text = String(value || "");
		return text.length >= 8 ? text.slice(0, 8) : `${text}:00`.slice(0, 8);
	}
	time_input_value(value) {
		const text = String(value || "").replace(" ", "T");
		return text.includes("T") ? text.slice(11, 16) : text.slice(0, 5);
	}
	compose_output_interval(fromTime, toTime, shiftStart, shiftEnd, fallbackDate) {
		const fromClock = this.time_input_value(fromTime);
		const toClock = this.time_input_value(toTime);
		if (!/^\d{2}:\d{2}$/.test(fromClock) || !/^\d{2}:\d{2}$/.test(toClock)) return {from_time: "", to_time: ""};
		const start = String(shiftStart || "").replace(" ", "T");
		const end = String(shiftEnd || "").replace(" ", "T");
		const startDate = start.slice(0, 10) || fallbackDate;
		const endDate = end.slice(0, 10) || startDate;
		const startClock = start.includes("T") ? start.slice(11, 16) : "00:00";
		if (!/^\d{4}-\d{2}-\d{2}$/.test(startDate) || !/^\d{4}-\d{2}-\d{2}$/.test(endDate)) return {from_time: "", to_time: ""};
		let fromDate = startDate;
		if (endDate > startDate && fromClock < startClock) fromDate = endDate;
		let toDate = fromDate;
		if (toClock <= fromClock) {
			const next = new Date(`${fromDate}T00:00:00`);
			next.setDate(next.getDate() + 1);
			toDate = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}-${String(next.getDate()).padStart(2, "0")}`;
		}
		return {from_time: `${fromDate} ${fromClock}:00`, to_time: `${toDate} ${toClock}:00`};
	}

	async search_creation_jobs() {
		if (!this.creation || this.creation_pending) return;
		const creation = this.creation;
		const requestId = this.creation_search_sequence = (this.creation_search_sequence || 0) + 1;
		const search = this.$root.find(".pcw-create-search").val() || "";
		creation.search = search;
		this.creation_searching = true;
		this.render();
		try {
			const result = await this.call("get_process_card_creation_context", {
				company: creation.company, site: creation.site, workstation: creation.workstation.name,
				shift_date: creation.shift_date, shift_type: creation.shift_type || null, search,
			});
			if (this.creation !== creation || requestId !== this.creation_search_sequence) return;
			creation.job_cards = result.job_cards || [];
		} catch (error) {
			if (this.creation !== creation || requestId !== this.creation_search_sequence) return;
			frappe.msgprint(error?.message || __("Could not search eligible Job Cards."));
		} finally {
			if (this.creation === creation && requestId === this.creation_search_sequence) {
				this.creation_searching = false;
				this.render();
			}
		}
	}

	async submit_creation() {
		if (!this.creation || this.creation_pending) return;
		if (!this.creation.selected_job_cards?.length) return frappe.msgprint(__("Select at least one Job Card to allocate to this Process Card."));
		const value = selector => this.$root.find(selector).val();
		const shiftStart = value(".pcw-create-shift-start");
		const shiftEnd = value(".pcw-create-shift-end");
		if (!shiftStart || !shiftEnd || !this.creation.shift_type) return frappe.msgprint(__("Select a Shift Type and enter the shift start and end."));
		this.creation_pending = true;
		this.render();
		try {
			const result = await this.call_post("create_process_card", {
				company: this.creation.company, site: this.creation.site, workstation: this.creation.workstation.name,
				shift_date: this.creation.shift_date, shift_type: this.creation.shift_type,
				shift_start: shiftStart.replace("T", " "), shift_end: shiftEnd.replace("T", " "),
				job_cards: JSON.stringify(this.creation.selected_job_cards), remarks: this.creation.remarks || "",
			});
			sessionStorage.removeItem("qcmc_process_card_create_context");
			frappe.show_alert({message: __("Process Card created with selected Job Cards"), indicator: "green"});
			this.creation_pending = false;
			this.creation = null;
			frappe.set_route("process-card-workbench", result.name);
		} catch (error) {
			this.creation_pending = false;
			frappe.msgprint(error?.message || __("Process Card could not be created."));
			this.render();
		}
	}

	return_to_floor() {
		frappe.set_route("production-floor-workbench");
	}

	async handle_action(action, id) {
		if (action === "cancel-create-process-card") { this.creation = null; sessionStorage.removeItem("qcmc_process_card_create_context"); return frappe.set_route("production-floor-workbench"); }
		if (action === "search-create-jobs") return this.search_creation_jobs();
		if (action === "submit-create-process-card") return this.submit_creation();
		if (action === "toggle-create-job") {
			if (!this.creation) return;
			const selected = new Set(this.creation.selected_job_cards || []);
			selected.has(id) ? selected.delete(id) : selected.add(id);
			this.creation.selected_job_cards = [...selected];
			return this.render();
		}
		if (action === "create-shift-date") {
			this.creation.shift_date = this.$root.find(".pcw-create-shift-date").val();
			this.creation.shift_start = ""; this.creation.shift_end = ""; this.apply_shift_type_times(false);
			return this.render();
		}
		if (action === "create-shift-time") {
			this.creation[id] = this.$root.find(`.pcw-create-${id.replaceAll("_", "-")}`).val();
			return;
		}
		if (action === "create-remarks") { this.creation.remarks = this.$root.find(".pcw-create-remarks").val(); return; }
		if (action === "refresh") return this.load_from_route();
		if (action === "encoding-mode") { this.encoding_mode = id === "batch" ? "batch" : "mobile"; if (this.process_card) this.save_encoding_mode(this.process_card, this.encoding_mode); if (this.encoding_mode === "batch") this.batch = this.batch || this.load_batch_defaults(); return this.render(); }
		if (action === "load-batch") return this.load_batch_rows();
		if (action === "save-batch") return this.save_batch_rows();
		if (action === "correct-batch-output") return this.correct_batch_output(Number(id));
		if (action === "batch-back") { this.encoding_mode = "mobile"; if (this.process_card) this.save_encoding_mode(this.process_card, "mobile"); this.batch = null; if (this.process_card) return this.render(); return frappe.set_route("production-floor-workbench"); }
		if (action === "open-process-card-form") return frappe.set_route("Form", "Process Card", this.process_card);
		if (action === "open-job-card") return frappe.set_route("Form", "Job Card", id);
		if (action === "save-output") return this.save_output_entry(false);
		if (action === "save-output-next") return this.save_output_entry(true);
		if (action === "correct-output") return this.correct_output_entry(id);
		if (action === "remove-job-card") {
			const confirmed = await new Promise(resolve => frappe.confirm(__("Remove this Job Card from the Process Card?"), () => resolve(true), () => resolve(false)));
			if (!confirmed) return;
			await this.mutate("remove_job_card", {process_card: this.process_card, job_card: id});
			return;
		}
		if (action === "add-job-cards") return this.open_job_card_picker();
		if (action === "transition") await this.mutate("transition_status", {process_card: this.process_card, status: id});
	}

	encoding_mode_key(name) { return `qcmc_process_card_encoding_mode_${name}`; }
	load_encoding_mode(name) {
		try { return sessionStorage.getItem(this.encoding_mode_key(name)) === "batch" ? "batch" : "mobile"; }
		catch (_storageError) { return "mobile"; }
	}
	save_encoding_mode(name, mode) {
		try { sessionStorage.setItem(this.encoding_mode_key(name), mode); } catch (_storageError) {}
	}

	async save_output_entry(nextOperation = false) {
		if (this.output_pending || !this.context?.can_record_output) return;
		const jobCard = this.$root.find(".pcw-output-job").val();
		const fromTime = this.$root.find(".pcw-output-from").val();
		const toTime = this.$root.find(".pcw-output-to").val();
		if (!jobCard || !fromTime || !toTime) return frappe.msgprint(__("Select a Job Card and reporting period."));
		const good = this.$root.find(".pcw-output-good").val();
		const rejected = this.$root.find(".pcw-output-rejected").val();
		const remarks = this.$root.find(".pcw-output-remarks").val();
		const card = this.context.process_card || {};
		const interval = this.compose_output_interval(fromTime, toTime, card.shift_start, card.shift_end, card.shift_date);
		if (!interval.from_time || !interval.to_time) return frappe.msgprint(__("Enter valid From and To times."));
		this.output_pending = true; this.render();
		try {
			const eligible = (this.context.job_cards || []).filter(job => !job.docstatus && job.status !== "Cancelled" && job.can_record_output);
			const currentIndex = eligible.findIndex(job => job.name === jobCard);
			const nextJob = currentIndex >= 0 ? eligible[(currentIndex + 1) % eligible.length] : null;
			await this.call_output("save_process_card_output", {
				process_card: this.process_card, job_card: jobCard, from_time: interval.from_time, to_time: interval.to_time,
				good_qty: good, rejected_qty: rejected || 0, remarks: remarks || "",
			});
			try {
				localStorage.removeItem(this.mobile_draft_key());
				if (nextOperation && nextJob && nextJob.name !== jobCard) localStorage.setItem(this.mobile_draft_key(), JSON.stringify({job: nextJob.name, from: fromTime, to: toTime, good: "", rejected: "0", remarks: ""}));
			} catch (_storageError) {}
			frappe.show_alert({message: __("Production output saved"), indicator: "green"});
		} catch (error) { frappe.msgprint(error?.message || __("Production output could not be saved.")); }
		finally { this.output_pending = false; await this.load_from_route(); }
	}

	mobile_draft_key() { return `qcmc_mobile_output_${this.process_card}`; }
	remember_mobile_entry() {
		if (!this.process_card || !this.$root.find(".pcw-output-from").length) return;
		const draft = Object.fromEntries(["job", "from", "to", "good", "rejected", "remarks"].map((key, index) => [key, this.$root.find([".pcw-output-job", ".pcw-output-from", ".pcw-output-to", ".pcw-output-good", ".pcw-output-rejected", ".pcw-output-remarks"][index]).val()]));
		try {
			localStorage.setItem(this.mobile_draft_key(), JSON.stringify(draft));
			localStorage.setItem("qcmc_mobile_output_period", JSON.stringify({from: draft.from, to: draft.to}));
		} catch (_storageError) {}
	}
	job_quantity_balance_html(jobName) {
		const job = (this.context?.job_cards || []).find(row => row.name === jobName);
		const totals = (this.context?.production_output?.per_job || []).find(row => row.job_card === jobName);
		if (!job || !totals) return "";
		return `<div class="pcw-quantity-balance" aria-live="polite"><span>${__("Target")}: <b>${pcwEscape(totals.target_qty ?? job.for_quantity ?? 0)}</b></span><span>${__("Official Completed")}: <b>${pcwEscape(totals.official_completed_qty ?? job.total_completed_qty ?? 0)}</b></span><span>${__("All Process Card Output")}: <b>${pcwEscape(totals.all_process_card_output_qty ?? 0)}</b> (${__("Good")}: ${pcwEscape(totals.all_process_card_good_qty ?? 0)} · ${__("Rejected")}: ${pcwEscape(totals.all_process_card_rejected_qty ?? 0)})</span><span>${__("This Process Card")}: <b>${pcwEscape(totals.current_process_card_output_qty ?? totals.recorded_qty ?? 0)}</b></span><span>${__("Available")}: <b>${pcwEscape(totals.remaining_qty ?? 0)}</b></span></div>`;
	}
	render_mobile_quantity_balance() {
		const jobName = this.$root.find(".pcw-output-job").val();
		this.$root.find(".pcw-mobile-quantity-balance").html(this.job_quantity_balance_html(jobName));
	}
	preview_mobile_metrics() {
		clearTimeout(this.mobile_metric_timer);
		this.mobile_metric_timer = setTimeout(async () => {
			const job = this.$root.find(".pcw-output-job").val();
			const source = this.context?.production_output?.per_job?.find(row => row.job_card === job);
			const from = this.$root.find(".pcw-output-from").val();
			const to = this.$root.find(".pcw-output-to").val();
			if (!source?.soph || source.soph <= 0 || !from || !to) { this.$root.find(".pcw-mobile-metrics").text(source?.soph < 0 ? __("SOPH must be greater than zero.") : source?.soph ? __("Select a valid reporting period.") : __("SOPH unavailable for this operation.")); return; }
			const sequence = this.mobile_metric_sequence = (this.mobile_metric_sequence || 0) + 1;
			try {
				const bounds = this.context.process_card || {};
				const interval = this.compose_output_interval(from, to, bounds.shift_start, bounds.shift_end, bounds.shift_date);
				if (!interval.from_time || !interval.to_time) { this.$root.find(".pcw-mobile-metrics").text(__("Enter valid From and To times.")); return; }
				const period = Math.max(0, (new Date(interval.to_time.replace(" ", "T")) - new Date(interval.from_time.replace(" ", "T"))) / 60000);
				const result = await this.call_post("calculate_output_metrics", {good_qty: this.$root.find(".pcw-output-good").val() || 0, rejected_qty: this.$root.find(".pcw-output-rejected").val() || 0, soph: source.soph, period_minutes: period});
				if (sequence !== this.mobile_metric_sequence) return;
				this.$root.find(".pcw-mobile-metrics").text(`${__("SOPH")}: ${result.soph} ${source.uom ? `${source.uom}/h` : __("per hour")} · ${__("Run hours")}: ${result.run_hours ?? "—"} · ${__("Computed Remaining Minutes")}: ${result.remaining_minutes ?? "—"}${result.negative_remaining ? ` · ${__("Review: exceeds period")}` : ""}`);
			} catch (_error) { this.$root.find(".pcw-mobile-metrics").text(__("Enter valid quantities to calculate.")); }
		}, 250);
	}
	load_batch_defaults() {
		let saved = {};
		try { saved = JSON.parse(sessionStorage.getItem("qcmc_process_card_batch_context") || "{}"); } catch (_error) {}
		return {site: this.context?.process_card?.site || saved.site || "", building: this.context?.process_card?.building || saved.building || "", shift_date: this.context?.process_card?.shift_date || saved.shift_date || frappe.datetime.get_today(), shift_type: this.context?.process_card?.shift_type || saved.shift_type || "", from_time: saved.from_time || "", to_time: saved.to_time || "", rows: [], loaded: false};
	}
	remember_batch_period() {
		if (!this.batch) return;
		this.batch.shift_date = this.$root.find(".pcw-batch-date").val() || this.batch.shift_date;
		this.batch.building = this.$root.find(".pcw-batch-building").val() || "";
		this.batch.from_time = this.$root.find(".pcw-batch-from").val() || "";
		this.batch.to_time = this.$root.find(".pcw-batch-to").val() || "";
		this.batch.site = this.batch_site_control?.get_value() || this.batch.site;
		this.batch.shift_type = this.batch_shift_type_control?.get_value() || this.batch.shift_type;
		try { sessionStorage.setItem("qcmc_process_card_batch_context", JSON.stringify({site: this.batch.site, building: this.batch.building, shift_date: this.batch.shift_date, shift_type: this.batch.shift_type, from_time: this.batch.from_time, to_time: this.batch.to_time})); } catch (_storageError) {}
	}
	async load_batch_rows() {
		const batch = this.batch || (this.batch = this.load_batch_defaults());
		batch.site = this.batch_site_control?.get_value() || batch.site;
		batch.shift_date = this.$root.find(".pcw-batch-date").val() || batch.shift_date;
		batch.building = this.$root.find(".pcw-batch-building").val() || batch.building;
		batch.from_time = this.$root.find(".pcw-batch-from").val();
		batch.to_time = this.$root.find(".pcw-batch-to").val();
		batch.shift_type = this.batch_shift_type_control?.get_value() || batch.shift_type;
		if (!batch.site || !batch.shift_date || !batch.shift_type || !batch.from_time || !batch.to_time) return frappe.msgprint(__("Select site, production date, shift, and default from/to times."));
		this.batch_loading = true; this.render();
		try {
			const result = await this.call("get_batch_output_context", {site: batch.site, shift_date: batch.shift_date, shift_type: batch.shift_type || null, building: batch.building || null});
			batch.rows = result.rows.map(row => {
				const interval = this.compose_output_interval(batch.from_time, batch.to_time, row.from_time, row.to_time, batch.shift_date);
				const item = {...row, process_shift_start: row.from_time, process_shift_end: row.to_time, from_time: interval.from_time, to_time: interval.to_time, good_qty: "", rejected_qty: "0", remarks: "", run_hours: null, remaining_minutes: null, entry_status: "Pending", dirty: false};
				item.existing_entry = this.matching_batch_entry(item);
				if (item.existing_entry) {
					item.good_qty = String(item.existing_entry.good_qty);
					item.rejected_qty = String(item.existing_entry.rejected_qty);
					item.remarks = item.existing_entry.remarks || "";
					item.entry_status = __("Existing entry · correction required");
				}
				return item;
			});
			batch.loaded = true; batch.loading = false;
		} catch (error) { batch.loading = false; frappe.msgprint(error?.message || __("Could not load production rows.")); }
		this.batch_loading = false; this.render();
	}
	async update_batch_cell(input) {
		const row = this.batch?.rows?.[Number(input.dataset.row)];
		if (!row) return;
		const was_existing = row.existing_entry;
		if (input.dataset.field === "from_time" || input.dataset.field === "to_time") {
			const fromTime = input.dataset.field === "from_time" ? input.value : this.time_input_value(row.from_time);
			const toTime = input.dataset.field === "to_time" ? input.value : this.time_input_value(row.to_time);
			const interval = this.compose_output_interval(fromTime, toTime, row.process_shift_start, row.process_shift_end, this.batch.shift_date);
			row.from_time = interval.from_time;
			row.to_time = interval.to_time;
		} else row[input.dataset.field] = input.value;
		row.dirty = true;
		row.existing_entry = this.matching_batch_entry(row);
		if (was_existing && !row.existing_entry && ["from_time", "to_time"].includes(input.dataset.field)) {
			row.good_qty = ""; row.rejected_qty = "0"; row.remarks = "";
		}
		row.entry_status = row.existing_entry ? __("Existing entry · correction required") : "Modified";
		if (["good_qty", "rejected_qty", "from_time", "to_time"].includes(input.dataset.field)) {
			clearTimeout(this.batch_metric_timers?.[input.dataset.row]);
			this.batch_metric_timers = this.batch_metric_timers || {};
			this.batch_metric_timers[input.dataset.row] = setTimeout(async () => {
				if (!row.soph || !row.from_time || !row.to_time) { row.run_hours = null; row.remaining_minutes = null; this.render_batch_grid(); return; }
				const period = Math.max(0, (new Date(row.to_time.replace(" ", "T")) - new Date(row.from_time.replace(" ", "T"))) / 60000);
				const sequence = row.metric_sequence = (row.metric_sequence || 0) + 1;
				try { const metrics = await this.call_post("calculate_output_metrics", {good_qty: row.good_qty || 0, rejected_qty: row.rejected_qty || 0, soph: row.soph, period_minutes: period}); if (sequence !== row.metric_sequence) return; row.run_hours = metrics.run_hours; row.remaining_minutes = metrics.remaining_minutes; row.negative_remaining = metrics.negative_remaining; }
				catch (_error) { row.run_hours = null; row.remaining_minutes = null; }
				this.render_batch_grid();
			}, 250);
		}
		this.render_batch_grid();
	}
	matching_batch_entry(row) {
		const normalize = value => String(value || "").replace("T", " ").slice(0, 16);
		return (row.existing_entries || []).find(entry => normalize(entry.from_time) === normalize(row.from_time) && normalize(entry.to_time) === normalize(row.to_time)) || null;
	}
	async correct_batch_output(index) {
		const row = this.batch?.rows?.[index];
		const entry = row?.existing_entry;
		if (!row || !entry) return;
		if (!row.can_correct_output) return frappe.msgprint(__("You do not have permission to correct output for this Job Card."));
		const dialog = new frappe.ui.Dialog({
			title: __("Correct Production Output"),
			fields: [
				{fieldname: "good_qty", fieldtype: "Float", label: __("Good Quantity"), reqd: 1, default: row.good_qty || entry.good_qty},
				{fieldname: "rejected_qty", fieldtype: "Float", label: __("Rejected Quantity"), reqd: 1, default: row.rejected_qty || entry.rejected_qty},
				{fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks"), default: row.remarks || entry.remarks || ""},
				{fieldname: "reason", fieldtype: "Small Text", label: __("Correction Reason"), reqd: 1},
			],
			primary_action_label: __("Save Correction"),
			primary_action: async values => {
				try {
					await this.call_output("correct_process_card_output", {process_card: row.process_card, job_card: row.job_card, time_log_id: entry.time_log_id, expected_revision: entry.revision, good_qty: values.good_qty, rejected_qty: values.rejected_qty, remarks: values.remarks || "", reason: values.reason});
					dialog.hide(); frappe.show_alert({message: __("Correction saved with audit history"), indicator: "green"}); await this.refresh_batch_rows();
				} catch (error) { frappe.msgprint(error?.message || __("Correction could not be saved.")); }
			},
		});
		dialog.show();
	}
	async refresh_batch_rows(resultsByKey = new Map(), preserveRows = this.batch?.rows || []) {
		const batch = this.batch;
		if (!batch?.loaded) return;
		try {
			const result = await this.call("get_batch_output_context", {site: batch.site, shift_date: batch.shift_date, shift_type: batch.shift_type || null, building: batch.building || null});
			const prior = new Map(preserveRows.map(row => [`${row.process_card}\u0000${row.job_card}`, row]));
			batch.rows = (result.rows || []).map(source => {
				const key = `${source.process_card}\u0000${source.job_card}`;
				const previous = prior.get(key);
				const interval = this.compose_output_interval(
					previous ? this.time_input_value(previous.from_time) : this.time_input_value(batch.from_time),
					previous ? this.time_input_value(previous.to_time) : this.time_input_value(batch.to_time),
					source.from_time, source.to_time, batch.shift_date,
				);
				const row = {...source, process_shift_start: source.from_time, process_shift_end: source.to_time, from_time: interval.from_time, to_time: interval.to_time, good_qty: "", rejected_qty: "0", remarks: "", run_hours: null, remaining_minutes: null, entry_status: "Pending", dirty: false};
				row.existing_entry = this.matching_batch_entry(row);
				if (row.existing_entry) {
					row.good_qty = String(row.existing_entry.good_qty);
					row.rejected_qty = String(row.existing_entry.rejected_qty);
					row.remarks = row.existing_entry.remarks || "";
					row.entry_status = __("Existing entry · correction required");
				}
				if (previous) {
					const status = resultsByKey.get(key);
					if (status?.success) {
						row.entry_status = status.duplicate_request ? __("Already Exists") : __("Saved");
					} else if (status) {
						row.good_qty = previous.good_qty;
						row.rejected_qty = previous.rejected_qty;
						row.remarks = previous.remarks;
						row.from_time = previous.from_time;
						row.to_time = previous.to_time;
						row.dirty = true;
						row.entry_status = status.message || __("Failed");
					} else if (previous.dirty && !row.existing_entry) {
						row.good_qty = previous.good_qty;
						row.rejected_qty = previous.rejected_qty;
						row.remarks = previous.remarks;
						row.from_time = previous.from_time;
						row.to_time = previous.to_time;
						row.dirty = true;
						row.entry_status = previous.entry_status;
					}
				}
				return row;
			});
		} catch (error) {
			frappe.msgprint(error?.message || __("Could not refresh production rows."));
		}
	}
	render_batch_grid() {
		if (!this.batch?.loaded) return;
		this.$root.find(".pcw-batch-machine-minutes").text(this.unique_machine_minutes());
		this.batch.rows.forEach((row, index) => {
			this.$root.find(`[data-run-hours="${index}"]`).text(row.run_hours ?? "—");
			this.$root.find(`[data-remaining="${index}"]`).text(row.remaining_minutes ?? "—").toggleClass("text-danger", !!row.negative_remaining);
			this.$root.find(`[data-status="${index}"]`).text(row.entry_status);
		});
	}
	async save_batch_rows() {
		if (this.batch_pending || !this.batch?.loaded) return;
		const rows = this.batch.rows.filter(row => row.dirty && !row.existing_entry && row.good_qty !== "");
		if (!rows.length) return frappe.msgprint(__("There are no modified output rows to save."));
		this.batch_pending = true; this.render();
		try {
			const result = await this.call_output("save_process_card_output_batch", {rows: JSON.stringify(rows.map(row => ({process_card: row.process_card, job_card: row.job_card, from_time: row.from_time, to_time: row.to_time, good_qty: row.good_qty, rejected_qty: row.rejected_qty || 0, remarks: row.remarks || ""})))});
			const resultsByKey = new Map();
			(result.results || []).forEach((saved, index) => {
				const row = rows[index];
				if (!row) return;
				resultsByKey.set(`${row.process_card}\u0000${row.job_card}`, saved);
				row.dirty = !saved.success;
				row.entry_status = saved.success ? (saved.duplicate_request ? __("Already Exists") : __("Saved")) : (saved.message || __("Failed"));
			});
			await this.refresh_batch_rows(resultsByKey, this.batch.rows);
			frappe.show_alert({message: __("Batch processed: {0} saved", [result.success_count || 0]), indicator: result.success_count ? "green" : "orange"});
		} catch (error) { frappe.msgprint(error?.message || __("Batch could not be saved.")); }
		this.batch_pending = false; this.render();
	}
	batch_grid_html() {
		const machineMinutes = this.unique_machine_minutes();
		return `<div class="pcw-output-summary"><b>${__("Scheduled machine minutes (overlap deduplicated)")}: <span class="pcw-batch-machine-minutes">${machineMinutes}</span></b><span>${__("Per-operation Run Hours remain separate; shared intervals are counted once here.")}</span></div><div class="table-responsive"><table class="table table-bordered pcw-batch-table"><thead><tr>${[__("Process Card"), __("Job Card / Work Order"), __("Operation"), __("Product Code"), __("Description"), __("UOM"), __("Machine"), __("SOPH / hour"), __("From"), __("To"), __("Good Output"), __("Rejected"), __("Run Hours"), __("Computed Remaining Minutes"), __("Color Count"), __("Remarks"), __("Entry Status")].map(label => `<th>${label}</th>`).join("")}</tr></thead><tbody>${this.batch.rows.map((row, index) => `<tr><td>${pcwEscape(row.process_card)}</td><td>${pcwEscape(row.job_card)}<small>${pcwEscape(row.work_order)}</small></td><td>${pcwEscape(row.operation)}</td><td>${pcwEscape(row.product_code)}</td><td>${pcwEscape(row.product_description)}<small>${__("Target")}: ${pcwEscape(row.target_qty ?? 0)} · ${__("Official")}: ${pcwEscape(row.official_completed_qty ?? 0)} · ${__("All operational")}: ${pcwEscape(row.all_process_card_output_qty ?? 0)} · ${__("This card")}: ${pcwEscape(row.current_process_card_output_qty ?? 0)} · ${__("Available")}: ${pcwEscape(row.remaining_qty ?? 0)}</small></td><td>${pcwEscape(row.uom || "—")}</td><td>${pcwEscape(row.workstation)}</td><td>${row.soph > 0 ? pcwEscape(row.soph) : `<span class="text-warning">${__("Unavailable")}</span>`}</td><td><input class="form-control pcw-batch-cell" data-row="${index}" data-field="from_time" type="time" value="${pcwEscape(this.time_input_value(row.from_time))}" ${row.can_record_output ? "" : "disabled"}></td><td><input class="form-control pcw-batch-cell" data-row="${index}" data-field="to_time" type="time" value="${pcwEscape(this.time_input_value(row.to_time))}" ${row.can_record_output ? "" : "disabled"}></td><td><input class="form-control pcw-batch-cell" data-row="${index}" data-field="good_qty" type="number" min="0" step="any" value="${pcwEscape(row.good_qty)}" ${row.can_record_output ? "" : "disabled"}></td><td><input class="form-control pcw-batch-cell" data-row="${index}" data-field="rejected_qty" type="number" min="0" step="any" value="${pcwEscape(row.rejected_qty)}" ${row.can_record_output ? "" : "disabled"}></td><td data-run-hours="${index}">${pcwEscape(row.run_hours ?? "—")}</td><td data-remaining="${index}" class="${row.negative_remaining ? "text-danger" : ""}">${pcwEscape(row.remaining_minutes ?? "—")}</td><td>${pcwEscape(row.color_count ?? "—")}</td><td><input class="form-control pcw-batch-cell" data-row="${index}" data-field="remarks" value="${pcwEscape(row.remarks)}" ${row.can_record_output ? "" : "disabled"}></td><td><span data-status="${index}">${pcwEscape(row.entry_status)}</span>${row.existing_entry && row.can_correct_output ? ` <button class="btn btn-default btn-xs" data-action="correct-batch-output" data-id="${index}">${__("Correct")}</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
	}
	unique_machine_minutes() {
		const grouped = new Map();
		for (const row of this.batch?.rows || []) {
			const start = new Date(String(row.from_time).replace(" ", "T")).getTime(), end = new Date(String(row.to_time).replace(" ", "T")).getTime();
			if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) continue;
			const intervals = grouped.get(row.workstation) || [];
			intervals.push([start, end]); grouped.set(row.workstation, intervals);
		}
		let milliseconds = 0;
		for (const intervals of grouped.values()) {
			intervals.sort((left, right) => left[0] - right[0]);
			let current = null;
			for (const interval of intervals) {
				if (!current || interval[0] > current[1]) { if (current) milliseconds += current[1] - current[0]; current = [...interval]; }
				else current[1] = Math.max(current[1], interval[1]);
			}
			if (current) milliseconds += current[1] - current[0];
		}
		return Math.round(milliseconds / 60000);
	}

	correct_output_entry(entryId) {
		const entry = (this.context.production_output?.per_job || []).flatMap(row => row.entries || []).find(row => row.time_log_id === entryId);
		if (!entry || !this.context?.can_record_output) return;
		const job = (this.context.production_output.per_job || []).find(row => row.entries.some(item => item.time_log_id === entryId));
		const dialog = new frappe.ui.Dialog({
			title: __("Correct Production Entry"),
			fields: [
				{fieldname: "good_qty", fieldtype: "Float", label: __("Good Quantity"), reqd: 1, default: entry.good_qty},
				{fieldname: "rejected_qty", fieldtype: "Float", label: __("Rejected Quantity"), reqd: 1, default: entry.rejected_qty},
				{fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks"), default: entry.remarks || ""},
				{fieldname: "reason", fieldtype: "Small Text", label: __("Correction Reason"), reqd: 1},
			],
			primary_action_label: __("Save Correction"),
			primary_action: async values => {
				if (this.output_pending) return;
				this.output_pending = true; dialog.disable_primary_action();
				try {
					await this.call_output("correct_process_card_output", {
						process_card: this.process_card, job_card: job.job_card, time_log_id: entryId,
						expected_revision: entry.revision, good_qty: values.good_qty, rejected_qty: values.rejected_qty,
						remarks: values.remarks || "", reason: values.reason,
					});
					dialog.hide(); frappe.show_alert({message: __("Correction saved with audit history"), indicator: "green"});
				} catch (error) { frappe.msgprint(error?.message || __("Correction could not be saved.")); }
				finally { this.output_pending = false; await this.load_from_route(); }
			},
		});
		dialog.show();
	}

	async mutate(method, args) {
		try {
			this.context = await this.call_post(method, args);
			this.error = null;
			this.render();
			return true;
		} catch (error) {
			frappe.msgprint(error?.message || __("The Process Card could not be updated."));
			await this.load_from_route();
			return false;
		}
	}

	open_job_card_picker() {
		const dialog = new frappe.ui.Dialog({
			title: __("Add Existing Job Cards"),
			fields: [
				{fieldname: "search", fieldtype: "Data", label: __("Search Job Card, Work Order, Operation, or Item")},
				{fieldname: "results", fieldtype: "HTML"},
			],
		});
		const wrapper = dialog.fields_dict.results.$wrapper;
		let rows = [];
		const render_rows = () => {
			wrapper.find(".pcw-picker-results").html(rows.length ? rows.map(row => `<label class="pcw-picker-row"><input type="checkbox" value="${pcwEscape(row.name)}"><span><b>${pcwEscape(row.name)}</b> · ${pcwEscape(row.status)}<small>${pcwEscape(row.work_order)} · ${pcwEscape(row.production_item)} · ${pcwEscape(row.operation)} · ${pcwEscape(row.for_quantity)} / ${pcwEscape(row.total_completed_qty)}</small></span></label>`).join("") : `<p>${__("No eligible Job Cards found.")}</p>`);
		};
		wrapper.html(`<div class="pcw-picker-actions"><button class="btn btn-default btn-sm pcw-search">${__("Search")}</button><button class="btn btn-primary btn-sm pcw-add-selected">${__("Add selected")}</button></div><div class="pcw-picker-state" role="status"></div><div class="pcw-picker-results"></div>`);
		wrapper.on("click", ".pcw-search", async () => {
			wrapper.find(".pcw-picker-state").text(__("Searching…"));
			try {
				rows = await this.call("search_eligible_job_cards", {process_card: this.process_card, search: dialog.get_value("search") || ""});
				wrapper.find(".pcw-picker-state").text(""); render_rows();
			} catch (error) { wrapper.find(".pcw-picker-state").text(__("Could not search eligible Job Cards.")); }
		});
		wrapper.on("click", ".pcw-add-selected", async () => {
			const selected = wrapper.find(".pcw-picker-results input:checked").map((_, node) => node.value).get();
			if (!selected.length) return frappe.msgprint(__("Select at least one Job Card."));
			try {
				const saved = await this.mutate("add_job_cards", {process_card: this.process_card, job_cards: JSON.stringify(selected)});
				if (saved) dialog.hide();
				else wrapper.find(".pcw-picker-state").text(__("The selected Job Cards could not be added."));
			} catch (error) { wrapper.find(".pcw-picker-state").text(__("The selected Job Cards could not be added.")); }
		});
		dialog.show();
		wrapper.find(".pcw-search").trigger("click");
	}

	render() {
		const state = this.$root.find(".pcw-state");
		const content = this.$root.find(".pcw-content");
		if (this.loading) { state.html(`<div class="alert alert-info">${__("Loading Process Card…")}</div>`); content.empty(); return; }
		if (this.error) { state.html(`<div class="alert alert-danger">${pcwEscape(this.error)}</div>`); content.empty(); return; }
		if (this.creation) { state.empty(); this.render_creation(content); return; }
		if (frappe.get_route()[1] === "batch") { state.empty(); this.render_batch(content); return; }
		if (!this.process_card) { state.html(`<div class="alert alert-warning">${__("Choose a Process Card from the Production Floor Navigator or enter its identifier in the page route.")}</div>`); content.empty(); return; }
		if (!this.context) { state.empty(); content.empty(); return; }
		state.empty();
		if (this.encoding_mode === "batch") { this.render_batch(content); return; }
		const card = this.context.process_card;
		const jobs = this.context.job_cards || [];
		const outputJobs = jobs.filter(job => job.can_record_output);
		const canEdit = this.context.can_write && ["Draft", "In Progress"].includes(card.status);
		const location = [card.site || card.plant_floor, card.building].filter(Boolean).join(" / ") || "—";
		content.html(`
			<header class="pcw-header pcw-compact-header"><div><div class="pcw-eyebrow">${pcwEscape(location)} · ${pcwEscape(card.workstation_name || card.workstation || "—")}</div><h2>${pcwEscape(card.name)} <span class="pcw-status">${pcwEscape(card.status)}</span></h2><div class="pcw-shift-line">${pcwEscape(card.shift_date)} · ${pcwEscape(card.shift_type || "—")}</div></div></header>
			<div class="pcw-mode-switch" role="group" aria-label="${__("Production encoding mode")}"><button class="btn ${this.encoding_mode === "mobile" ? "btn-primary" : "btn-default"}" data-action="encoding-mode" data-id="mobile">${__("Mobile Encoding")}</button><button class="btn ${this.encoding_mode === "batch" ? "btn-primary" : "btn-default"}" data-action="encoding-mode" data-id="batch">${__("Batch Encoding")}</button></div>
			${outputJobs.length ? this.mobile_output_form(outputJobs) : `<p class="text-muted">${__("You do not have permission to enter output on the linked Job Cards, or this Process Card is locked.")}</p>`}
			${this.render_history_html()}
			<details class="pcw-details"><summary>${__("Details")}</summary><section class="pcw-section"><div class="pcw-details-grid"><div><small>${__("Company")}</small><b>${pcwEscape(card.company)}</b></div><div><small>${__("Workstation Type")}</small><b>${pcwEscape(card.workstation_type || "—")}</b></div><div><small>${__("Workstation Status")}</small><b>${pcwEscape(card.workstation_status || "—")}</b></div><div><small>${__("Shift Window")}</small><b>${pcwEscape(card.shift_start || "—")} – ${pcwEscape(card.shift_end || "—")}</b></div></div><button class="btn btn-default btn-sm" data-action="open-process-card-form">${__("Open Process Card Form")}</button></section>
				<section class="pcw-section"><div class="pcw-section-heading"><h3>${__("Allocated Job Cards")}</h3>${canEdit ? `<button class="btn btn-primary btn-sm" data-action="add-job-cards">${__("Add Existing Job Card")}</button>` : ""}</div>${jobs.length ? `<div class="table-responsive"><table class="table table-bordered table-hover pcw-job-table"><thead><tr><th>${__("Job Card")}</th><th>${__("Status")}</th><th>${__("Work Order")}</th><th>${__("Operation")}</th><th>${__("Production Item")}</th><th>${__("Qty To Manufacture")}</th><th>${__("Completed Qty")}</th><th>${__("Progress")}</th><th>${__("Actual Start / End")}</th><th></th></tr></thead><tbody>${jobs.map(job => `<tr><td><button class="btn btn-link btn-xs" data-action="open-job-card" data-id="${pcwEscape(job.name)}">${pcwEscape(job.name)}</button></td><td>${pcwEscape(job.status)}</td><td>${pcwEscape(job.work_order)}</td><td>${pcwEscape(job.operation || job.operation_id)}</td><td>${pcwEscape(job.production_item)}</td><td>${pcwEscape(job.for_quantity)}</td><td>${pcwEscape(job.total_completed_qty)}</td><td>${Number(job.for_quantity) > 0 ? `<progress class="pcw-progress" max="${pcwEscape(job.for_quantity)}" value="${pcwEscape(job.total_completed_qty)}"></progress>` : "—"}</td><td>${pcwEscape(job.actual_start_date || "—")} / ${pcwEscape(job.actual_end_date || "—")}</td><td>${canEdit ? `<button class="btn btn-default btn-xs" data-action="remove-job-card" data-id="${pcwEscape(job.name)}">${__("Remove")}</button>` : ""}</td></tr>`).join("")}</tbody></table></div>` : `<p class="text-muted">${__("No Job Cards are linked to this Process Card.")}</p>`}</section>
				${this.context.allowed_transitions?.length && this.context.can_write ? `<section class="pcw-section pcw-transitions">${this.context.allowed_transitions.map(status => `<button class="btn btn-default btn-sm" data-action="transition" data-id="${pcwEscape(status)}">${__("Set status")}: ${pcwEscape(status)}</button>`).join("")}</section>` : ""}
			</details>
		`);
	}

	render_history_html() {
		const perJob = this.context?.production_output?.per_job || [];
		const jobs = this.context?.job_cards || [];
		const entries = perJob.flatMap(summary => (summary.entries || []).map(entry => ({...entry, job_card: summary.job_card, operation: jobs.find(job => job.name === summary.job_card)?.operation || jobs.find(job => job.name === summary.job_card)?.operation_id || "—", production_item: summary.production_item || "—", uom: summary.uom || ""}))).sort((a, b) => String(b.from_time || "").localeCompare(String(a.from_time || "")));
		const filtered = entries.filter(entry => (!this.history_filter.job_card || entry.job_card === this.history_filter.job_card) && (!this.history_filter.date || String(entry.from_time || "").slice(0, 10) === this.history_filter.date));
		const rows = filtered.length ? filtered.map(entry => { const job = this.context.job_cards.find(row => row.name === entry.job_card); return `<article class="pcw-history-row"><div class="pcw-history-main"><b>${pcwEscape(entry.job_card)}</b><span>${pcwEscape(entry.operation)} · ${pcwEscape(entry.production_item)}</span><span>${pcwEscape(entry.from_time || "—")} – ${pcwEscape(entry.to_time || "—")}</span><span>${__("Good")}: ${pcwEscape(entry.good_qty)} · ${__("Rejected")}: ${pcwEscape(entry.rejected_qty)} ${pcwEscape(entry.uom)}</span><small>${pcwEscape(entry.entered_by || "—")} · ${pcwEscape(entry.entered_at || "—")}</small>${entry.remarks ? `<small>${pcwEscape(entry.remarks)}</small>` : ""}${entry.correction_history?.length ? `<details class="pcw-correction-history"><summary>${__("Correction history")} (${entry.correction_history.length})</summary>${entry.correction_history.map(change => `<small>${pcwEscape(change.timestamp)} · ${pcwEscape(change.user)} · ${pcwEscape(change.reason)} · ${pcwEscape(change.previous_good_qty)}/${pcwEscape(change.previous_rejected_qty)} → ${pcwEscape(change.revised_good_qty)}/${pcwEscape(change.revised_rejected_qty)}</small>`).join("")}</details>` : ""}</div>${job?.can_correct_output ? `<button class="btn btn-default btn-sm" data-action="correct-output" data-id="${pcwEscape(entry.time_log_id)}">${__("Correct")}</button>` : ""}</article>`; }).join("") : `<p class="text-muted">${__("No production entries match these filters.")}</p>`;
		return `<details class="pcw-history"><summary>${__("Production History")} (${entries.length})</summary><div class="pcw-history-filters"><label>${__("Job Card")}<select class="form-control pcw-history-job"><option value="">${__("All Job Cards")}</option>${[...new Set(entries.map(row => row.job_card))].map(name => `<option value="${pcwEscape(name)}" ${this.history_filter.job_card === name ? "selected" : ""}>${pcwEscape(name)}</option>`).join("")}</select></label><label>${__("Date")}<input class="form-control pcw-history-date" type="date" value="${pcwEscape(this.history_filter.date)}"></label></div><div class="pcw-history-rows">${rows}</div></details>`;
	}

	render_history() {
		const details = this.$root.find(".pcw-history");
		const open = details.prop("open");
		const replacement = this.render_history_html();
		details.replaceWith(replacement);
		if (open) this.$root.find(".pcw-history").prop("open", true);
	}

	mobile_output_form(jobs) {
		let draft = {};
		try { draft = JSON.parse(localStorage.getItem(this.mobile_draft_key()) || "{}"); } catch (_error) {}
		let period = {};
		try { period = JSON.parse(localStorage.getItem("qcmc_mobile_output_period") || "{}"); } catch (_error) {}
		const start = this.time_input_value(draft.from || period.from || "");
		const end = this.time_input_value(draft.to || period.to || "");
		return `<div class="pcw-output-entry-form"><h4>${__("Mobile Encoding")}</h4><label>${__("Operation / Job Card")}<select class="form-control pcw-output-job"><option value="">${__("Select a Job Card")}</option>${jobs.filter(job => !job.docstatus && job.status !== "Cancelled" && job.can_record_output).map(job => { const standard = this.context.production_output?.per_job?.find(row => row.job_card === job.name); return `<option value="${pcwEscape(job.name)}" ${draft.job === job.name ? "selected" : ""}>${pcwEscape(job.operation || job.operation_id)} · ${pcwEscape(standard?.product_description || standard?.production_item || job.production_item)} · ${pcwEscape(standard?.production_item || job.production_item)} ${standard?.uom ? `(${pcwEscape(standard.uom)})` : ""} · ${pcwEscape(job.name)} · ${pcwEscape(job.work_order)}</option>`; }).join("")}</select></label><div class="pcw-mobile-quantity-balance">${this.job_quantity_balance_html(draft.job)}</div><div class="pcw-output-form-grid"><label>${__("From Time")}<input class="form-control pcw-output-from" type="time" value="${pcwEscape(start)}"></label><label>${__("To Time")}<input class="form-control pcw-output-to" type="time" value="${pcwEscape(end)}"></label><label>${__("Good Quantity")}<input class="form-control pcw-output-good" inputmode="decimal" type="number" min="0" step="any" value="${pcwEscape(draft.good || "")}"></label><label>${__("Rejected Quantity")}<input class="form-control pcw-output-rejected" inputmode="decimal" type="number" min="0" step="any" value="${pcwEscape(draft.rejected || "0")}"></label></div><div class="pcw-mobile-metrics" aria-live="polite"></div><label>${__("Remarks")}<textarea class="form-control pcw-output-remarks" rows="2">${pcwEscape(draft.remarks || "")}</textarea></label><button class="btn btn-primary btn-lg pcw-touch-save" data-action="save-output" ${this.output_pending ? "disabled" : ""}>${this.output_pending ? __("Saving…") : __("Save Output")}</button><button class="btn btn-default btn-lg pcw-touch-save" data-action="save-output-next" ${this.output_pending ? "disabled" : ""}>${__("Save & Next Operation")}</button></div>`;
	}

	render_batch(content) {
		const batch = this.batch || (this.batch = this.load_batch_defaults());
		content.html(`<header class="pcw-header"><div><div class="pcw-eyebrow">${__("Production Workbench")}</div><h2>${__("Batch Encoding")}</h2></div></header><div class="pcw-mode-switch"><button class="btn btn-default" data-action="encoding-mode" data-id="mobile">${__("Mobile Encoding")}</button><button class="btn btn-primary">${__("Batch Encoding")}</button></div><section class="pcw-section"><h3>${__("Reporting Period")}</h3><div class="pcw-create-grid"><div class="pcw-batch-link-field"><div class="pcw-batch-site-control"></div></div><label>${__("Production Date")}<input class="form-control pcw-batch-date" type="date" value="${pcwEscape(batch.shift_date)}"></label><div class="pcw-batch-link-field"><div class="pcw-batch-shift-control"></div></div><label>${__("Building / Production Area")}<input class="form-control pcw-batch-building" value="${pcwEscape(batch.building)}" placeholder="${__("Optional building name or ID")}"></label><label>${__("Default From Time")}<input class="form-control pcw-batch-from" type="time" value="${pcwEscape(this.time_input_value(batch.from_time))}"></label><label>${__("Default To Time")}<input class="form-control pcw-batch-to" type="time" value="${pcwEscape(this.time_input_value(batch.to_time))}"></label></div><button class="btn btn-primary" data-action="load-batch" ${this.batch_loading ? "disabled" : ""}>${this.batch_loading ? __("Loading…") : __("Load Production Grid")}</button></section>${batch.loaded ? `<section class="pcw-section"><div class="pcw-section-heading"><div><h3>${__("Production Entries")}</h3><small>${__("Rows are saved independently; failures remain editable.")}</small></div><button class="btn btn-primary" data-action="save-batch" ${this.batch_pending ? "disabled" : ""}>${this.batch_pending ? __("Saving…") : __("Save Modified Rows")}</button></div><div class="pcw-batch-grid">${this.batch_grid_html()}</div></section>` : ""}`);
		const controls = this;
		this.batch_site_control = frappe.ui.form.make_control({parent: content.find(".pcw-batch-site-control"), df: {fieldname: "site", label: __("Production Site"), fieldtype: "Link", options: "Production Site", change: function () { if (controls.batch) { controls.batch.site = this.get_value(); controls.remember_batch_period(); } }}, render_input: true});
		this.batch_site_control.set_input(batch.site || "");
		this.batch_shift_type_control = frappe.ui.form.make_control({parent: content.find(".pcw-batch-shift-control"), df: {fieldname: "shift_type", label: __("Shift"), fieldtype: "Link", options: "Shift Type", change: function () { if (controls.batch) { controls.batch.shift_type = this.get_value(); controls.remember_batch_period(); } }}, render_input: true});
		this.batch_shift_type_control.set_input(batch.shift_type || "");
	}

	render_creation(content) {
		const creation = this.creation;
		const selected = new Set(creation.selected_job_cards || []);
		const jobCards = creation.job_cards || [];
		content.html(`
			<header class="pcw-header"><div><div class="pcw-eyebrow">${__("Production Floor Workbench")}</div><h2>${__("Create Process Card")}</h2></div><div class="pcw-header-actions"><button class="btn btn-default" data-action="cancel-create-process-card">${__("Back to Floor Navigator")}</button></div></header>
			<section class="pcw-summary"><div><small>${__("Company")}</small><b>${pcwEscape(creation.company)}</b></div><div><small>${__("Production Site")}</small><b>${pcwEscape(creation.site)}</b></div><div><small>${__("Machine / Workstation")}</small><b>${pcwEscape(creation.workstation.workstation_name || creation.workstation.name)}</b></div></section>
			<section class="pcw-section"><h3>${__("Shift")}</h3><div class="pcw-create-grid">
				<label>${__("Shift Date")}<input class="form-control pcw-create-shift-date" type="date" value="${pcwEscape(creation.shift_date)}" data-action="create-shift-date"></label>
				<label>${__("Shift Type")}<div class="pcw-create-shift-type"></div></label>
				<label>${__("Shift Start")}<input class="form-control pcw-create-shift-start" type="datetime-local" value="${pcwEscape(String(creation.shift_start || "").replace(" ", "T"))}" data-action="create-shift-time" data-id="shift_start"></label>
				<label>${__("Shift End")}<input class="form-control pcw-create-shift-end" type="datetime-local" value="${pcwEscape(String(creation.shift_end || "").replace(" ", "T"))}" data-action="create-shift-time" data-id="shift_end"></label>
				<label class="pcw-create-remarks-label">${__("Remarks")}<textarea class="form-control pcw-create-remarks" data-action="create-remarks">${pcwEscape(creation.remarks || "")}</textarea></label>
			</div></section>
			<section class="pcw-section"><div class="pcw-section-heading"><div><h3>${__("Allocate Existing Job Cards")}</h3><small>${__("Only eligible Job Cards for this workstation and company are listed.")}</small></div><b>${selected.size} ${__("selected")}</b></div>
				<div class="pcw-picker-actions"><input class="form-control pcw-create-search" type="search" placeholder="${__("Search Job Card, Work Order, Operation, or Item")}" value="${pcwEscape(creation.search || "")}"><button class="btn btn-default" data-action="search-create-jobs">${this.creation_searching_label()}</button></div>
				<div class="pcw-picker-results">${jobCards.length ? jobCards.map(row => `<label class="pcw-picker-row"><input type="checkbox" data-action="toggle-create-job" data-id="${pcwEscape(row.name)}" ${selected.has(row.name) ? "checked" : ""}><span><b>${pcwEscape(row.name)}</b> · ${pcwEscape(row.status)}<small>${pcwEscape(row.work_order)} · ${pcwEscape(row.production_item)} · ${pcwEscape(row.operation)} · ${pcwEscape(row.for_quantity)} target · ${pcwEscape(row.total_completed_qty)} official completed</small></span></label>`).join("") : `<p class="text-muted">${__("No eligible Job Cards found for this machine.")}</p>`}</div>
				<p class="text-muted">${__("Select one or more Job Cards. Allocation is saved with the Process Card and can be reviewed in this Workbench.")}</p>
				<button class="btn btn-primary" data-action="submit-create-process-card" ${this.creation_pending ? "disabled" : ""}>${this.creation_pending ? __("Creating…") : __("Create Process Card and Allocate Job Cards")}</button>
			</section>`);
		const shiftParent = content.find(".pcw-create-shift-type");
		const workbench = this;
		this.creation_shift_type_control = frappe.ui.form.make_control({
			parent: shiftParent,
			df: {fieldname: "shift_type", label: __("Shift Type"), fieldtype: "Link", options: "Shift Type", change: function () {
				// A validation from a detached control must not change the new view.
				if (workbench.creation !== creation || workbench.creation_shift_type_control !== this) return;
				workbench.change_creation_shift_type(this.get_value());
			}},
			render_input: true,
		});
		// The context API already validated this value. Hydrate without running
		// set_value's asynchronous validation/change chain during rendering.
		this.creation_shift_type_control.set_input(creation.shift_type || "");
	}

	creation_searching_label() {
		return this.creation_searching ? __("Searching…") : __("Search");
	}
}

ProcessCardWorkbench.css = `<style>
.pcw{padding:18px;max-width:1500px;margin:auto;color:#243746}.pcw-header{display:flex;justify-content:space-between;align-items:center;padding:20px;background:#fff;border:1px solid #dce4e8;border-radius:8px}.pcw-header h2{margin:3px 0 8px}.pcw-header-actions{display:flex;gap:8px;flex-wrap:wrap}.pcw-eyebrow,.pcw-summary small{display:block;color:#71808a;font-size:11px;text-transform:uppercase;letter-spacing:.06em}.pcw-status{display:inline-block;padding:4px 10px;background:#e9f4f1;color:#0a6658;border-radius:12px;font-size:12px}.pcw-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;margin:14px 0;background:#dce4e8;border:1px solid #dce4e8;border-radius:8px;overflow:hidden}.pcw-summary>div{background:#fff;padding:13px 15px}.pcw-summary b{display:block;margin-top:5px;overflow-wrap:anywhere}.pcw-section{background:#fff;border:1px solid #dce4e8;border-radius:8px;margin:14px 0;padding:16px}.pcw-section h3{font-size:16px;margin:0}.pcw-section-heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.pcw-job-table{font-size:12px;margin:0}.pcw-job-table th{white-space:nowrap}.pcw-job-table td{vertical-align:middle}.pcw-progress{width:100%;min-width:75px;height:12px;accent-color:#0b8a77}.pcw-transitions{display:flex;gap:8px;flex-wrap:wrap}.pcw-picker-actions{display:flex;gap:8px;margin-bottom:10px}.pcw-picker-row{display:flex!important;gap:9px;padding:9px;border-bottom:1px solid #e5eaed;align-items:flex-start}.pcw-picker-row small{display:block;color:#687983;font-weight:400}.pcw-picker-results{max-height:55vh;overflow:auto}.pcw-picker-state{padding:4px;color:#71808a}.pcw-output-entry-form h4{font-size:14px}.pcw-output-entry-form{max-width:650px;padding:14px;border:1px solid #dce4e8;border-radius:7px;margin-top:16px}.pcw-output-entry-form label{display:block;margin:10px 0;font-size:12px}.pcw-output-form-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.pcw-create-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.pcw-create-grid>label{display:block;font-size:12px}.pcw-create-remarks-label{grid-column:1/-1}.pcw-create-search{max-width:420px}.pcw-mobile-metrics{padding:10px;background:#f2f7f5;border-radius:6px;margin:10px 0;font-weight:600}.pcw-mode-switch{display:flex;gap:8px;margin:12px 0}.pcw-batch-table{min-width:1700px;font-size:12px}.pcw-batch-table th{position:sticky;top:0;background:#f4f7f8;z-index:1}.pcw-batch-table input{min-width:120px}.pcw-touch-save{min-height:54px;min-width:180px}.pcw-output-entry-form input,.pcw-output-entry-form select,.pcw-output-entry-form textarea{min-height:46px;font-size:16px}@media(max-width:800px){.pcw-job-table{min-width:900px}.pcw-create-grid{grid-template-columns:1fr}.pcw-create-remarks-label{grid-column:auto}.pcw{padding:10px}.pcw-header{padding:14px}.pcw-output-form-grid{grid-template-columns:1fr}.pcw-section{padding:12px}.pcw-section-heading{align-items:flex-start;gap:8px;flex-direction:column}.pcw-output-entry-form{max-width:none}.pcw-touch-save{width:100%}}
.pcw-batch-link-field .frappe-control{margin-bottom:0}.pcw-output-summary{display:flex;gap:12px;flex-wrap:wrap;padding:10px;background:#f5f8f9;border-radius:6px;margin:10px 0;color:#536572;font-size:12px}.pcw-compact-header{padding:12px 16px}.pcw-shift-line{font-size:13px;color:#586a74}.pcw-details{margin:12px 0}.pcw-details>summary,.pcw-history>summary{cursor:pointer;padding:12px 14px;background:#f5f8f9;border:1px solid #dce4e8;border-radius:7px;font-weight:600}.pcw-details[open]>summary,.pcw-history[open]>summary{border-radius:7px 7px 0 0}.pcw-details-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-bottom:12px}.pcw-details-grid small,.pcw-details-grid b{display:block}.pcw-history{margin:14px 0}.pcw-history-filters{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:12px;border:1px solid #dce4e8;border-top:0}.pcw-history-filters label{font-size:12px}.pcw-history-rows{border:1px solid #dce4e8;border-top:0}.pcw-history-row{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:12px;border-top:1px solid #e7ecee}.pcw-history-row:first-child{border-top:0}.pcw-history-main{display:grid;gap:4px;min-width:0;overflow-wrap:anywhere}.pcw-history-main small{color:#71808a}.pcw-correction-history{margin-top:4px}.pcw-output-entry-form{max-width:none;margin-top:10px}.pcw-touch-save{min-height:54px}.pcw-mode-switch .btn{min-height:46px;flex:1}@media(max-width:800px){.pcw-details-grid,.pcw-history-filters{grid-template-columns:1fr}.pcw-history-row{gap:8px}.pcw-history-row>.btn{min-height:44px;flex:0 0 auto}.pcw-mode-switch{position:sticky;top:0;z-index:5;background:#fff;padding:5px 0}.pcw-output-entry-form{padding:12px}.pcw-touch-save{width:100%}}
</style>`;
