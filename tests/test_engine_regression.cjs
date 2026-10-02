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
test('fixed scenarios preserve all original recommendation outputs',async()=>{
  const before=await engine(path.join(root,'output/qa/baseline/engine.js'),path.join(root,'output/qa/baseline/model.json'));
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
  for(const body of fixtures){const a=after.evaluate(body);assert.equal(JSON.stringify(a),JSON.stringify(before.evaluate(body)));results.push(a);}
  fs.mkdirSync(path.join(root,'tests/fixtures'),{recursive:true});
  fs.writeFileSync(path.join(root,'tests/fixtures/qa_scenarios.json'),JSON.stringify(fixtures,null,2));
  fs.writeFileSync(path.join(root,'output/qa/engine_regression.json'),JSON.stringify({scenarios:fixtures.length,exact_match:true,results},null,2));
});
