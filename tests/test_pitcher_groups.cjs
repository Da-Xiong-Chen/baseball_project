const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const groups=require('../docs/pitcher-groups.js');
const store=()=>{const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)};};
const pitchers=[{name:'A',role:'後援',games:40},{name:'B',role:'後援',games:50},{name:'C',role:'後援',games:30},{name:'D',role:'後援',games:20},{name:'SP',role:'先發',games:60}];
test('exactly three presets persist, including intentional empty groups, isolated by team',()=>{
 const s=store(),data=groups.defaults(pitchers);data[0].members=[];assert.equal(groups.write(s,'A',data),true);
 assert.deepEqual(groups.read(s,'A'),data);assert.deepEqual(groups.read(s,'B'),[]);
 assert.deepEqual(groups.load(s,'A',pitchers)[0].members,[]);
});
test('malformed old data is preserved and never overwritten with defaults',()=>{
 const s=store();s.setItem('cpbl-pitcher-groups-v2:A','{broken');
 assert.equal(groups.loadState(s,'A',pitchers).blocked,true);
 assert.equal(s.getItem('cpbl-pitcher-groups-v2:A'),'{broken');assert.equal(s.getItem('cpbl-pitcher-groups-v3:A'),null);
});
test('denied and silently refusing storage never reports success',()=>{
 const data=groups.defaults(pitchers);
 assert.equal(groups.write({setItem(){throw Error('denied')},getItem(){return null}},'A',data),false);
 assert.equal(groups.write({setItem(){},getItem(){return null}},'A',data),false);
 assert.match(groups.loadState(undefined,'A',pitchers).error,/無法讀取/);
});
test('membership selects available names and keeps missing names for explicit feedback',()=>{
 assert.deepEqual(groups.membership({members:['A','OLD']},['A','B']),{selected:['A'],missing:['OLD']});
});
test('v2 selected custom group migrates while all old presets remain recoverable',()=>{
 const s=store(),old={groups:[{name:'勝投組',members:['D']},{name:'Travel',members:['A']},{name:'Rest',members:['B']}],selected:'Rest'};
 const raw=JSON.stringify(old);s.setItem('cpbl-pitcher-groups-v2:A',raw);
 const state=groups.loadState(s,'A',pitchers);
 assert.deepEqual(state.groups.map(g=>g.name),groups.names);assert.deepEqual(state.groups[2].members,['B']);
 assert.deepEqual(state.groups[0].members,['D']);assert.equal(state.legacy.length,3);assert.equal(s.getItem('cpbl-pitcher-groups-v2:A'),raw);
 assert.deepEqual(groups.load(s,'A',pitchers),state.groups);
});
test('ambiguous legacy groups do not guess a latest or merge members',()=>{
 const s=store();s.setItem('cpbl-pitcher-groups-v1:A',JSON.stringify([{name:'X',members:['A']},{name:'Y',members:['B']}]));
 const state=groups.loadState(s,'A',pitchers);assert.deepEqual(state.groups[2].members,[]);assert.equal(state.legacy.length,2);
});
test('valid v3 is independent of damaged obsolete storage',()=>{
 const s=store(),data=groups.defaults(pitchers);groups.write(s,'A',data);s.setItem('cpbl-pitcher-groups-v2:A','broken');
 assert.deepEqual(groups.loadState(s,'A',pitchers).groups,data);assert.equal(groups.loadState(s,'A',pitchers).error,'');
});
test('extra or missing groups cannot be saved as a valid fixed configuration',()=>{
 const s=store();assert.equal(groups.write(s,'A',[{name:'X',members:['A']}]),false);
 assert.equal(groups.write(s,'A',groups.defaults(pitchers).concat({name:'X',members:['A']})),false);
});
test('six teams have two nonoverlapping reliever templates and an empty custom slot',()=>{
 const model=JSON.parse(fs.readFileSync(require('node:path').join(__dirname,'../docs/data/model.json'),'utf8'));
 for(const [team,roster] of Object.entries(model.rosters)){
  const rows=groups.defaults(roster.pitchers,team);assert.deepEqual(rows.map(g=>g.name),groups.names);assert.deepEqual(rows[2].members,[]);
  const a=new Set(rows[0].members);assert.ok(rows[1].members.every(n=>!a.has(n)));
  assert.ok(rows.slice(0,2).flatMap(g=>g.members).every(n=>roster.pitchers.some(p=>p.name===n&&p.role==='後援')));
 }
});
test('2025 closer stays in the documented suggested winning template when present',()=>{
 const p=[{name:'陳柏豪',role:'後援',games:45},...pitchers];assert.ok(groups.defaults(p,'樂天桃猿')[0].members.includes('陳柏豪'));
});
