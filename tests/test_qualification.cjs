const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
test('personal sample qualification isolates players and respects exact boundaries',()=>{
  const c={};vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(__dirname,'../docs/qualification.js'),'utf8'),c);
  c.data={policy:{min_pa:100,min_outs:60},cutoffs:{'2025-04-01':{hitters:{A:[99,'2024-09-01'],B:[100,'2024-09-02']},pitchers:{P:[59,'2024-09-01'],Q:[60,'2024-09-02']}}}};
  c.result={model_cutoff:'2025-04-01',situation:{pitcher:'Q'},candidates:[{球員:'A'},{球員:'B'},{球員:'New'}],bullpen:{rows:[{投手:'P'},{投手:'Q'}],next:['B']}};
  vm.runInContext('Qualification.configure(data);Qualification.annotate(result)',c);
  assert.equal(vm.runInContext('Qualification.innings(60)',c),'20 局');
  assert.equal(vm.runInContext('Qualification.innings(32)',c),'10 局 2 出局');
  assert.deepEqual(c.result.candidates.map(x=>x['可列入排名']),[false,true,false]);
  assert.deepEqual(c.result.bullpen.rows.map(x=>x['可列入排名']),[false,true]);
  assert.equal(c.result.candidates[0]['個人樣本'],99);
  c.result.situation.pitcher='P';vm.runInContext('Qualification.annotate(result)',c);
  assert.ok(c.result.candidates.every(x=>!x['可列入排名']));
  c.result.bullpen.next=['A'];vm.runInContext('Qualification.annotate(result)',c);
  assert.ok(c.result.bullpen.rows.every(x=>!x['可列入排名']));
  c.result.model_cutoff='2025-03-31';vm.runInContext('Qualification.annotate(result)',c);
  assert.ok(c.result.candidates.every(x=>!x['可列入排名']));
  assert.equal(c.result.candidates[1]['個人樣本'],null); // Never fall back to future cutoff.
});
