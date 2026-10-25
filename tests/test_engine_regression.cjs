const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'..');
async function engine(file,model){
  const c={fetch:async()=>({json:async()=>JSON.parse(fs.readFileSync(model,'utf8'))})};
  vm.createContext(c);vm.runInContext(fs.readFileSync(file,'utf8')+'\nthis.engine=Engine;',c);
  await c.engine.load();return c.engine;
}
test('same exported parameters preserve original calculation formulas across 18 scenarios',async()=>{
  // Compare numeric formulas on the same v5 parameters and known-handed queries,
  // while independently checking Python/export parity in verify_decisions.py.
  const model=path.join(process.env.BASEBALL_STATIC_OUT||path.join(root,'docs/data'),'model.json');
  const before=await engine(path.join(root,'output/qa/baseline/engine.js'),model);
  const after=await engine(path.join(root,'docs/engine.js'),model);
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
  // Percentile half-score rounding is intentionally aligned to Python in v3.
  const metrics=['價值分數','預估勝率','相對現任','誤差','每打席得分值','階層式','機器學習','預估失分','守方勝率增減','疲勞調整'];
  for(const body of fixtures){
    const a=after.evaluate(body),original=before.evaluate(body);
    for(const key of ['candidates','bullpen']){
      const rows=key==='candidates'?a[key]:a[key].rows,old=key==='candidates'?original[key]:original[key].rows;
      assert.equal(rows.length,old.length);
      rows.forEach((row,i)=>{
        assert.equal(row[key==='candidates'?'球員':'投手'],old[i][key==='candidates'?'球員':'投手']);
        for(const metric of metrics)if(metric!=='價值分數'&&typeof old[i][metric]==='number')
          assert.ok(Math.abs(row[metric]-old[i][metric])<=1e-10,metric+' '+row[metric]+' '+old[i][metric]);
      });
    }
    results.push(a);
  }
  fs.mkdirSync(path.join(root,'tests/fixtures'),{recursive:true});
  fs.writeFileSync(path.join(root,'tests/fixtures/qa_scenarios.json'),JSON.stringify(fixtures,null,2));
  const reportDir=process.env.BASEBALL_REPORT_OUT||path.join(root,'output/qa');
  fs.mkdirSync(reportDir,{recursive:true});
  fs.writeFileSync(path.join(reportDir,'engine_regression.json'),JSON.stringify({scenarios:fixtures.length,same_parameter_formula_match:true,training_version:after.model().training_version,results},null,2));
});
