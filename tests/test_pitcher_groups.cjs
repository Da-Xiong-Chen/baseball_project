const {test}=require('node:test');
const assert=require('node:assert/strict');
const groups=require('../docs/pitcher-groups.js');
const store=()=>{const m=new Map();return {getItem:k=>m.get(k),setItem:(k,v)=>m.set(k,v)};};
test('presets persist and remain isolated by team',()=>{
  const s=store(),data=[{name:'勝投組',members:['A','B']}];
  assert.equal(groups.write(s,'TeamA',data),true);
  assert.deepEqual(groups.read(s,'TeamA'),data);
  assert.deepEqual(groups.read(s,'TeamB'),[]);
});
test('corrupt or denied storage never crashes and failed writes are reported',()=>{
  const s={getItem:()=>'{broken',setItem:()=>{throw Error('denied')}};
  assert.deepEqual(groups.read(s,'A'),[]);
  assert.equal(groups.write(s,'A',[]),false);
  assert.deepEqual(groups.read(undefined,'A'),[]);
});
test('invalid presets and duplicate names are filtered without guessing membership',()=>{
  const s=store();groups.write(s,'A',[{name:'',members:['A']},{name:'勝投組',members:['A','A']},
    {name:'勝投組',members:['B']},{name:'bad',members:[42]}]);
  assert.deepEqual(groups.read(s,'A'),[{name:'勝投組',members:['A']}]);
});
test('roster changes select only available group members and report missing members',()=>{
  assert.deepEqual(groups.membership({members:['A','OLD']},['A','B']),
    {selected:['A'],missing:['OLD']});
});
const pitchers=[{name:'A',role:'後援',games:40},{name:'B',role:'後援',games:50},
  {name:'C',role:'後援',games:30},{name:'D',role:'後援',games:20},{name:'SP',role:'先發',games:60}];
test('default templates use reliever appearances only and do not overlap',()=>{
  assert.deepEqual(groups.defaults(pitchers),[{name:'勝投組',members:['B','A','C']},{name:'敗投組',members:['D']}]);
});
test('legacy groups survive migration and missing templates are added only once',()=>{
  const s=store();s.setItem('cpbl-pitcher-groups-v1:A',JSON.stringify([{name:'勝投組',members:['D']}]));
  const loaded=groups.load(s,'A',pitchers);
  assert.deepEqual(loaded,[{name:'勝投組',members:['D']},{name:'敗投組',members:['D']}]);
  assert.equal(groups.write(s,'A',[],''),true);
  assert.deepEqual(groups.load(s,'A',pitchers),[]);
});
test('silent storage refusal cannot report successful persistence',()=>{
  assert.equal(groups.write({getItem:()=>null,setItem:()=>{}},'A',[{name:'test',members:['A']}]),false);
});
test('all six exported teams have two valid nonoverlapping template groups',()=>{
  const fs=require('node:fs'),path=require('node:path');
  const model=JSON.parse(fs.readFileSync(path.join(__dirname,'../docs/data/model.json'),'utf8'));
  const teams=model.rosters;
  assert.ok(teams);
  assert.equal(Object.keys(teams).length,6);
  for(const [team,roster] of Object.entries(teams)){
    const presets=groups.defaults(roster.pitchers,team);
    assert.equal(presets.length,2,team);
    const all=presets.flatMap(g=>g.members);
    assert.equal(new Set(all).size,all.length,team);
    assert.ok(all.every(n=>roster.pitchers.some(p=>p.name===n&&p.role==='後援')),team);
  }
});
test('default winning template includes documented 2025 closer when present',()=>{
  const roster=[...pitchers,{name:'曾峻岳',role:'後援',games:10}];
  const presets=groups.defaults(roster,'富邦悍將');
  assert.deepEqual(presets[0].members,['曾峻岳','B','A']);
  assert.ok(!presets[1].members.includes('曾峻岳'));
});
