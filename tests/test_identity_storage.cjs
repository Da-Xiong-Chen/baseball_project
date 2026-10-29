const test=require('node:test'),assert=require('node:assert/strict');
const P=require('../docs/players.js');
const groups=require('../docs/pitcher-groups.js');
function storage(values={}){const map=new Map(Object.entries(values));return {getItem:k=>map.has(k)?map.get(k):null,setItem:(k,v)=>map.set(k,v),map};}
const pitchers=[{name:'rebas:CPBL:p',display_name:'新投手',aliases:['舊投手','新投手'],role:'後援',games:30}];
test('saved pitcher groups map to IDs and retain the exact original backup',()=>{
  global.PlayerIdentity=P;P.setRegistry({'rebas:CPBL:p':'新投手'});
  const key='cpbl-pitcher-groups-v3:A',raw=JSON.stringify({version:3,selected:'勝投組',groups:groups.names.map((name,i)=>({name,members:i===0?['舊投手']:[]}))});
  const s=storage({[key]:raw}),state=groups.loadState(s,'A',pitchers);
  assert.equal(s.getItem(key+':identity-backup'),raw);
  assert.deepEqual(state.groups[0].members,['rebas:CPBL:p']);
  assert.deepEqual(JSON.parse(s.getItem(key)).groups[0].members,['rebas:CPBL:p']);delete global.PlayerIdentity;
});
test('ambiguous groups preserve old values without selecting an arbitrary player',()=>{
  global.PlayerIdentity=P;
  const pool=[...pitchers,{...pitchers[0],name:'rebas:CPBL:q'}];
  const key='cpbl-pitcher-groups-v3:B',raw=JSON.stringify({version:3,groups:groups.names.map((name,i)=>({name,members:i===0?['舊投手']:[]}))});
  const s=storage({[key]:raw}),state=groups.loadState(s,'B',pool);
  assert.equal(s.getItem(key),raw);assert.equal(s.getItem(key+':identity-backup'),raw);
  assert.equal(groups.membership(state.groups[0],pool.map(p=>p.name)).selected.length,0);
  assert.match(state.error,/無法唯一/);delete global.PlayerIdentity;
});
test('confirmed legacy lineup keeps order and positions while moving to IDs',()=>{
  global.PlayerIdentity=P;
  const hitters=Array.from({length:9},(_,i)=>({name:'rebas:CPBL:h'+i,display_name:'打者'+i,aliases:['打者'+i]}));
  const roster={hitters,pitchers};P.registerRoster('C',roster);
  const positions=['C','1B','2B','3B','SS','LF','CF','RF','DH'];
  const config={pitcher:'舊投手',slots:hitters.map((p,i)=>({name:p.display_name,pos:positions[i]}))};
  const raw=JSON.stringify({version:1,season:2025,draft:config,confirmed:config}),key='cpbl-lineup-2025-v1:C';
  global.localStorage=storage({[key]:raw});delete require.cache[require.resolve('../docs/lineup.js')];
  const board=require('../docs/lineup.js'),current=board.current('C');
  assert.deepEqual(current.slots.map(x=>x.name),hitters.map(x=>x.name));assert.deepEqual(current.slots.map(x=>x.pos),positions);
  assert.equal(current.pitcher,'rebas:CPBL:p');assert.equal(global.localStorage.getItem(key),raw);
  assert.equal(global.localStorage.getItem(key+':identity-backup'),raw);delete global.localStorage;delete global.PlayerIdentity;
});
test('ambiguous confirmed lineup is disabled for evaluation and backed up',()=>{
  global.PlayerIdentity=P;
  const hitters=Array.from({length:9},(_,i)=>({name:'rebas:CPBL:z'+i,display_name:'Z'+i,aliases:i<2?['同名']:['Z'+i]}));
  P.registerRoster('D',{hitters,pitchers});
  const positions=['C','1B','2B','3B','SS','LF','CF','RF','DH'];
  const config={pitcher:'舊投手',slots:hitters.map((p,i)=>({name:i===0?'同名':p.display_name,pos:positions[i]}))};
  const raw=JSON.stringify({version:1,season:2025,draft:config,confirmed:config}),key='cpbl-lineup-2025-v1:D';
  global.localStorage=storage({[key]:raw});delete require.cache[require.resolve('../docs/lineup.js')];
  assert.equal(require('../docs/lineup.js').current('D'),null);
  assert.equal(global.localStorage.getItem(key+':identity-backup'),raw);delete global.localStorage;delete global.PlayerIdentity;
});
