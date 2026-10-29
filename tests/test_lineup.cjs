const {test}=require('node:test');const assert=require('node:assert/strict');const L=require('../docs/lineup.js');
const roster={hitters:Array.from({length:12},(_,i)=>({name:'H'+i})),pitchers:[{name:'P0'},{name:'P1'}]};
const config=()=>({slots:L.empty().slots.map((s,i)=>({...s,name:'H'+i})),pitcher:'P0'});
test('complete DH configuration validates nine unique hitters and separate pitcher',()=>{assert.deepEqual(L.validate(config(),roster),[]);let c=config();c.slots[1].name='H0';assert.ok(L.validate(c,roster).length);c=config();c.slots[1].pos='C';assert.ok(L.validate(c,roster).length);c=config();c.pitcher='Unknown';assert.ok(L.validate(c,roster).length);});
test('incomplete, cross-team and unsupported two-way configurations cannot be applied',()=>{assert.ok(L.validate(L.empty(),roster).length);let c=config();c.slots[0].name='OtherTeam';assert.ok(L.validate(c,roster).length);c=config();c.pitcher='H0';assert.ok(L.validate(c,{...roster,pitchers:[{name:'H0'}]}).length);assert.equal(L.validState({version:1,season:2024,draft:c,retired:[]}),false);});

test('malformed draft and confirmed state are rejected',()=>{const c=config(),s={version:1,season:2025,draft:c,confirmed:{}};assert.equal(L.validState(s),false);s.confirmed=c;assert.equal(L.validState(s),true);s.draft={};assert.equal(L.validState(s),false);});
const fs=require('node:fs');const vm=require('node:vm');
function uiFixture(storageMode='ok',loadTeam=async()=>roster){
 const values=new Map(),nodes=new Map(),listeners={};
 const node=id=>{if(!nodes.has(id)){const events={};nodes.set(id,{value:'',textContent:'',innerHTML:'',disabled:false,dataset:{},classList:{add(){},toggle(){}},setAttribute(){},focus(){},showModal(){this.open=true;},close(){this.open=false;for(const fn of events.close||[])fn();events.close=[];},addEventListener(type,fn){(events[type]??=[]).push(fn);},dispatch(type,event){for(const fn of events[type]||[])fn(event);}});}return nodes.get(id);};
 const attrs=new Set(),element={querySelector:node,querySelectorAll:()=>[],setAttribute:a=>attrs.add(a),removeAttribute:a=>attrs.delete(a),hasAttribute:a=>attrs.has(a),addEventListener:(name,fn)=>listeners[name]=fn};
 const storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>{if(storageMode==='throw')throw Error('denied');if(storageMode!=='silent')values.set(k,v);},removeItem:k=>values.delete(k)};
 const context={module:{exports:{}},window:{},localStorage:storage,document:{activeElement:null},console};vm.createContext(context);vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../docs/lineup.js'),'utf8'),context);const api=context.module.exports,applied=[];
 api.mount({element,teams:['A','B'],team:loadTeam,matches:(name,team,q)=>name.includes(q),pitchCount:()=>15,role:()=>true,applied:async(t,c)=>applied.push({team:t,change:c})});
 const pick=(slot,name)=>{listeners.click({target:{closest:sel=>sel==='[data-pick]'?{dataset:{pick:String(slot)}}:null}});if(node('#lineupPicker').open)node('#lineupPlayerList').onclick({target:{closest:()=>({dataset:{player:name},disabled:false})}});};
 return {api,node,pick,values,applied,listeners,element};
}
async function fillUI(f){await f.api.selectTeam('A');for(let i=0;i<9;i++)f.pick(i,'H'+i);f.node('#lineupPitcherPick').onclick({currentTarget:{}});f.node('#lineupPlayerList').onclick({target:{closest:()=>({dataset:{player:'P0'}})}});}
test('UI draft is isolated until apply, and confirmed configuration persists by team',async()=>{const f=uiFixture();await fillUI(f);assert.equal(f.api.current('A'),null);await f.node('#lineupApply').onclick();assert.equal(f.api.current('A').slots.length,9);assert.equal(f.api.current('B'),null);const stored=JSON.parse([...f.values.values()][0]);assert.equal(stored.confirmed.pitcher,'P0');assert.equal(f.applied.length,1);});
test('storage refusal still permits session configuration and never reports saved',async()=>{for(const mode of ['throw','silent']){const f=uiFixture(mode);await fillUI(f);await f.node('#lineupApply').onclick();assert.ok(f.api.current('A'));assert.match(f.node('#lineupMessage').textContent,/無法保存/);}});
test('malformed saved data remains preserved during editing and applying',async()=>{const f=uiFixture();f.values.set('cpbl-lineup-2025-v1:A','broken');await fillUI(f);await f.node('#lineupApply').onclick();assert.equal(f.values.get('cpbl-lineup-2025-v1:A'),'broken');assert.match(f.node('#lineupMessage').textContent,/無法保存/);});

test('field selection exchanges positions for on-field players while retaining their batting order',()=>{const c=config(),names=c.slots.map(s=>s.name),pos=c.slots.map(s=>s.pos);L.assignPlayer(c,0,'H1',true);assert.deepEqual(c.slots.map(s=>s.name),names);assert.equal(c.slots[0].pos,pos[1]);assert.equal(c.slots[1].pos,pos[0]);assert.deepEqual(L.validate(c,roster),[]);});
test('batting-row selection swaps duplicate names instead of producing duplicate lineup entries',()=>{const c=config();L.assignPlayer(c,0,'H1');assert.equal(c.slots[0].name,'H1');assert.equal(c.slots[1].name,'H0');assert.deepEqual(L.validate(c,roster),[]);});
test('reapply directly updates configuration without retirement or confirmation flow',async()=>{const f=uiFixture();await fillUI(f);await f.node('#lineupApply').onclick();f.pick(3,'H9');await f.node('#lineupApply').onclick();assert.equal(f.api.current('A').slots[3].name,'H9');assert.equal(f.applied.at(-1).change.resetPitchCount,false);});
test('legacy retirement records do not constrain the simplified configuration',async()=>{const f=uiFixture(),c=config();f.values.set('cpbl-lineup-2025-v1:A',JSON.stringify({version:1,season:2025,draft:c,confirmed:c,retired:['H9'],undo:{}}));await f.api.selectTeam('A');f.pick(3,'H9');await f.node('#lineupApply').onclick();assert.equal(f.api.current('A').slots[3].name,'H9');assert.equal(JSON.parse(f.values.get('cpbl-lineup-2025-v1:A')).retired,undefined);});

test('explicit order swap retains player positions and pitcher while exchanging distant batting slots',()=>{const c=config(),before=structuredClone(c);assert.equal(L.swapPlayers(c,0,6,'order'),true);assert.deepEqual(c.slots[0],before.slots[6]);assert.deepEqual(c.slots[6],before.slots[0]);assert.equal(c.pitcher,before.pitcher);assert.deepEqual(L.validate(c,roster),[]);});
test('explicit field swap retains batting order and rejects empty or invalid targets',()=>{const c=config(),names=c.slots.map(s=>s.name);assert.equal(L.swapPlayers(c,0,4,'field'),true);assert.deepEqual(c.slots.map(s=>s.name),names);assert.deepEqual(L.validate(c,roster),[]);for(const args of [[0,0,'field'],[0,9,'field'],[0,1,'invalid']])assert.equal(L.swapPlayers(c,...args),false);c.slots[2].name='';assert.equal(L.swapPlayers(c,0,2,'order'),false);});
test('two-click batting exchange supports cancellation and one-step undo without applying',async()=>{const f=uiFixture();await fillUI(f);await f.node('#lineupApply').onclick();f.node('#lineupSwapOrder').onclick();f.pick(0,'H0');f.node('#lineupSwapCancel').onclick();assert.equal(f.api.current('A').slots[0].name,'H0');f.node('#lineupSwapOrder').onclick();f.pick(0,'H0');f.pick(6,'H6');let draft=JSON.parse(f.values.get('cpbl-lineup-2025-v1:A')).draft;assert.equal(draft.slots[0].name,'H6');assert.equal(f.api.current('A').slots[0].name,'H0');f.node('#lineupSwapUndo').onclick();draft=JSON.parse(f.values.get('cpbl-lineup-2025-v1:A')).draft;assert.equal(draft.slots[0].name,'H0');assert.equal(draft.slots[6].name,'H6');});

test('opening and cancelling player picker preserves exchange undo; applying clears it',async()=>{const f=uiFixture();await fillUI(f);await f.node('#lineupApply').onclick();f.node('#lineupSwapOrder').onclick();f.pick(0,'H0');f.pick(6,'H6');assert.equal(f.node('#lineupSwapUndo').hidden,false);f.node('#lineupPitcherPick').onclick({currentTarget:{}});f.node('#lineupPickerClose').onclick();f.node('#lineupSwapUndo').onclick();assert.equal(JSON.parse(f.values.get('cpbl-lineup-2025-v1:A')).draft.slots[0].name,'H0');f.node('#lineupSwapOrder').onclick();f.pick(0,'H0');f.pick(6,'H6');await f.node('#lineupApply').onclick();assert.equal(f.node('#lineupSwapUndo').hidden,true);assert.equal(f.api.current('A').slots[0].name,'H6');});
const defaults=()=>({A:{slots:config().slots,pitcher:'P0',games:30,through:'2025-10-05'}});
test('default lineup is only a draft until applied, and saved records take priority',async()=>{const f=uiFixture();f.api.setDefaults(defaults());await f.api.selectTeam('A');assert.equal(f.api.current('A'),null);assert.match(f.node('#lineupStatus').textContent,/預設名單.*尚未套用/);await f.node('#lineupApply').onclick();assert.deepEqual(JSON.parse(JSON.stringify(f.api.current('A'))),config());const g=uiFixture(),c=config();c.slots[0].name='H9';g.values.set('cpbl-lineup-2025-v1:A',JSON.stringify({version:1,season:2025,draft:c,confirmed:c}));g.api.setDefaults(defaults());await g.api.selectTeam('A');assert.equal(g.api.current('A').slots[0].name,'H9');});
test('invalid default lineups are ignored and defaultFor returns an independent copy',()=>{const bad=defaults();bad.A.slots[1].pos='C';L.setDefaults(bad);assert.equal(L.defaultFor('A'),null);L.setDefaults(defaults());const d=L.defaultFor('A');d.slots[0].name='X';assert.equal(L.defaultFor('A').slots[0].name,'H0');});
test('unapplied edits are labelled, and reset applies and saves the defaults',async()=>{const f=uiFixture();f.api.setDefaults(defaults());await f.api.selectTeam('A');f.pick(0,'H9');assert.match(f.node('#lineupStatus').textContent,/未套用/);assert.ok(f.values.has('cpbl-lineup-2025-v1:A'));await f.node('#lineupReset').onclick();assert.deepEqual(JSON.parse(f.values.get('cpbl-lineup-2025-v1:A')).confirmed,config());assert.deepEqual(JSON.parse(JSON.stringify(f.api.current('A'))),config());assert.match(f.node('#lineupStatus').textContent,/預設名單/);assert.equal(f.applied.at(-1).change.resetPitchCount,false);});
test('release returns to free selection, keeps the draft, and survives reload',async()=>{const f=uiFixture();f.api.setDefaults(defaults());await f.api.selectTeam('A');await f.node('#lineupApply').onclick();assert.ok(f.api.current('A'));f.api.release('A');assert.equal(f.api.current('A'),null);const stored=JSON.parse(f.values.get('cpbl-lineup-2025-v1:A'));assert.equal(stored.confirmed,null);assert.equal(stored.draft.pitcher,config().pitcher);});

test('duplicate saved positions are rejected before a missing field slot can be opened',()=>{const c=config();c.slots[1].pos=c.slots[0].pos;assert.equal(L.validState({version:1,season:2025,draft:c,confirmed:null}),false);});

test('manually withdrawn players cannot remain active and corrupted exclusion data is rejected',()=>{
 const c=config();c.unavailable=[c.pitcher];
 assert.ok(L.validate(c,roster).some(s=>s.includes('已退場')));
 c.unavailable=['Bench'];assert.equal(L.validate(c,roster).length,0);
 assert.equal(L.validState({version:1,season:2025,draft:c,confirmed:c}),true);
 c.unavailable='broken';assert.equal(L.validState({version:1,season:2025,draft:c,confirmed:c}),false);
});
test('same-name pitcher migration keeps lineup order and uses saved team identity',()=>{
 for(const [team,name] of [['樂天桃猿','林子崴〔樂天〕'],['統一7-ELEVEn獅','林子崴〔統一〕']]){
  const c=config(),slots=JSON.stringify(c.slots);c.pitcher='林子崴';c.unavailable=['Other'];
  assert.equal(L.migrateIdentity(c,team),true);assert.equal(c.pitcher,name);
  assert.equal(JSON.stringify(c.slots),slots);assert.deepEqual(c.unavailable,['Other']);
  assert.equal(L.migrateIdentity(c,team),false);
 }
 const c=config();c.pitcher='林子崴';assert.equal(L.migrateIdentity(c,'unknown'),false);assert.equal(c.pitcher,'林子崴');
});
test('restore defaults never claims browser persistence when storage refuses writes',async()=>{for(const mode of ['throw','silent']){const f=uiFixture(mode);f.api.setDefaults({A:config()});await f.api.selectTeam('A');await f.node('#lineupReset').onclick();assert.ok(f.api.current('A'));assert.match(f.node('#lineupMessage').textContent,/無法保存/);}});

test('moving to the first batting slot focuses the player instead of a disabled arrow',async()=>{const f=uiFixture();await fillUI(f);let focused=false;f.node('[data-move="0"][data-step="-1"]').disabled=true;f.node('[data-pick="0"]').focus=()=>{focused=true};f.listeners.click({target:{closest:sel=>sel==='[data-move]'?{dataset:{move:'1',step:'-1'}}:null}});assert.equal(focused,true);const saved=JSON.parse(f.values.get('cpbl-lineup-2025-v1:A'));assert.equal(saved.draft.slots[0].name,'H1');});


test('keyboard position changes preserve focus and swap the other position',async()=>{
 const f=uiFixture();await fillUI(f);let focused=false;f.node('[data-position="0"]').focus=()=>{focused=true};
 f.node('#lineupRows').onchange({target:{matches:()=>true,dataset:{position:'0'},value:'LF'}});
 assert.equal(focused,true);const c=JSON.parse(f.values.get('cpbl-lineup-2025-v1:A')).draft;
 assert.equal(c.slots[0].pos,'LF');assert.equal(c.slots[5].pos,'C');
});

test('late failed team request cannot overwrite the latest successful team status',async()=>{
 let rejectA;const pending=new Promise((_,reject)=>{rejectA=reject});
 const f=uiFixture('ok',name=>name==='A'?pending:Promise.resolve(roster));
 const old=f.api.selectTeam('A');await f.api.selectTeam('B');const message=f.node('#lineupMessage').textContent;
 rejectA(Error('old failure'));await old;
 assert.equal(f.node('#lineupMessage').textContent,message);assert.equal(f.node('#lineupTeam').value,'B');assert.equal(f.node('#lineupApply').disabled,false);
});

test('failed team switch returns selector and apply action to the last loaded team',async()=>{
 const f=uiFixture('ok',name=>name==='A'?Promise.resolve(roster):Promise.reject(Error('offline')));
 await fillUI(f);f.node('#lineupTeam').value='B';await f.api.selectTeam('B');
 assert.equal(f.node('#lineupTeam').value,'A');assert.equal(f.node('#lineupApply').disabled,false);
 assert.match(f.node('#lineupMessage').textContent,/載入失敗/);await f.node('#lineupApply').onclick();assert.ok(f.api.current('A'));assert.equal(f.api.current('B'),null);
});


test('first team load failure keeps apply disabled and picker safe until retry succeeds',async()=>{
 let fail=true;const f=uiFixture('ok',async()=>{if(fail)throw Error('offline');return roster});
 await f.api.selectTeam('A');assert.equal(f.node('#lineupApply').disabled,true);
 assert.doesNotThrow(()=>f.node('#lineupPitcherPick').onclick({currentTarget:{}}));
 assert.notEqual(f.node('#lineupPicker').open,true);fail=false;await fillUI(f);
 await f.node('#lineupApply').onclick();assert.ok(f.api.current('A'));
});

test('unavailable checkbox retains keyboard focus after its list is rebuilt',async()=>{
 const f=uiFixture();await fillUI(f);let focused=false;
 const replacement={dataset:{lineupUnavailable:'H10'},focus(){focused=true}};
 f.element.querySelectorAll=selector=>selector==='[data-lineup-unavailable]'?[replacement]:[];
 f.node('#lineupUnavailable').onchange({target:{dataset:{lineupUnavailable:'H10'},checked:true}});
 assert.equal(focused,true);const saved=JSON.parse(f.values.get('cpbl-lineup-2025-v1:A'));assert.deepEqual(saved.draft.unavailable,['H10']);
});

test('Escape cancels the player picker without changing the draft and respects composition',async()=>{
 const f=uiFixture();await fillUI(f);const before=JSON.parse(f.values.get('cpbl-lineup-2025-v1:A')).draft;
 f.listeners.click({target:{closest:s=>s==='[data-pick]'?{dataset:{pick:'0'}}:null}});
 assert.equal(f.node('#lineupPicker').open,true);let prevented=false;
 f.node('#lineupPicker').dispatch('keydown',{key:'Escape',isComposing:true,preventDefault(){throw Error('must preserve IME')}});assert.equal(f.node('#lineupPicker').open,true);
 f.node('#lineupPicker').dispatch('keydown',{key:'Escape',isComposing:false,preventDefault(){prevented=true}});
 assert.equal(f.node('#lineupPicker').open,false);assert.equal(prevented,true);assert.deepEqual(JSON.parse(f.values.get('cpbl-lineup-2025-v1:A')).draft,before);
});
