"""Install an app-owned workspace overview using Frappe's native custom block."""
import frappe

BLOCK = "Reorder Management - Operational Overview"
BLOCK_ID = "qcmc-reorder-overview"

HTML = """
<section class="rm-overview">
  <div class="rm-heading"><div><h3>Inventory Planning Overview</h3><p>Calculate recommendations, approve reorder values, then monitor and replenish.</p></div><button type="button" class="rm-refresh">Refresh</button></div>
  <div class="rm-status" role="status" aria-live="polite">Loading operational counts...</div>
  <div class="rm-grid" aria-label="Operational counts"></div>
  <div class="rm-actions"></div>
  <h4>Getting started</h4><div class="rm-steps"></div>
</section>
"""
STYLE = """
.rm-overview{padding:12px 4px;color:var(--text-color,#202124)}
.rm-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.rm-heading h3{margin:0 0 5px;font-size:18px}
.rm-heading p,.rm-status{font-size:13px;color:var(--text-muted,#606770)}
.rm-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:10px;margin:12px 0}
.rm-grid button,.rm-refresh,.rm-actions button,.rm-steps button{background:var(--card-bg,transparent);color:inherit;border:1px solid var(--border-color,#c8ccd0);border-radius:8px;padding:10px 12px;cursor:pointer}
.rm-grid button{text-align:left;display:flex;flex-direction:column;gap:8px}
.rm-grid strong{font-size:24px}.rm-grid span{font-size:12px}
.rm-grid button:hover,.rm-actions button:hover,.rm-steps button:hover{border-color:var(--text-muted,#606770)}
.rm-actions{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 20px}
.rm-steps{display:grid;gap:6px}.rm-steps button{text-align:left}
.rm-overview h4{font-size:15px;margin:12px 0 8px}
"""
SCRIPT = """
const section=root_element.querySelector(".rm-overview");
if(section) {
    const status=section.querySelector(".rm-status");
    const grid=section.querySelector(".rm-grid");
    const steps=section.querySelector(".rm-steps");
    const actions=section.querySelector(".rm-actions");
    const refresh=section.querySelector(".rm-refresh");
    let loading=false;
    const make=(tag,text,container)=>{
        const el=document.createElement(tag);
        el.textContent=text;
        container.appendChild(el);
        return el;
    };
    const button=(container,label,route)=>{
        const el=make("button",label,container);
        el.type="button";
        el.addEventListener("click",()=>frappe.set_route(...route));
        return el;
    };
    async function load() {
        if(loading) return;
        grid.replaceChildren(); steps.replaceChildren(); actions.replaceChildren();
        if(frappe.session.user!=="Administrator") {
            status.textContent="Operational overview is restricted to Administrator until delegated access is validated.";
            refresh.disabled=true;
            return;
        }
        loading=true;
        refresh.disabled=true;
        status.textContent="Loading operational counts...";
        try {
            const response=await frappe.call({method:"qcmc_logic.dynamic_reorder_dashboard.overview",type:"GET"});
            const d=response.message;
            if(!d) throw new Error("No overview data");
            const cards=[
                ["Approved item / mapping pairs",d.managed,["List","Reorder Calculation History",{status:"Approved"}]],
                ["Batch items awaiting review",d.pending,["List","Reorder Calculation Batch",{status:"Pending Review"}]],
                ["Draft replenishment requests",d.drafts,["List","Material Request",{docstatus:0,custom_replenishment_mapping:["is","set"]}]],
                ["Active warehouse mappings",d.active_mappings,["List","Reorder Policy Mapping",{enabled:1}]]
            ];
            for(const [label,value,route] of cards) {
                const card=button(grid,"",route);
                make("span",label,card); make("strong",String(value),card);
            }
            status.textContent=(d.automatic_ready?"Automatic drafts configured":d.manual_ready?"Manual drafts available":"Draft generation blocked")+" | Native auto reorder: "+(d.native_enabled?"Enabled":"Disabled")+" | Last execution: "+(d.last_execution?d.last_execution.status:"Not recorded")+". Counts are not live shortage totals.";
            for(const [label,route] of [
                ["Calculate recommendations",["query-report","Reorder Analysis"]],
                ["Review recommendations",["List","Reorder Calculation Batch",{status:"Pending Review"}]],
                ["Monitor stock",["query-report","Replenishment Monitoring"]],
                ["Run replenishment / settings",["Form","Reorder Settings","Reorder Settings"]]
            ]) button(actions,label,route);
            for(const [done,label,route] of [
                [d.enabled,"Enable Reorder Settings",["Form","Reorder Settings","Reorder Settings"]],
                [d.policies>0,"Create a reorder policy",["List","Reorder Policy"]],
                [d.active_mappings>0,"Map warehouses",["List","Reorder Policy Mapping"]],
                [d.managed>0,"Calculate and approve",["query-report","Reorder Analysis"]],
                [d.manual_ready,"Enable draft request generation",["Form","Reorder Settings","Reorder Settings"]]
            ]) button(steps,(done?"✓ ":"○ ")+label,route);
        } catch(error) {
            status.textContent="Overview could not be loaded. Check access and migration, then refresh.";
        } finally {
            loading=false; refresh.disabled=false;
        }
    }
    refresh.addEventListener("click",load);
    load();
}
"""


def install_overview(workspace):
    # Only manage our named block; never modify other workspace blocks.
    if frappe.db.exists("Custom HTML Block", BLOCK):
        doc = frappe.get_doc("Custom HTML Block", BLOCK)
        if doc.owner != "Administrator":
            frappe.throw("Reorder overview block name is already in use")
    else:
        doc = frappe.new_doc("Custom HTML Block")
        doc.name = BLOCK
    doc.update(dict(html=HTML,style=STYLE,script=SCRIPT,private=0))
    doc.set("roles",[{"role":"System Manager"}])
    doc.save(ignore_permissions=True)
    if not any(row.custom_block_name==BLOCK for row in workspace.custom_blocks):
        workspace.append("custom_blocks",{"custom_block_name":BLOCK,"label":BLOCK})
    return {"id":BLOCK_ID,"type":"custom_block","data":{"custom_block_name":BLOCK,"col":12}}
