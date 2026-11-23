const assert=require('assert');
const fs=require('fs');
const vm=require('vm');
const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const context={frappe:{treeview_settings:{},utils:{escape_html:escape,get_form_link:(dt,name)=>`/desk/${dt.toLowerCase().replaceAll(' ','-')}/${encodeURIComponent(name)}`}},__:value=>value};
vm.createContext(context);
vm.runInContext(fs.readFileSync('qcmc_logic/qcmc_logics/doctype/storage_location/storage_location_tree.js','utf8'),context);
const display=context.location_movement_reference_display;
assert.equal(typeof display,'function');
for(const [doctype,label] of [['Purchase Receipt','Warehouse Receiving Report'],['Warehouse Transfer','Warehouse Transfer'],['Delivery Note','Delivery Note Return'],['Stock Entry','Stock Entry']]) {
 const html=display({movement_type:'Storage Allocation',reference_name:'WA-1',source_doctype:doctype,source_document:'SOURCE-1'});
 assert(html.indexOf(label)<html.indexOf('SOURCE-1'));
 assert(html.indexOf('SOURCE-1')<html.indexOf('WA-1'));
 assert(html.includes('/storage-allocation/WA-1'));
 assert(html.includes('/'+doctype.toLowerCase().replaceAll(' ','-')+'/SOURCE-1'));
}
const legacy=display({movement_type:'Storage Allocation',reference_name:'WA-OLD'});
assert(legacy.includes('Storage Allocation')&&legacy.includes('/storage-allocation/WA-OLD'));
const count=display({movement_type:'Physical Count',reference_name:'COUNT-1'});
assert(count.includes('/stock-reconciliation/COUNT-1'));
const unsafe=display({movement_type:'Storage Allocation',reference_name:'WA-1',source_doctype:'Stock Entry',source_document:'<img>'});
assert(!unsafe.includes('<img>'));
console.log('Movement references show source first, linked allocation second, with legacy/count fallbacks and escaped names');
