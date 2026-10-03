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

test('missing personal pitch mix never displays league fallback percentages as pitcher usage',()=>{
  const f=fixture();f.context.result={situation:{pitcher:'No pitches'},pitch_mix:{R:{n:0,cells:{速球高中:.5}},L:{n:0,cells:{速球高中:.5}}}};
  const html=f.eval('mixCard(result)');
  assert.match(html,/不展示聯盟回退配球/);
  assert.doesNotMatch(html,/50%|mix-bar/);
});

test('comparison chart shares a zero baseline and never magnifies tiny improvements',()=>{
  const f=fixture();f.context.current={球員:'Current'};f.context.choices=[{球員:'One',守備:'ok',相對現任:.001},{球員:'Two',守備:'bad',相對現任:-.5}];
  const html=f.eval('candidateChart(current,choices,false)');
  assert.match(html,/共同刻度 ±1.0/);assert.match(html,/\+0.0010/);assert.match(html,/差距極小/);
  assert.match(html,/守備受限/);assert.match(html,/left:25%;width:25%/);
  assert.doesNotMatch(html,/NaN|undefined/);
});

test('defense chart uses defending-team win delta without reversing the sign again',()=>{
  const f=fixture();f.context.current={投手:'Current'};f.context.choices=[{投手:'Better',守方勝率增減:2},{投手:'Worse',守方勝率增減:-1}];
  const html=f.eval('candidateChart(current,choices,true)');
  assert.match(html,/守方/);assert.match(html,/共同刻度 ±2.0/);
  assert.match(html,/left:50%;width:50%/);assert.match(html,/left:25%;width:25%/);
  assert.match(html,/不是贏球機率/);
  assert.equal(f.eval('candidateChart(current,[],true)'), '');
});

test('editing a custom situation invalidates an in-flight result before it can arrive',async()=>{
  const f=fixture(),a=deferred();f.context.a=a.promise;f.eval('S.ready=true;renderResult=()=>{};');
  const pending=f.eval("run(()=>a,'offense')");
  f.eval("invalidateCustom({target:{id:'myScore'}})");
  a.resolve({id:'obsolete'});await pending;
  assert.equal(f.eval('S.last'),null);assert.equal(f.node('#resultBody').innerHTML,'');
  assert.equal(f.node('#evalBtn').disabled,false);
});

test('searching the bench and theme-independent replay controls do not invalidate a result',()=>{
  const f=fixture();f.eval("S.last={id:'saved'};invalidateCustom({target:{id:'benchFilter'}})");
  assert.equal(f.eval('S.last.id'),'saved');
  f.eval("S.mode='replay';invalidateCustom({target:{id:'myScore'}})");
  assert.equal(f.eval('S.last.id'),'saved');
});

test('invalid submit removes the previous recommendation without making a request',async()=>{
  const f=fixture();f.node('#myScore').value='-1';f.node('#myScore').checkValidity=()=>false;
  f.eval("S.ready=true;S.last={id:'old'};api=()=>{throw Error('request should not run');};");
  await f.eval('evaluateCustom()');
  assert.equal(f.eval('S.last'),null);assert.equal(f.node('#resultBody').innerHTML,'');
  assert.match(f.node('#formError').innerHTML,/非負整數/);
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

test('tiny positive differences never become a strong recommendation from SE',()=>{
  const f=fixture();f.context.cands=[{角色:'現任',球員:'Current',預估勝率:0,誤差:0,階層式:0,機器學習:0,樣本球數:1000},
    {角色:'代打',球員:'One',守備:'ok',預估勝率:.00001,誤差:0,階層式:.00001,機器學習:.00001,樣本球數:1000}];
  const rec=f.eval('recommendation(cands)');
  assert.equal(rec.kind,'neutral');assert.match(rec.text,/不能只依排序認定必須換人/);
  assert.match(rec.title,/差距小於顯示精度/);assert.match(rec.text,/並非統計上的相等/);
});

test('a high predicted value never bypasses personal sample qualification',()=>{
  const f=fixture();f.context.cands=[{角色:'現任',球員:'Current',預估勝率:0},
    {角色:'代打',球員:'Thin',預估勝率:99,守備:'ok',可列入排名:false}];
  const rec=f.eval('recommendation(cands)');
  assert.match(rec.title,/沒有達門檻/);assert.equal(rec.best,undefined);
  f.context.cands[0]['可列入排名']=false;f.context.cands[0]['樣本資格說明']='99 打席';
  assert.match(f.eval('recommendation(cands).title'),/個人資料不足/);
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

test('ambiguous player identity also blocks observational pitch charts',()=>{
  const f=fixture();f.eval("S.last={ambiguous_players:['Shared'],situation:{pitcher:'Shared'}};mountPitchChange('Shared');");
  assert.equal(f.context.lastMount,undefined);
  assert.match(f.node('#pitchChange').innerHTML,/避免混入另一位球員/);
  assert.match(f.eval('mixCard(S.last)'),/不展示合併球路/);
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
