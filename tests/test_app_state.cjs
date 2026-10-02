const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function fixture() {
  const nodes = new Map();
  const node = key => {
    if (!nodes.has(key)) nodes.set(key, {value:'', innerHTML:'', disabled:false,
      classList:{add(){},remove(){},toggle(){}}, querySelector:()=>({}), focus(){}, setAttribute(){}, removeAttribute(){}, checkValidity:()=>true});
    return nodes.get(key);
  };
  const context = {document:{querySelector:node,querySelectorAll:()=>[]}, location:{href:'http://localhost/'}, console, URL, URLSearchParams, AbortSignal,
    window:{matchMedia:()=>({matches:false}),scrollTo(){}}, Engine:{model:()=>({}), detail:()=>{throw Error('unsafe fallback');}},
    PitchChange:{mount:o=>context.lastMount=o,staticResult:()=>{}},fetch:async()=>({ok:true,json:async()=>({})})};
  let code = fs.readFileSync(path.join(__dirname,'../docs/app.js'),'utf8');
  code = code.slice(0,code.lastIndexOf('init().catch'));
  vm.createContext(context); vm.runInContext(code,context);
  return {context,node,eval:s=>vm.runInContext(s,context)};
}
const deferred = ()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};

test('API and static reads work without the newer timeout API',async()=>{
  const f=fixture();f.context.AbortSignal={};
  assert.equal(f.eval('Object.keys(timeoutOptions(100)).length'),0);
  await f.eval("api('api/meta')");
  await f.eval("json('data/example.json')");
});

test('mobile result navigation respects reduced-motion preference',async()=>{
  for (const reduced of [false,true]) {
    const f=fixture();let scroll;
    f.context.window.matchMedia=q=>({matches:q.includes('max-width')||reduced});
    f.node('#result').scrollIntoView=o=>{scroll=o.behavior;};
    f.eval('renderResult=()=>{};S.ready=true;');
    await f.eval("run(async()=>({id:'new'}),'offense')");
    assert.equal(scroll,reduced?'auto':'smooth');
  }
});

test('search preserves hidden selections and never treats InputEvent as reset',()=>{
  const f=fixture(); f.node('#myTeam').value='A'; f.node('#dueBatter').value='Due';
  f.eval("S.roster.A={hitters:[{name:'Due',positions:{}},{name:'One',positions:{}},{name:'Two',positions:{}}]}; S.bench=new Set(['One']);");
  f.node('#benchFilter').value='Two'; f.eval('renderBench()');
  assert.equal(f.eval("S.bench.has('One')"),true);
  f.node('#benchFilter').value=''; f.eval('renderBench({type:"input"})');
  assert.match(f.node('#benchList').innerHTML,/value="One" checked/);
  assert.doesNotMatch(f.node('#benchList').innerHTML,/value="Two" checked/);
});

test('missing historical detail never falls back to full-season Engine',async()=>{
  const f=fixture(); f.eval("S.last={view:'replay',details:{}};");
  await assert.rejects(()=>f.eval("staticApi('api/detail?batter=X&pitcher=Y')"),/不使用全季/);
});

test('result context controls season after a mode switch',()=>{
  const f=fixture();f.eval("S.mode='replay';S.last={view:'offense',situation:{date:'2026-01-01'},model_cutoff:'2026-01-01'};mountPitchChange('P');");
  assert.equal(f.context.lastMount.season,2025);
});

test('pitcher identity switches even when detail fails',async()=>{
  const f=fixture();f.eval("S.last={view:'offense',situation:{date:'2026-01-01'},model_cutoff:'2026-01-01'};api=async()=>{throw Error('offline')};");
  await f.eval("showDetail('B','NEW')");
  assert.equal(f.context.lastMount.pitcher,'NEW');
  assert.match(f.node('#detail').innerHTML,/offline/);
});

test('slow evaluation cannot replace the latest result',async()=>{
  const f=fixture(), a=deferred(),b=deferred();f.context.a=a.promise;f.context.b=b.promise;
  f.eval('renderResult=()=>{};S.ready=true;');
  const first=f.eval("run(()=>a,'offense')"), second=f.eval("run(()=>b,'defense')");
  b.resolve({id:'B'});await second;a.resolve({id:'A'});await first;
  assert.equal(f.eval('S.last.id'),'B');assert.equal(f.node('#evalBtn').disabled,false);
});

test('mode switch invalidates a pending evaluation',async()=>{
  const f=fixture(), a=deferred();f.context.a=a.promise;f.eval('renderResult=()=>{};S.ready=true;');
  const pending=f.eval("run(()=>a,'offense')");f.eval('clearResult()');a.resolve({id:'old'});await pending;
  assert.equal(f.eval('S.last'),null);
});

test('slow game cannot replace the latest plate appearance list',async()=>{
  const f=fixture(),a=deferred(),b=deferred();f.context.a=a.promise;f.context.b=b.promise;
  f.eval("renderGames=()=>{};renderPAs=()=>{};api=p=>p.endsWith('A')?a:b;");
  const first=f.eval("loadGame('A')"),second=f.eval("loadGame('B')");
  b.resolve([{id:'B'}]);await second;a.resolve([{id:'A'}]);await first;
  assert.equal(f.eval('S.pas[0].id'),'B');
});

test('game request failure exposes a retry path',async()=>{
  const f=fixture();f.eval("renderGames=()=>{};api=async()=>{throw Error('network')};");
  await f.eval("loadGame('A')");assert.match(f.node('#paList').innerHTML,/重新載入/);
});

test('older team list response cannot replace the latest team',async()=>{
  const f=fixture(),a=deferred(),b=deferred();f.context.a=a.promise;f.context.b=b.promise;
  f.eval("renderGames=()=>{};api=p=>p.endsWith('A')?a:b;");
  f.node('#rpTeam').value='A';const first=f.eval('loadGames()');
  f.node('#rpTeam').value='B';const second=f.eval('loadGames()');
  b.resolve([{game:'B'}]);await second;a.resolve([{game:'A'}]);await first;
  assert.equal(f.eval('S.games[0].game'),'B');
});

test('slow roster response cannot reset the latest names',async()=>{
  const f=fixture(),a=deferred(),b=deferred();f.context.a=a.promise;f.context.b=b.promise;
  f.eval("team=n=>n==='A'?a:b;autoPos=()=>{};renderBench=()=>{};syncRole=()=>{};");
  f.node('#myTeam').value='A';f.node('#oppTeam').value='A';const first=f.eval('refreshCustom()');
  f.node('#myTeam').value='B';f.node('#oppTeam').value='B';const second=f.eval('refreshCustom()');
  b.resolve({pitchers:[{name:'B',role:'後援'}],hitters:[{name:'B'}]});await second;
  a.resolve({pitchers:[{name:'A',role:'後援'}],hitters:[{name:'A'}]});await first;
  assert.match(f.node('#dueBatter').innerHTML,/value="B"/);assert.doesNotMatch(f.node('#dueBatter').innerHTML,/value="A"/);
});
