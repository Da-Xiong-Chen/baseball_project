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

test('pitch arsenal preserves exported ratios, sorts groups, and never presents missing personal mix',()=>{
  const f=fixture(); f.context.result={situation:{pitcher:'P'},pitch_mix:{R:{n:10,cells:{速球高中:.3,速球低:.2,滑卡低:.4,曲球低:.1}},L:{n:0,cells:{速球高中:1}}}};
  const html=f.eval('mixCard(result)');
  assert.equal((html.match(/class="arsenal-pitch"/g)||[]).length,4);
  assert.match(html,/50.0/);assert.match(html,/40.0/);
  assert.ok(html.indexOf('<h3>速球')<html.indexOf('<h3>滑卡'));
  assert.match(html,/此側沒有可用個人逐球紀錄/);
  assert.doesNotMatch(html,/100.0|九宮格|內角|外角|球速/);
});

test('official profile uses unique validated ID and searches when name is ambiguous',()=>{
  const f=fixture();f.eval("officialPlayers={'鋼龍':['0000006497'],'同名':['0000000001','0000000002']};");
  assert.match(f.eval("officialPlayerLink('鋼龍')"),/person\?acnt=0000006497/);
  assert.match(f.eval("officialPlayerLink('同名')"),/players\?playerName=/);
  assert.match(f.eval("officialPlayerLink('未知')"),/noopener noreferrer/);
});

test('automatic detail does not collapse the initial two-candidate comparison',async()=>{
  const f=fixture();f.node('#candidateCompare').innerHTML='both selected candidates';
  f.eval("S.last={view:'offense',model_cutoff:'2026-01-01'};mountPitchChange=()=>{};api=async()=>{throw Error('controlled missing detail');};");
  await f.eval("showDetail('One','Pitcher',null,false)");
  assert.equal(f.node('#candidateCompare').innerHTML,'both selected candidates');
});

test('comparison keeps both candidates initially and explains model disagreement',()=>{
  const f=fixture();const base={角色:'現任',球員:'Current',階層式:0,機器學習:0,樣本球數:1000,本身能力:0,球路適性:0,左右優勢:0};
  f.context.result={candidates:[base,{...base,角色:'代打',球員:'One',階層式:.02,機器學習:-.01,相對現任:.2},
    {...base,角色:'代打',球員:'Two',階層式:.01,機器學習:.01,相對現任:.1}]};
  const html=f.eval("comparisonPanel(result,null,'ph')");
  assert.equal((html.match(/<article/g)||[]).length,2);
  assert.match(html,/模型意見不同，難以區分/);assert.match(html,/排序尚未校準/);
  const selected=f.eval("comparisonPanel(result,'Two','ph')");
  assert.equal((selected.match(/<article/g)||[]).length,1);assert.match(selected,/<h3>Two/);
});

test('candidate chart preserves direction and a common scale when selection changes',()=>{
  const f=fixture(),base={角色:'現任',球員:'Current',階層式:0,機器學習:0,樣本球數:1000,本身能力:0,球路適性:0,左右優勢:0};
  f.context.result={candidates:[base,{...base,角色:'代打',球員:'Positive',相對現任:.2},
    {...base,角色:'代打',球員:'Negative',相對現任:-.1}]};
  const both=f.eval("comparisonPanel(result,null,'ph')");
  assert.match(both,/class="positive" style="left:50%;width:48%"/);
  assert.match(both,/class="negative" style="left:26%;width:24%"/);
  assert.match(both,/現任 0/);assert.match(both,/百分點/);
  assert.match(f.eval("comparisonPanel(result,'Negative','ph')"),/left:26%;width:24%/);
});

test('tiny positive differences never become a strong recommendation from SE',()=>{
  const f=fixture();f.context.cands=[{角色:'現任',球員:'Current',預估勝率:0,誤差:0,階層式:0,機器學習:0,樣本球數:1000},
    {角色:'代打',球員:'One',守備:'ok',預估勝率:.00001,誤差:0,階層式:.00001,機器學習:.00001,樣本球數:1000}];
  const rec=f.eval('recommendation(cands)');
  assert.equal(rec.kind,'neutral');assert.match(rec.text,/不能只依排序認定必須換人/);
  assert.match(rec.title,/差距小於顯示精度/);assert.match(rec.text,/並非統計上的相等/);
});

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
