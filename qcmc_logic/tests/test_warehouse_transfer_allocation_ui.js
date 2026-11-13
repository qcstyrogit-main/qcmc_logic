const assert=require('assert');
const fs=require('fs');
const vm=require('vm');
const context={qcmc_logic:{warehouse_transfer:{}},frappe:{provide:()=>{},ui:{form:{on:()=>{}}}},__:s=>s};
vm.createContext(context);
vm.runInContext(fs.readFileSync('qcmc_logic/public/js/warehouse_transfer.js','utf8'),context);
for(const checked of [0,1]) {
 const changes=[];
 const frm={doc:{docstatus:0,custom_apply_putaway_rule:checked,custom_storage_allocation_enabled:1},is_new:()=>false,set_df_property:(...args)=>changes.push(args),refresh_field:()=>{}};
 context.qcmc_logic.warehouse_transfer.configure_allocation(frm);
 assert.equal(frm.doc.custom_apply_putaway_rule,checked);
 assert(changes.some(([field,prop,value])=>field==='custom_apply_putaway_rule'&&prop==='read_only'&&value===0));
 assert(changes.some(([field,prop,value])=>field==='custom_storage_allocation_section'&&prop==='hidden'&&value===(checked?0:1)));
}
console.log('Warehouse Transfer manual checkbox and native allocation table checks passed');
