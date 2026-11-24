frappe.pages["production-floor-workbench"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Production Floor Workbench"), single_column: true });
	wrapper.floor_workbench = new ProductionFloorWorkbench(page);
};

const FLOOR_API = "qcmc_logic.api.production_floor_workbench.";
const floorEscape = value => frappe.utils.escape_html(String(value ?? ""));
const floorId = () => (window.crypto?.randomUUID?.() || `floor-${Date.now()}-${Math.random().toString(36).slice(2)}`);
const floorClone = value => JSON.parse(JSON.stringify(value));

class ProductionFloorWorkbench {
	constructor(page) {
		this.page = page;
		this.sites = [];
		this.layout = null;
		this.version = 0;
		this.building = null;
		this.expandedBuildings = new Set();
		this.selected = null;
		this.mode = "view";
		this.zoom = 1;
		this.pan = { x: 0, y: 0 };
		this.grid = 10;
		this.dirty = false;
		this.context = { workstations: [], process_cards: [] };
		this.machineContext = null;
		this.machineContextState = "idle";
		this.machineRequestId = 0;
		this.shift_date = frappe.datetime.get_today();
		this.root = $(page.body).empty().get(0);
		this.root.innerHTML = `<style>${ProductionFloorWorkbench.css}</style>
			<div class="pfw">
				<header class="pfw-toolbar">
					<button data-action="toggle-nav" class="btn btn-default btn-sm pfw-toggle">☰ ${__("Plants")}</button>
					<button data-action="toggle-context" class="btn btn-default btn-sm pfw-toggle">▤ ${__("Details")}</button>
					<button data-action="back" class="btn btn-default btn-sm">← ${__("Site")}</button>
					<button data-action="open-batch" class="btn btn-primary btn-sm pfw-batch">${__("Batch Encoding")}</button>
					<strong class="pfw-title">${__("Select a site")}</strong>
					<button data-action="view" class="btn btn-default btn-sm">${__("View")}</button>
					<button data-action="edit" class="btn btn-default btn-sm">${__("Edit")}</button>
					<button data-action="add-building" class="btn btn-default btn-sm pfw-edit">${__("Add building")}</button>
					<button data-action="add-machine" class="btn btn-default btn-sm pfw-edit">${__("Add machine")}</button>
					<button data-action="add-section" class="btn btn-default btn-sm pfw-edit">${__("Section")}</button>
					<button data-action="add-walkway" class="btn btn-default btn-sm pfw-edit">${__("Walkway")}</button>
					<button data-action="add-static" class="btn btn-default btn-sm pfw-edit">${__("Static")}</button>
					<button data-action="zoom-out" class="btn btn-default btn-sm">−</button>
					<span class="pfw-zoom">100%</span>
					<button data-action="zoom-in" class="btn btn-default btn-sm">+</button>
					<button data-action="reset-view" class="btn btn-default btn-sm">${__("Fit")}</button>
					<button data-action="save" class="btn btn-primary btn-sm pfw-edit">${__("Save")}</button>
				</header>
				<div class="pfw-body">
					<nav class="pfw-nav"><h4>${__("Production floor")}</h4><div class="pfw-tree"></div></nav>
					<main class="pfw-main"><div class="pfw-hint">${__("Drag empty space to pan. Use the mouse wheel to zoom.")}</div><div class="pfw-viewport"><div class="pfw-canvas"></div></div><div class="pfw-empty"></div></main>
					<aside class="pfw-context"><h4>${__("Details")}</h4><div class="pfw-filters"><label>${__("Shift Date")}<input class="form-control pfw-shift-date" type="date" value="${floorEscape(this.shift_date)}"></label><div class="pfw-shift-type"><label>${__("Shift Type")}</label><div class="pfw-shift-type-control"></div></div><div class="pfw-filter-actions"><button class="btn btn-default btn-xs" data-action="clear-machine">${__("Clear machine")}</button><button class="btn btn-default btn-xs" data-action="refresh-machine">${__("Refresh")}</button></div><div class="pfw-filter-state" aria-live="polite"></div></div><div class="pfw-details"></div></aside>
				</div>
			</div>`;
		this.bind();
		this.make_shift_type_control();
		this.load_plants();
	}

	async call(method, args = {}) {
		const result = await frappe.call({
			method: FLOOR_API + method,
			args,
			type: method === "save_layout" ? "POST" : "GET",
		});
		return result.message;
	}

	bind() {
		this.root.addEventListener("click", event => {
			const action = event.target.closest("[data-action]");
		if (action) { if (action.tagName === "A") event.preventDefault(); this.action(action.dataset.action, action.dataset.id); }
		});
		this.root.addEventListener("input", event => this.update_property(event));
		this.root.querySelector(".pfw-shift-date").addEventListener("change", event => { this.shift_date = event.target.value || frappe.datetime.get_today(); this.load_selected_machine(); });
		this.root.querySelector(".pfw-viewport").addEventListener("wheel", event => {
			event.preventDefault(); this.zoom = Math.max(.35, Math.min(2.5, this.zoom + (event.deltaY < 0 ? .1 : -.1))); this.transform();
		}, { passive: false });
		this.root.querySelector(".pfw-viewport").addEventListener("pointerdown", event => this.pointer_down(event));
		window.addEventListener("beforeunload", event => {
			if (this.dirty) { event.preventDefault(); event.returnValue = ""; }
		});
	}

	make_shift_type_control() {
		this.shift_type_control = frappe.ui.form.make_control({
			parent: this.root.querySelector(".pfw-shift-type-control"),
			df: { fieldname: "shift_type", label: __("Shift Type"), fieldtype: "Link", options: "Shift Type", change: () => { this.shift_type = this.shift_type_control.get_value() || null; this.load_selected_machine(); } },
			render_input: true,
		});
	}

	async load_plants() {
		try {
			this.sites = await this.call("list_sites"); this.render_tree();
			const saved = sessionStorage.getItem("qcmc_floor_workbench_return");
			if (saved) {
				const state = JSON.parse(saved); sessionStorage.removeItem("qcmc_floor_workbench_return");
				if (state.shift_date) { this.shift_date = state.shift_date; this.root.querySelector(".pfw-shift-date").value = state.shift_date; }
				if (state.shift_type) { this.shift_type = state.shift_type; this.shift_type_control.set_value(state.shift_type); }
				if (this.sites.some(site => site.name === state.site && site.configured)) {
					await this.open_site(state.site);
					if (this.layout?.buildings.some(building => building.id === state.building)) {
						this.building = state.building; this.expandedBuildings.add(state.building);
						if (this.selected_element_by_id(state.selected)?.kind === "machine") { this.selected = state.selected; await this.load_selected_machine(); }
						this.render();
					}
				}
			}
		}
		catch (error) { frappe.msgprint(__("Could not load permitted sites.")); }
	}

	selected_element_by_id(id) {
		return this.layout?.buildings.flatMap(building => building.interior.elements).find(element => element.id === id);
	}

	async open_site(name) {
		if (this.dirty && !window.confirm(__("Discard unsaved layout changes?"))) return;
		this.site = name; this.building = null; this.selected = null; this.machineRequestId++; this.machineContext = null; this.machineContextState = "idle"; this.mode = "view";
		try {
			const record = await this.call("get_layout", { production_site: name });
			this.layout = record.layout; this.version = record.version; this.can_edit = record.can_edit; this.company = record.company; this.plant_floors = record.plant_floors || [];
			this.context = { workstations: [], process_cards: [] }; this.dirty = false; this.zoom = 1; this.pan = { x: 0, y: 0 };
			this.expandedBuildings = new Set(); this.render();
			try {
				this.context = await this.call("get_floor_context", { production_site: name });
				this.render_tree(); this.render_canvas();
			} catch (error) {
				console.error("Production Floor Workbench could not load Workstation context", error);
				frappe.msgprint({title: __("Workstation details unavailable"), message: error?.message || __("Could not load the Workstation list. The saved floor layout is open; machine details may be incomplete."), indicator: "orange"});
			}
		} catch (error) {
			console.error("Production Floor Workbench could not open site layout", error);
			frappe.msgprint({title: __("Could not open the site layout"), message: error?.message || __("Check your Production Site access and try again."), indicator: "red"});
		}
	}

	async load_selected_machine() {
		let element = this.selected_element();
		if (!this.site || !element || element.kind !== "machine") { this.machineRequestId++; this.machineContext = null; this.machineContextState = "idle"; this.render_details(); return; }
		const requestId = ++this.machineRequestId;
		const selection = { site: this.site, machine: element.id, workstation: element.workstation, shift_date: this.shift_date, shift_type: this.shift_type || "" };
		this.machineContext = null; this.machineContextState = "loading"; this.render_details();
		try {
			const context = await this.call("get_machine_context", { production_site: selection.site, workstation: selection.workstation, shift_date: selection.shift_date, shift_type: selection.shift_type || null });
			if (requestId !== this.machineRequestId || !this.is_current_machine_selection(selection)) return;
			this.machineContext = context; this.machineContextState = context.unavailable ? "unavailable" : "ready";
		} catch (error) {
			if (requestId !== this.machineRequestId || !this.is_current_machine_selection(selection)) return;
			this.machineContextState = "error";
		}
		this.render_details();
	}

	is_current_machine_selection(selection) {
		let element = this.selected_element();
		return this.site === selection.site && element?.id === selection.machine && element?.workstation === selection.workstation && this.shift_date === selection.shift_date && (this.shift_type || "") === selection.shift_type;
	}

	remember_floor_context() {
		if (this.site) sessionStorage.setItem("qcmc_floor_workbench_return", JSON.stringify({ site: this.site, building: this.building, selected: this.selected, shift_date: this.shift_date, shift_type: this.shift_type || "" }));
	}

	async save() {
		if (!this.can_edit || !this.dirty) return;
		try {
			const result = await this.call("save_layout", {
				production_site: this.site, layout: JSON.stringify(this.layout), expected_version: this.version,
			});
			this.version = result.version; this.dirty = false; this.render_toolbar(); frappe.show_alert(__("Floor layout saved"));
		} catch (error) { frappe.msgprint(__("Save failed. Another editor may have changed the layout. Copy your changes before reloading.")); }
	}

	async action(action, id) {
		if (action === "toggle-nav") { this.root.querySelector(".pfw-nav").classList.toggle("pfw-panel-open"); return; }
		if (action === "toggle-context") { this.root.querySelector(".pfw-context").classList.toggle("pfw-panel-open"); return; }
		if (action === "site") return this.open_site(id);
		if (action === "toggle-building") { this.expandedBuildings.has(id) ? this.expandedBuildings.delete(id) : this.expandedBuildings.add(id); return this.render_tree(); }
		if (action === "building") {
			this.building = id; this.selected = null; this.machineRequestId++; this.machineContext = null; this.machineContextState = "idle";
			this.expandedBuildings.add(id); this.zoom = 1; this.pan = { x: 0, y: 0 }; this.render();
			if (this.mode === "edit") { this.selected = id; this.render_details(); this.render_canvas(); }
			return;
		}
		if (action === "machine") {
			const building = this.layout?.buildings.find(row => row.interior.elements.some(element => element.id === id));
			if (building) { this.building = building.id; this.selected = id; this.expandedBuildings.add(building.id); this.zoom = 1; this.pan = { x: 0, y: 0 }; this.render(); this.load_selected_machine(); }
			return;
		}
		if (action === "back") { this.building = null; this.selected = null; this.machineRequestId++; this.machineContext = null; this.machineContextState = "idle"; return this.render(); }
		if (action === "select") { this.selected = id; this.render_details(); this.render_canvas(); if (this.selected_element()?.kind === "machine") this.load_selected_machine(); return; }
		if (action === "clear-machine") { this.selected = null; this.machineRequestId++; this.machineContext = null; this.machineContextState = "idle"; this.render_details(); this.render_canvas(); this.render_tree(); return; }
		if (action === "refresh-machine") return this.load_selected_machine();
		if (action === "open-card") { this.remember_floor_context(); return frappe.set_route("process-card-workbench", id); }
		if (action === "open-batch") {
			const now = frappe.datetime.get_today();
			sessionStorage.setItem("qcmc_process_card_batch_context", JSON.stringify({site: this.site, building: id || this.building || "", shift_date: now, shift_type: this.shift_type || ""}));
			return frappe.set_route("process-card-workbench", "batch");
		}
		if (action === "open-workstation") return frappe.set_route("Form", "Workstation", id);
		if (action === "create-card") {
			const workstation = this.machineContext?.workstation;
			if (!this.machineContext?.can_create || !workstation) return;
			this.remember_floor_context();
			sessionStorage.setItem("qcmc_process_card_create_context", JSON.stringify({
				company: this.company, site: this.site, workstation: workstation.name,
				shift_date: this.shift_date, shift_type: this.shift_type || "",
			}));
			return frappe.set_route("process-card-workbench", "new");
		}
		if (action === "view") { this.mode = "view"; this.render(); if (this.selected_element()?.kind === "machine") return this.load_selected_machine(); return; }
		if (action === "edit") { if (this.can_edit) { this.mode = "edit"; this.render(); } return; }
		if (action === "save") return this.save();
		if (action === "zoom-in" || action === "zoom-out") { this.zoom = Math.max(.35, Math.min(2.5, this.zoom + (action === "zoom-in" ? .1 : -.1))); return this.transform(); }
		if (action === "reset-view") { this.zoom = 1; this.pan = { x: 0, y: 0 }; return this.transform(); }
		if (action.startsWith("add-") && this.mode === "edit") return this.add(action.slice(4));
		if (action === "remove" && this.mode === "edit") {
			const row = this.selected_element();
			if (!row) return;
			const prompt = row.kind === "building"
				? __("Remove this building and all machines and floor elements inside it?")
				: __("Remove this element?");
			if (!window.confirm(prompt)) return;
			if (row.kind === "building") {
				const index = this.layout.buildings.findIndex(building => building.id === row.id);
				if (index >= 0) this.layout.buildings.splice(index, 1);
				this.building = null;
				this.expandedBuildings.delete(row.id);
			} else {
				const elements = this.elements();
				const index = elements.findIndex(element => element.id === row.id);
				if (index >= 0) elements.splice(index, 1);
			}
			this.selected = null;
			this.changed();
		}
	}

	add(kind) {
		if (kind === "building" && this.building) return;
		if (kind !== "building" && !this.building) return;
		const element = { id: floorId(), kind, label: __(kind[0].toUpperCase() + kind.slice(1)), x: 40, y: 40, w: kind === "walkway" ? 240 : 140, h: kind === "walkway" ? 45 : 100, color: kind === "walkway" ? "#e4e9ed" : "#d9e8ef" };
		if (kind === "building") element.interior = { width: 1200, height: 800, elements: [] };
		if (kind === "machine") {
			const used = new Set(this.layout.buildings.flatMap(b => b.interior.elements.filter(e => e.kind === "machine").map(e => e.workstation)));
			const available = this.context.workstations.find(row => !used.has(row.name));
			if (!available) return frappe.msgprint(__("No unplaced Workstation is available for this site."));
			element.workstation = available.name; element.label = available.workstation_name || available.name;
		}
		this.elements().push(element); this.selected = element.id; this.changed();
	}

	elements() { return this.building ? this.layout.buildings.find(row => row.id === this.building).interior.elements : this.layout.buildings; }
	current_canvas() { return this.building ? this.layout.buildings.find(row => row.id === this.building)?.interior : this.layout; }
	selected_element() {
		return this.layout?.buildings.find(row => row.id === this.selected) || this.elements().find(row => row.id === this.selected);
	}
	changed() { this.dirty = true; this.render(); }

	render() { this.render_toolbar(); this.render_tree(); this.render_canvas(); this.render_details(); }
	render_toolbar() {
		const title = this.root.querySelector(".pfw-title");
		title.textContent = this.building ? `${this.site} / ${this.layout.buildings.find(b => b.id === this.building)?.label || ""}` : (this.site || __("Select a site"));
		this.root.querySelectorAll(".pfw-edit").forEach(node => node.hidden = this.mode !== "edit");
		this.root.querySelector('[data-action="edit"]').hidden = !this.can_edit;
		this.root.querySelector('[data-action="back"]').hidden = !this.building;
		this.root.querySelector('[data-action="open-batch"]').hidden = !this.site || !this.building || this.mode === "edit";
		this.root.querySelector('[data-action="add-building"]').hidden = this.mode !== "edit" || !!this.building;
		this.root.querySelectorAll('[data-action="add-machine"], [data-action="add-section"], [data-action="add-walkway"], [data-action="add-static"]').forEach(node => node.hidden = this.mode !== "edit" || !this.building);
		this.root.querySelector('[data-action="save"]').disabled = !this.dirty;
		this.root.querySelector(".pfw-zoom").textContent = `${Math.round(this.zoom * 100)}%`;
	}
	render_tree() {
		this.root.querySelector(".pfw-tree").innerHTML = this.sites.map(site => {
			const selected = this.site === site.name;
			const buildings = selected && this.layout ? this.layout.buildings.map(building => {
				const expanded = this.expandedBuildings.has(building.id);
				const machines = building.interior.elements.filter(element => element.kind === "machine");
				return `<div class="pfw-tree-node"><div class="pfw-tree-line"><button class="pfw-tree-toggle" data-action="toggle-building" data-id="${floorEscape(building.id)}" aria-label="${expanded ? __("Collapse") : __("Expand")}">${expanded ? "▾" : "▸"}</button><button data-action="building" data-id="${floorEscape(building.id)}" class="pfw-tree-row pfw-building-row ${this.building === building.id ? "active" : ""}">▣ ${floorEscape(building.label)}</button></div>${expanded ? machines.map(machine => {
					const ws = this.context.workstations.find(row => row.name === machine.workstation);
					return `<button data-action="machine" data-id="${floorEscape(machine.id)}" class="pfw-tree-row pfw-machine-row ${this.selected === machine.id ? "active" : ""}">⚙ ${floorEscape(ws?.workstation_name || machine.label)}${ws?.status ? `<small>${floorEscape(ws.status)}</small>` : ""}</button>`;
				}).join("") : ""}</div>`;
			}).join("") : "";
			return `<button data-action="site" data-id="${floorEscape(site.name)}" class="pfw-tree-row pfw-site-row ${selected ? "active" : ""}" ${site.configured ? "" : "disabled"}>⌂ ${floorEscape(site.name)}${site.configured ? "" : ` <small>(${__("setup needed")})</small>`}</button>${buildings}`;
		}).join("");
	}
	render_canvas() {
		const canvas = this.root.querySelector(".pfw-canvas");
		const empty = this.root.querySelector(".pfw-empty");
		if (!this.layout) { canvas.innerHTML = ""; empty.textContent = __("Choose a site in the navigation panel."); return; }
		const model = this.current_canvas();
		canvas.style.width = `${model.width}px`; canvas.style.height = `${model.height}px`;
		canvas.innerHTML = this.elements().map(row => {
			const machine = this.context.workstations.find(ws => ws.name === row.workstation);
			const status = machine?.status || "";
			return `<div class="pfw-element pfw-${floorEscape(row.kind)} ${this.selected === row.id ? "selected" : ""}" data-element="${floorEscape(row.id)}" style="left:${row.x}px;top:${row.y}px;width:${row.w}px;height:${row.h}px;background:${floorEscape(row.color || "#d9e8ef")}"><span>${floorEscape(row.label)}</span>${row.kind === "machine" && status ? `<small>${floorEscape(status)}</small>` : ""}${this.mode === "edit" ? '<i class="pfw-resize" data-resize="1"></i>' : ""}</div>`;
		}).join("");
		empty.textContent = this.elements().length ? "" : (this.building ? __("No machines or floor elements yet. Switch to Edit to add them.") : __("No buildings yet. Switch to Edit to create one."));
		this.transform();
	}
	transform() { const canvas = this.root.querySelector(".pfw-canvas"); canvas.style.transform = `translate(${this.pan.x}px, ${this.pan.y}px) scale(${this.zoom})`; this.root.querySelector(".pfw-zoom").textContent = `${Math.round(this.zoom * 100)}%`; }

	render_details() {
		const target = this.root.querySelector(".pfw-details");
		const state = this.root.querySelector(".pfw-filter-state");
		const selectedMachine = this.selected_element()?.kind === "machine";
		this.root.querySelector("[data-action='clear-machine']").hidden = !selectedMachine;
		this.root.querySelector("[data-action='refresh-machine']").hidden = !selectedMachine || this.mode === "edit";
		state.textContent = this.machineContextState === "loading" ? __("Loading Workstation and Process Cards…") : this.machineContextState === "error" ? __("Could not load Workstation details or Process Cards. Refresh to try again.") : "";
		if (!this.layout) { target.innerHTML = `<p>${__("Select a site to view its floor plan.")}</p>`; return; }
		let element = this.selected_element();
		const edit = this.mode === "edit";
		if (!element && this.mode === "edit" && this.building) {
			const building = this.layout.buildings.find(row => row.id === this.building);
			if (building) this.selected = building.id;
		}
		element = this.selected_element();
		if (!element) {
			target.innerHTML = `<p>${this.building ? __("Select a machine or floor element.") : __("Select a building to inspect or open it.")}</p><h5>${__("Plant Floors in this site")}</h5><p>${(this.plant_floors || []).map(floorEscape).join(", ") || __("None assigned")}</p>`;
			return;
		}
		const layoutMachine = element.kind === "machine" ? this.context.workstations.find(row => row.name === element.workstation) : null;
		const machine = element.kind === "machine" && this.machineContextState === "ready" ? this.machineContext?.workstation : null;
		const cards = machine ? (this.machineContext?.process_cards || []) : [];
		const field = (name, label, type = "number") => `<label>${floorEscape(label)}<input class="form-control" data-property="${name}" type="${type}" value="${floorEscape(element[name] ?? "")}"></label>`;
		target.innerHTML = `<strong>${floorEscape(element.label)}</strong><p class="text-muted">${floorEscape(element.kind)}</p>
			${edit ? `${field("label", __("Label"), "text")}<div class="pfw-grid-fields">${["x", "y", "w", "h"].map(n => field(n, n.toUpperCase())).join("")}</div>${field("color", __("Color"), "color")}${element.kind === "machine" ? `<label>${__("Workstation")}<select class="form-control" data-property="workstation">${this.context.workstations.map(ws => `<option value="${floorEscape(ws.name)}" ${ws.name === element.workstation ? "selected" : ""}>${floorEscape(ws.workstation_name || ws.name)}</option>`).join("")}</select></label>` : ""}<button class="btn btn-danger btn-sm" data-action="remove">${__("Remove")}</button>` : ""}
			${element.kind === "building" ? `<p><button class="btn btn-default btn-sm" data-action="building" data-id="${floorEscape(element.id)}">${__("Open interior")}</button> <button class="btn btn-primary btn-sm" data-action="open-batch" data-id="${floorEscape(element.id)}">${__("Batch Encoding")}</button></p>` : ""}
			${element.kind === "machine" && !edit ? this.render_machine_context(layoutMachine, machine, cards) : ""}`;
	}

	render_machine_context(layoutMachine, machine, cards) {
		if (this.machineContextState === "loading") return `<hr><p role="status">${__("Loading machine details…")}</p>`;
		if (this.machineContextState === "error") return `<hr><p class="text-danger">${__("Unable to load machine information.")}</p>`;
		if (this.machineContextState === "unavailable" || !machine) return `<hr><h5>${__("Workstation")}</h5><p class="text-warning">${layoutMachine ? __("Linked Workstation is missing, disabled, or not accessible.") : __("This machine has no valid Workstation link.")}</p>`;
		const docstatus = {0: __("Draft"), 1: __("Submitted"), 2: __("Cancelled")};
		return `<hr><h5>${__("Workstation")}</h5><p><a href="#" data-action="open-workstation" data-id="${floorEscape(machine.name)}">${floorEscape(machine.workstation_name || machine.name)}</a></p><p>${__("Type")}: ${floorEscape(machine.workstation_type || __("Not set"))}<br>${__("Status")}: ${floorEscape(machine.status || __("Not set"))}</p><p>${floorEscape(machine.description || "")}</p><h5>${__("Process Cards")}</h5>${cards.length ? cards.map(card => `<button class="pfw-card" data-action="open-card" data-id="${floorEscape(card.name)}">${floorEscape(card.name)}<small>${floorEscape(card.shift_date)} · ${floorEscape(card.shift_type || __("No Shift Type"))} · ${floorEscape(card.status)} · ${floorEscape(docstatus[card.docstatus] || "")}</small></button>`).join("") : `<p class="text-muted">${__("No Process Card for the selected machine and shift.")}</p>`}${this.machineContext?.can_create ? `<button class="btn btn-primary btn-sm" data-action="create-card">${__("Create Process Card")}</button>` : ""}`;
	}

	update_property(event) {
		const key = event.target.dataset.property;
		if (!key) return;
		if (this.mode !== "edit") return;
		const row = this.selected_element(); if (!row) return;
		if (["x", "y", "w", "h"].includes(key)) {
			const value = Number(event.target.value); if (!Number.isFinite(value)) return;
			row[key] = Math.round(value / this.grid) * this.grid;
		} else if (key === "workstation") {
			const used = this.layout.buildings.flatMap(b => b.interior.elements).some(e => e.id !== row.id && e.workstation === event.target.value);
			if (used) { frappe.msgprint(__("Workstation already placed.")); return this.render_details(); }
			row.workstation = event.target.value; this.machineRequestId++; this.machineContext = null; this.machineContextState = "idle";
		} else row[key] = event.target.value;
		this.dirty = true; this.render_canvas(); this.render_toolbar(); this.render_details();
	}

	pointer_down(event) {
		if (event.button !== 0 || !this.layout) return;
		const node = event.target.closest("[data-element]");
		if (node) {
			this.selected = node.dataset.element;
			this.machineRequestId++; this.machineContext = null; this.machineContextState = "idle";
			this.render_details();
			if (this.mode === "view") { this.render_canvas(); if (this.selected_element()?.kind === "machine") this.load_selected_machine(); if (!this.building && event.detail === 2) this.action("building", this.selected); return; }
		}
		const row = node && this.elements().find(e => e.id === node.dataset.element);
		const resize = !!event.target.closest("[data-resize]");
		const start = { x: event.clientX, y: event.clientY, pan: { ...this.pan }, row: row && { ...row } };
		const move = e => {
			if (row && this.mode === "edit") {
				const dx = Math.round((e.clientX - start.x) / this.zoom / this.grid) * this.grid;
				const dy = Math.round((e.clientY - start.y) / this.zoom / this.grid) * this.grid;
				const bounds = this.current_canvas();
				if (resize) { row.w = Math.max(20, Math.min(bounds.width - row.x, start.row.w + dx)); row.h = Math.max(20, Math.min(bounds.height - row.y, start.row.h + dy)); }
				else { row.x = Math.max(0, Math.min(bounds.width - row.w, start.row.x + dx)); row.y = Math.max(0, Math.min(bounds.height - row.h, start.row.y + dy)); }
				node.style.left = `${row.x}px`; node.style.top = `${row.y}px`; node.style.width = `${row.w}px`; node.style.height = `${row.h}px`;
			} else if (!row) { this.pan.x = start.pan.x + e.clientX - start.x; this.pan.y = start.pan.y + e.clientY - start.y; this.transform(); }
		};
		const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); if (row && this.mode === "edit" && ["x", "y", "w", "h"].some(k => row[k] !== start.row[k])) { this.dirty = true; this.render_details(); this.render_toolbar(); } };
		window.addEventListener("pointermove", move); window.addEventListener("pointerup", up, { once: true });
	}
}

ProductionFloorWorkbench.css = `
.pfw{font-family:Inter,Arial,sans-serif;color:#22313d}.pfw-toggle{display:none}.pfw-toolbar{display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:10px 12px;border-bottom:1px solid #dbe3e8;background:#fff}.pfw-toolbar .pfw-title{margin-right:auto;font-size:16px}.pfw-body{display:grid;grid-template-columns:220px minmax(0,1fr) 290px;height:calc(100vh - 160px);min-height:540px}.pfw-nav,.pfw-context{background:#fff;overflow:auto;padding:16px;border-right:1px solid #e3e8eb}.pfw-context{border-right:0;border-left:1px solid #e3e8eb}.pfw-nav h4,.pfw-context h4{font-weight:650;margin:0 0 16px}.pfw-company{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:#6b7b87;margin:14px 4px 5px}.pfw-tree-row{display:block;width:100%;border:0;background:transparent;text-align:left;padding:8px 10px;border-radius:6px;color:#294052}.pfw-tree-row:hover,.pfw-tree-row.active{background:#e9f4f1;color:#0a6658}.pfw-indent{padding-left:24px;font-size:12px}.pfw-main{position:relative;overflow:hidden;background:#f4f7f8}.pfw-hint{position:absolute;top:10px;left:14px;z-index:2;background:#fffbd9;padding:4px 8px;border-radius:4px;color:#6b6542;font-size:11px}.pfw-viewport{width:100%;height:100%;overflow:hidden;touch-action:none;cursor:grab}.pfw-canvas{position:absolute;left:40px;top:50px;transform-origin:0 0;background-color:#fff;background-image:linear-gradient(#e8edf0 1px,transparent 1px),linear-gradient(90deg,#e8edf0 1px,transparent 1px);background-size:20px 20px;box-shadow:0 8px 30px #1232;border:1px solid #cbd6dc}.pfw-element{position:absolute;border:2px solid #607d8b;border-radius:5px;display:flex;align-items:center;justify-content:center;flex-direction:column;text-align:center;padding:6px;overflow:hidden;cursor:pointer;user-select:none;font-weight:600;line-height:1.25}.pfw-element small{font-size:10px;font-weight:400;margin-top:5px}.pfw-element.selected{outline:3px solid #0b8a77;outline-offset:2px}.pfw-machine{border-color:#c48722}.pfw-walkway{border-style:dashed;color:#61717c}.pfw-section{border-color:#6390b2}.pfw-static{border-color:#858f99}.pfw-resize{position:absolute;right:0;bottom:0;width:15px;height:15px;background:#0b8a77;cursor:nwse-resize}.pfw-empty{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);pointer-events:none;background:#fffdf0;padding:9px 13px;border-radius:6px;color:#546776}.pfw-details label{display:block;font-size:12px;margin:12px 0}.pfw-grid-fields{display:grid;grid-template-columns:1fr 1fr;gap:0 8px}.pfw-card{display:block;width:100%;text-align:left;border:1px solid #d5e3e0;background:#eff8f6;padding:8px;margin:5px 0;border-radius:5px}.pfw-card:hover{background:#d9eee9}
.pfw-site-row{font-weight:700;margin-top:7px}.pfw-tree-line{display:flex;align-items:center}.pfw-tree-toggle{flex:0 0 25px;width:25px;height:32px;border:0;background:transparent;color:#61717c;border-radius:4px}.pfw-tree-toggle:hover{background:#eef3f5}.pfw-building-row{flex:1;font-weight:600;padding-left:6px}.pfw-machine-row{padding-left:46px;font-size:12px}.pfw-machine-row small{display:block;color:#788892;font-weight:400;padding-left:19px}.pfw-filters{padding:9px;margin-bottom:12px;border:1px solid #dce5e8;border-radius:6px;background:#f8fafb}.pfw-filters label{display:block;font-size:12px;margin:5px 0}.pfw-shift-type-control .form-group{margin:0}.pfw-filter-actions{display:flex;justify-content:space-between;gap:5px;margin-top:8px}.pfw-filter-state{font-size:11px;color:#637580;margin-top:6px}.pfw-card small{display:block;color:#687983;font-weight:400;margin-top:3px}
@media(max-width:1200px){.pfw-body{grid-template-columns:160px minmax(0,1fr) 240px}.pfw-nav,.pfw-context{padding:10px}}
@media(max-width:899px){.pfw-toggle{display:inline-block}.pfw-body{display:block;height:auto}.pfw-nav,.pfw-context{display:none;height:auto;max-height:240px;border:0;border-bottom:1px solid #e3e8eb}.pfw-nav.pfw-panel-open,.pfw-context.pfw-panel-open{display:block}.pfw-main{height:55vh;min-height:350px}.pfw-hint{display:none}}
`;
