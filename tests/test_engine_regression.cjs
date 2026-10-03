const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'..');
async function engine(file,model){
  const parameters=JSON.parse(fs.readFileSync(model,'utf8'));
  if(file.includes('baseline') && parameters.identities){
    // The old engine expects names. Project identical ID parameters onto unique display aliases.
    for(const [role,tables] of [['batter',['bat_all','bat_cell']],['pitcher',['pit_all','mix']]]){
      for(const table of tables)parameters[table]=Object.fromEntries(Object.entries(parameters.identities[role]).map(([name,id])=>[name,parameters[table][id]]));
    }
  }
  const c={fetch:async()=>({json:async()=>parameters})};
  vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(root,'docs/qualification.js'),'utf8'),c);
  vm.runInContext(fs.readFileSync(file,'utf8')+'\nthis.engine=Engine;',c);
  await c.engine.load();return c.engine;
}
test('same exported parameters preserve original calculation formulas across 18 scenarios',async()=>{
  // Training labels intentionally changed in v4. Compare formulas with identical parameters,
  // while independently checking Python/export parity in verify_decisions.py.
  const before=await engine(path.join(root,'output/qa/baseline/engine.js'),path.join(root,'docs/data/model.json'));
  const after=await engine(path.join(root,'docs/engine.js'),path.join(root,'docs/data/model.json'));
  const teams=after.model().teams, fixtures=[];
  for(let i=0;i<teams.length;i++){
    const bat=teams[i],fld=teams[(i+1)%teams.length],my=after.model().rosters[bat],opp=after.model().rosters[fld];
    for(const inning of [1,7,9]) {
      fixtures.push({inning,half:'home',outs:1,bases:3,bat_score:2,fld_score:3,pitcher:opp.pitchers[0].name,
        due:my.hitters[0].name,due_pos:'DH',bench:my.hitters.slice(1,5).map(h=>h.name),bat_team:bat,fld_team:fld,
        next_batters:my.hitters.slice(0,3).map(h=>h.name),pen:opp.pitchers.slice(1,4).map(p=>p.name),pitch_count:90,starter:true});
    }
  }
  const results=[];
  const project=(ref,value)=>Array.isArray(ref)?ref.map((r,i)=>project(r,value[i])):ref&&typeof ref==='object'?Object.fromEntries(Object.keys(ref).map(k=>[k,project(ref[k],value[k])])):value;
  for(const body of fixtures){
    const a=after.evaluate(body), original=before.evaluate(body);
    for(const [current,prior] of [[a.candidates,original.candidates],[a.bullpen.rows,original.bullpen.rows]]){
      current.forEach((row,i)=>{
        // Only percentile tie rounding changed: the browser now matches Python's even rounding.
        assert.ok(Math.abs(row['價值分數']-prior[i]['價值分數'])<=1);
        prior[i]['價值分數']=row['價值分數'];
      });
    }
    assert.equal(JSON.stringify(project(original,a)),JSON.stringify(original));results.push(a);
  }
  fs.mkdirSync(path.join(root,'tests/fixtures'),{recursive:true});
  fs.writeFileSync(path.join(root,'tests/fixtures/qa_scenarios.json'),JSON.stringify(fixtures,null,2));
  fs.writeFileSync(path.join(root,'output/qa/engine_regression.json'),JSON.stringify({scenarios:fixtures.length,same_parameter_formula_match:true,training_version:after.model().training_version,results},null,2));
});
