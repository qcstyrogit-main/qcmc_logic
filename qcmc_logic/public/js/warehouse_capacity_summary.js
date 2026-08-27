const qcmc_capacity_template = function (context) {
	const rows = (context.data || []).map((d) => {
		const esc = frappe.utils.escape_html;
		const warehouse = esc(d.warehouse || "");
		const item = esc(d.item_code || "");
		const location = esc(d.location || "No Storage Location");
		const rule = esc(d.putaway_rule || d.name || "");
		const percent = flt(d.percent_occupied);
		const button = context.can_write ? `
			<div class="col-sm-1 text-right" style="margin-top:2px">
				<button class="btn btn-default btn-xs qcmc-edit-capacity"
					data-rule="${rule}" style="margin:4px 0;float:left">
					${__("Edit Capacity")}
				</button>
			</div>` : "";
		return `<div class="dashboard-list-item" data-putaway-rule="${rule}" style="padding:7px 15px">
			<div class="row">
				<div class="col-sm-2" style="margin-top:8px"><a data-type="warehouse" data-name="${warehouse}">${warehouse}</a></div>
				<div class="col-sm-2" style="margin-top:8px"><a data-type="item" data-name="${item}">${item}</a></div>
				<div class="col-sm-2" style="margin-top:8px"><strong>${location}</strong></div>
				<div class="col-sm-1" style="margin-top:8px">${flt(d.stock_capacity)}</div>
				<div class="col-sm-1" style="margin-top:8px">${flt(d.actual_qty)}</div>
				<div class="col-sm-2"><div class="progress" style="margin-bottom:4px;height:7px;margin-top:14px">
					<div class="progress-bar" style="width:${percent}%;background-color:${d.color || "#f97316"}"></div>
				</div></div>
				<div class="col-sm-1" style="margin-top:8px">${percent}%</div>${button}
			</div>
		</div>`;
	}).join("");
	return rows;
};

const qcmc_capacity_header = `
	<div class="dashboard-list-item qcmc-capacity-header" style="padding:12px 15px">
		<div class="row text-muted">
			<div class="col-sm-2">${__("Warehouse")}</div>
			<div class="col-sm-2">${__("Item")}</div>
			<div class="col-sm-2">${__("Inventory Dimension")}</div>
			<div class="col-sm-1">${__("Capacity")}</div>
			<div class="col-sm-1">${__("Balance")}</div>
			<div class="col-sm-2">${__("Utilization")}</div>
			<div class="col-sm-1">${__("Occupied")}</div>
			<div class="col-sm-1"></div>
		</div>
	</div>`;

// ERPNext loads item-dashboard.bundle.js asynchronously inside on_page_load.
// Apply our template only after that bundle has created the dashboard; otherwise
// its compiled template replaces this one.
const qcmc_original_capacity_onload =
	frappe.pages["warehouse-capacity-summary"].on_page_load;

frappe.pages["warehouse-capacity-summary"].on_page_load = function (wrapper) {
	qcmc_original_capacity_onload(wrapper);
	let attempts = 0;
	const timer = setInterval(() => {
		attempts += 1;
		const page = wrapper.page;
		if (page && page.capacity_dashboard) {
			clearInterval(timer);
			page.capacity_dashboard.render = function (data) {
				if (this.start === 0 || !this.qcmc_rows) {
					this.qcmc_rows = new Map();
				}
				data = data || [];
				if (data.length === this.page_length + 1) {
					this.content.find(".more").removeClass("hidden");
					data.splice(-1);
				} else {
					this.content.find(".more").addClass("hidden");
				}
				data.forEach((row) => {
					this.qcmc_rows.set(row.putaway_rule || row.name, row);
				});
				const unique_rows = Array.from(this.qcmc_rows.values());
				this.result.empty();
				if (unique_rows.length) {
					unique_rows.forEach((row) => {
						row.color = flt(row.percent_occupied) >= 80 ? "#f8814f" : "#2490ef";
					});
					this.result.css("text-align", "unset");
					this.result.append(qcmc_capacity_template({
						data: unique_rows,
						can_write: frappe.boot.user.can_write.includes("Putaway Rule"),
					}));
				} else {
					this.result.css("text-align", "center").html(
						`<div class="text-muted" style="margin:20px 5px">${__("No Stock Available Currently")}</div>`
					);
				}
			};
			page.main.children(".dashboard-list-item").first().replaceWith(qcmc_capacity_header);
			page.capacity_dashboard.start = 0;
			page.capacity_dashboard.refresh();
		} else if (attempts >= 100) {
			clearInterval(timer);
		}
	}, 100);
};

$(document)
	.off("click.qcmc_capacity", ".qcmc-edit-capacity")
	.on("click.qcmc_capacity", ".qcmc-edit-capacity", function (event) {
		event.preventDefault();
		event.stopImmediatePropagation();
		const rule = $(this).attr("data-rule");
		if (rule) frappe.set_route("Form", "Putaway Rule", rule);
	});
