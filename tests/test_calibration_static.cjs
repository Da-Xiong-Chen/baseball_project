const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
async function engine(model){
 const c={fetch:async()=>({json:async()=>model})};vm.createContext(c);
 const source=fs.readFileSync(path.join(__dirname,'../docs/engine.js'),'utf8')
   .replace('return { load, evaluate, detail, model: () => M };','return { load, evaluate, detail, runToWin, valueScore, model: () => M };');
 vm.runInContext(source+'\nthis.engine=Engine;',c);await c.engine.load();return c.engine;
}
test('negative local conversion uses parent rather than reversing scoring benefit',async()=>{
 const e=await engine({training_version:5,engine_contract:5,identity_namespace:'rebas:CPBL',batch_id:'test-batch',slope_fine:{'9|away|1|6|1':-.0250555},slope_coarse:{'9|away|1':.07},slope_all:.09});
 assert.equal(e.runToWin(9,'away',2,1,6,1),.07);
 assert.equal(e.runToWin(8,'away',2,1,6,1),.09);
});
test('missing valid calibration fails explicitly and mixed training versions cannot load',async()=>{
 const e=await engine({training_version:5,engine_contract:5,identity_namespace:'rebas:CPBL',batch_id:'test-batch',slope_fine:{},slope_coarse:{},slope_all:-1});
 assert.throws(()=>e.runToWin(9,'away',2,1,6,1),/校準/);
 await assert.rejects(engine({training_version:2,engine_contract:3}),/版本不相容/);
});
test('percentile half-score ties match Python rather than always rounding up',async()=>{
 const e=await engine({training_version:5,engine_contract:5,identity_namespace:'rebas:CPBL',batch_id:'test-batch'});
 const pool=[...Array(17).fill(1),0,...Array(45).fill(-1)];
 assert.equal(e.valueScore(0,pool,false),28); // 28.5 -> 28
 assert.equal(e.valueScore(0,[...Array(18).fill(1),0,...Array(44).fill(-1)],false),30);
});
