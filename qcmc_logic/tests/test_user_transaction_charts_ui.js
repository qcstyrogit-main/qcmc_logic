const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const escape = value => String(value).replace(/[&<>"']/g, char => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[char]));
const context = {frappe: {utils: {escape_html: escape}}, __: text => text, console};
vm.runInNewContext(fs.readFileSync("qcmc_logic/public/js/user_transaction_charts.js", "utf8"), context);
const data = context.frappe.user_transaction_chart_data;
const scope = {
    date_from: "2026-10-01", date_to: "2026-10-30",
    doctypes: ["Purchase Order", "Purchase Invoice"], modules: {"Purchase Order":"Buying", "Purchase Invoice":"Accounts"},
    rows: [
        {user:"alice", employee_name:"Same Name", monitored:true, can_create:["Purchase Order","Purchase Invoice"], counts:{"Purchase Order":5,"Purchase Invoice":3}},
        {user:"bob", employee_name:"Same Name", monitored:true, can_create:["Purchase Order"], counts:{}},
        {user:"historic", employee_name:"Historical", monitored:false, can_create:[], counts:{"Purchase Invoice":2}},
    ],
};
const config = {id:"c_test", title:"Example", type:"bar", metric:"documents", group_by:"module", top_n:10};
function chart(overrides = {}, input = scope) { return data.aggregate({...config, ...overrides}, input); }
assert.equal(JSON.stringify(chart().labels), '["Accounts","Buying"]');
assert.equal(JSON.stringify(chart().datasets[0].values), '[5,5]');
assert.equal(JSON.stringify(chart({metric:"adoption",type:"stacked_bar"}).datasets.map(d=>d.values)), '[[1,1],[1,0]]');
assert.equal(chart({metric:"usage_rate"}).datasets[0].values.includes(50), true);
assert.equal(chart({metric:"usage_rate"}).datasets[0].values.includes(100), true);
const overall = chart({metric:"adoption",group_by:"overall",type:"donut"});
assert.equal(JSON.stringify(overall.datasets[0].values), '[1,1]', "Users spanning modules count once in adoption");
assert.ok(chart({group_by:"user"}).labels.includes("Same Name (alice)"));
assert.ok(chart({group_by:"user"}).labels.includes("Same Name (bob)"));
assert.equal(chart({metric:"usage_rate"}, {...scope, rows:[]}).empty, true);
const many = {...scope, doctypes:Array.from({length:7},(_,i)=>`Type ${i}`), rows:[{user:"x",counts:Object.fromEntries(Array.from({length:7},(_,i)=>[`Type ${i}`,i+1]))}]};
const pie = chart({type:"pie",group_by:"doctype",top_n:5}, many);
assert.equal(pie.labels.at(-1), "Other");
assert.equal(pie.datasets[0].values.reduce((a,b)=>a+b,0),28);
assert.equal(chart({type:"line",group_by:"month"}, {...scope, trend:{labels:["2026-09","2026-10"],values:[0,10]}}).datasets[0].values[0],0);
for (const invalid of [{type:"pie",metric:"usage_rate"}, {type:"line",group_by:"module"}, {type:"stacked_bar",metric:"documents"}, {metric:"adoption",type:"pie",group_by:"module"}]) {
    assert.throws(()=>data.validate({...config,...invalid}));
}
const options = data.chart_options({...config,title:"<script>bad()</script>"}, {labels:["<img src=x>"],datasets:[{name:"<b>name</b>",values:[1]}]});
assert.equal(options.title, "<script>bad()</script>", "Native SVG writes textContent; labels must remain human-readable");
assert.equal(options.data.labels[0], "<img src=x>");
let rendered = false, tooltip;
const native = {realData:{labels:["all"],datasets:[{values:[7]}]},update(value){rendered=value.datasets[0].values[0]===7;},
    tip:{setValues(x,y,title,rows){tooltip={title,rows};}}};
data.render_native(native);
assert.equal(rendered,true,"Native zero/partial initial data is replaced synchronously before export");
native.tip.setValues(0,0,{name:"<img src=x>",value:"<script>bad()</script>"},[{title:"<b>dataset</b>",value:7}]);
assert.equal(tooltip.title.name,"&lt;img src=x&gt;", "Native HTML tooltips still receive escaped text");
assert.equal(tooltip.rows[0].title,"&lt;b&gt;dataset&lt;/b&gt;");
const printed = data.report_html(scope,[{...config,title:"<script>bad()</script>", model:chart(),svg:""}],{using:1,not_using:1,usage_rate:50,documents:10},"2026-10-30 17:00");
assert.ok(printed.includes("2026-10-01"));
assert.ok(printed.includes("&lt;script&gt;bad()&lt;/script&gt;"));
assert.ok(!printed.includes("<script>bad()"));
assert.ok(printed.includes("<table"), "Print snapshot includes independently readable chart values");
async function lifecycle() {
    const requests = [], messages = [];
    let destroyed = 0, exports = 0, printed = "";
    class Element {
        constructor() { this.children=new Map(); this[0]={}; }
        html(value) { this.value=value; return this; }
        text(value) { this.value=value; return this; }
        empty() { this.value=""; this.children.clear(); return this; }
        find(selector) { if (!this.children.has(selector)) this.children.set(selector,new Element()); return this.children.get(selector); }
        prop(key,value) { this[key]=value; return this; }
        on() { return this; }
        appendTo() { return this; }
    }
    context.$ = () => new Element();
    context.document = {getElementById:()=>({})};
    const printSheet = {scrollHeight: 900, style: {}, getBoundingClientRect: () => ({height: 900})};
    const svgAttrs = {width: "600", height: "300"};
    const printSvg = {getAttribute: key => svgAttrs[key] || null, setAttribute: (key, value) => {svgAttrs[key] = value;}};
    context.window = {open:()=>({document:{
        open(){},close(){},write(html){printed=html;},
        querySelector: selector => selector === "#report-sheet" ? printSheet : null,
        querySelectorAll: selector => selector === ".report-chart svg" ? [printSvg] : [],
        createElement: () => ({style:{},getBoundingClientRect:()=>({height:733}),remove(){}}),
        body:{appendChild(){}},
    },focus(){},print(){}})};
    context.frappe.datetime = {now_datetime:()=>"2026-10-30 17:00"};
    context.frappe.msgprint = text=>messages.push(text);
    context.frappe.call = options=>new Promise((resolve,reject)=>requests.push({options,resolve,reject}));
    context.frappe.Chart = class {
        constructor(parent,options) { this.svg={outerHTML:"<svg></svg>"}; this.options=options; this.realData=options.data; }
        update(data) { this.data=data; }
        destroy() { destroyed++; }
        export() { exports++; }
    };
    const controller = new context.frappe.UserTransactionCharts({$root:new Element()});
    const fullScope={...scope,selections:{users:[],modules:[],doctypes:[]},summary:{using:1,not_using:1,usage_rate:50,documents:10},data_version:1};
    controller.update(fullScope);
    requests.shift().resolve({message:{charts:[]}});
    await controller.ready;
    assert.equal(controller.definitions.length,0,"An intentionally empty personal layout does not restore default charts");
    controller.definitions=[config];
    await controller.render();
    assert.equal(controller.instances.size,1);
    controller.instances.get(config.id).export();
    assert.equal(exports,1);
    controller.print();
    assert.ok(printed.includes("<svg></svg>"));
    assert.ok(printed.includes("Creation period"));
    assert.ok(printed.includes('id="report-sheet"'), "Printable report has a measurable single-sheet wrapper");
    assert.equal(svgAttrs.viewBox, "0 0 600 300", "SVG drawing coordinates are preserved");
    assert.equal(svgAttrs.preserveAspectRatio, "xMidYMid meet", "SVG is scaled without cropping");
    assert.equal(Number(printSheet.style.zoom) < 1, true, "Report scales to the usable A4 page height before printing");
    assert.ok(printed.includes('class="report-charts"'), "Print charts are packed into a compact grid");
    assert.ok(printed.includes("grid-template-columns:repeat(3,minmax(0,1fr))"), "Compact print layout uses three columns before moving to another page");
    assert.ok(printed.includes("max-height:88px"), "Print charts have a compact page-fitting height");
    assert.ok(!printed.includes("section{break-inside:avoid;page-break-inside:avoid;margin:28px 0}"), "Old wasteful section spacing was removed");
    controller.definitions=[{...config,type:"line",group_by:"month"}];
    const oldRender=controller.render();
    const old=requests.shift();
    controller.print();
    assert.ok(messages.at(-1).includes("Wait"),"Printing is blocked while a trend is pending");
    controller.update({...fullScope,date_from:"2026-09-01",data_version:2});
    const current=requests.shift();
    current.resolve({message:{labels:["2026-09","2026-10"],values:[0,20]}});
    await new Promise(resolve=>setImmediate(resolve));
    old.resolve({message:{labels:["2026-10"],values:[999]}});
    await oldRender;
    assert.equal(controller.models.get(config.id).model.datasets[0].values.at(-1),20,"Stale trend cannot overwrite new scope");
    assert.ok(destroyed>=1,"Replaced charts release their observers and listeners");
    const saving=controller.save();
    controller.edit_revision++;
    requests.shift().resolve({message:{charts:controller.definitions}});
    await saving;
    assert.ok(controller.$host.find(".utd-layout-status").value.includes("Newer chart changes"));
    const currentDefinitions=controller.definitions;
    const failedSave=controller.save();
    requests.shift().reject(new Error("offline"));
    await failedSave;
    assert.equal(controller.definitions,currentDefinitions);
    controller.clear();
    assert.equal(controller.models.size,0);
    assert.equal(controller.instances.size,0);
    assert.equal(controller.$host.find('[data-action="print"]').disabled,true);
    console.log("PASS: grouped metrics, ranking/Other, escaped print snapshot, empty saved layout, SVG export, pending print guard, stale trends, chart cleanup and save races/errors");
}
lifecycle().catch(error=>{console.error(error);process.exitCode=1;});
