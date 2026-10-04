const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function fixture() {
  const nodes = new Map();
  const node = key => {
    if (!nodes.has(key)) nodes.set(key, {value:'', innerHTML:'', disabled:false, options:[],
      classList:{add(){},remove(){},toggle(){}}, querySelector:()=>({}), querySelectorAll:()=>[], focus(){}, setAttribute(){}, removeAttribute(){}, checkValidity:()=>true});
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

test('both modes keep the latest four candidates, evict oldest at five and isolate results',()=>{
  const f=fixture();
  f.context.result={candidates:[{角色:'現任',球員:'Current'},...['A','B','C','D','E'].map(球員=>({角色:'代打',球員}))],bullpen:{rows:[{角色:'場上',投手:'Pitcher'},...['V','W','X','Y','Z'].map(投手=>({角色:'牛棚',投手}))]}};
  for(const [tab,initial,last] of [['ph',['A','B','C','D'],'E'],['pen',['V','W','X','Y'],'Z']]) {
    assert.equal(f.eval(`[...comparisonNames(result,'${tab}')].join(',')`),initial.join(','));
    assert.equal(f.eval(`setComparisonName(result,'${tab}','${initial[0]}',true)`),true);
    assert.equal(f.eval(`[...comparisonNames(result,'${tab}')].join(',')`),initial.join(','));
    assert.equal(f.eval(`setComparisonName(result,'${tab}','${last}',true)`),true);
    assert.equal(f.eval(`[...comparisonNames(result,'${tab}')].join(',')`),[...initial.slice(1),last].join(','));
    assert.equal(f.eval(`comparisonNames(result,'${tab}').size`),4);
    for(const name of [...initial.slice(1),last]) f.eval(`setComparisonName(result,'${tab}','${name}',false)`);
    assert.equal(f.eval(`comparisonNames(result,'${tab}').size`),0);
  }
  assert.equal(f.eval('setComparisonName(result,"ph","Current",true)'),false);
  assert.equal(f.eval('setComparisonName(result,"pen","Pitcher",true)'),false);
  assert.equal(f.eval('comparisonNames({...result},"ph").size'),4);
});

test('manual detail browsing never replaces the independent comparison panel',async()=>{
  const f=fixture();f.node('#candidateCompare').innerHTML='two independently chosen candidates';
  f.eval("S.last={view:'offense',model_cutoff:'2026-01-01'};mountPitchChange=()=>{};api=async()=>{throw Error('missing detail');};");
  await f.eval("showDetail('Other','Pitcher',null)");
  assert.equal(f.node('#candidateCompare').innerHTML,'two independently chosen candidates');
});

test('position-group selection clears evaluation even when rendering removes its button',()=>{
  const f=fixture();f.node('#customPanel').addEventListener=()=>{};
  f.eval('bindStatic();S.last={id:"old"};S.bench=new Set();renderBench=()=>{};');
  f.node('#benchList').onclick({target:{closest:()=>({dataset:{group:'One|Two'}})}});
  assert.equal(f.eval('S.last'),null);
  assert.equal(f.eval('S.bench.has("One")&&S.bench.has("Two")'),true);
});

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

test('editing the situation invalidates a pending request while bench search preserves it',async()=>{
  const f=fixture();const pending=deferred();f.context.pending=pending.promise;
  f.eval('S.ready=true;renderResult=()=>{};');
  const job=f.eval("run(()=>pending,'offense')");
  f.node('#myScore').value='4';f.eval("invalidateCustom({target:{id:'myScore'}})");
  pending.resolve({id:'stale'});await job;
  assert.equal(f.eval('S.last'),null);
  f.eval("S.last={id:'saved'};invalidateCustom({target:{id:'benchFilter'}})");
  assert.equal(f.eval('S.last.id'),'saved');
});

test('invalid submit clears the old result without evaluating',async()=>{
  const f=fixture();f.eval("S.ready=true;S.last={id:'old'};api=()=>{throw Error('must not evaluate');}");
  f.node('#myScore').value='';await f.eval('evaluateCustom()');
  assert.equal(f.eval('S.last'),null);assert.match(f.node('#formError').innerHTML,/非負整數/);
});

test('score steppers support typing, zero floor and stale-result invalidation',()=>{
  const f=fixture();f.node('#myScore').value='2';f.eval("S.last={id:'old'};stepScore('myScore',1)");
  assert.equal(f.node('#myScore').value,'3');assert.equal(f.eval('S.last'),null);
  f.node('#myScore').value='0';f.eval("stepScore('myScore',-1)");assert.equal(f.node('#myScore').value,'0');
  f.node('#myScore').value='';f.eval("stepScore('myScore',1)");assert.equal(f.node('#myScore').value,'1');
  f.node('#myScore').value='2.5';f.eval("stepScore('myScore',1)");assert.equal(f.node('#myScore').value,'2.5');
  assert.match(f.node('#formError').innerHTML,/非負整數/);
});

test('comparison keeps both candidates initially and explains model disagreement',()=>{
  const f=fixture();const base={角色:'現任',球員:'Current',階層式:0,機器學習:0,樣本球數:1000,本身能力:0,球路適性:0,左右優勢:0};
  f.context.result={candidates:[base,{...base,角色:'代打',球員:'One',階層式:.02,機器學習:-.01,相對現任:.2},
    {...base,角色:'代打',球員:'Two',階層式:.01,機器學習:.01,相對現任:.1}]};
  const html=f.eval("comparisonPanel(result,null,'ph')");
  assert.equal((html.match(/<article/g)||[]).length,2);
  assert.match(html,/模型分歧/);assert.doesNotMatch(html,/排序僅供參考/);
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
  assert.match(rec.title,/差距極小/);assert.match(rec.text,/並非統計上的相等/);
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
  assert.match(f.node('#detail').innerHTML,/未提供或載入失敗/);assert.match(f.node('#pitchArsenal').innerHTML,/NEW/);
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

test('team choices disable the opposing team and recover duplicate selections',()=>{
  const f=fixture();f.eval("S.teams=['A','B','C'];");
  const mine=f.node('#myTeam'),opp=f.node('#oppTeam');
  mine.options=['A','B','C'].map(value=>({value}));
  opp.options=['A','B','C'].map(value=>({value}));
  mine.value='A';opp.value='B';f.eval('syncTeamChoices()');
  assert.equal(mine.options[1].disabled,true);assert.equal(opp.options[0].disabled,true);
  opp.value='A';f.eval("syncTeamChoices('oppTeam')");
  assert.equal(opp.value,'A');assert.equal(mine.value,'B');
  assert.equal(mine.options[0].disabled,true);
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

test('extra inning selection presets only second base and never changes outs',()=>{
 const f=fixture();f.eval('renderState=()=>{};S.mode="custom";S.inning=9;S.bases=5;S.outs=2;changeInning(1);');
 assert.equal(f.eval('S.inning'),10);assert.equal(f.eval('S.bases'),2);assert.equal(f.eval('S.outs'),2);
 f.eval('S.inning=12;S.bases=0;changeInning(1);');assert.equal(f.eval('S.bases'),0);
 f.eval('changeInning(-1)');assert.equal(f.eval('S.bases'),2);
 f.eval('S.mode="replay";S.inning=9;S.bases=4;changeInning(1);');assert.equal(f.eval('S.bases'),4);
});
test('same effective input and group editing retain the result; changed input invalidates it',()=>{
 const f=fixture();f.eval('S.last={id:"result"};resultInputKey=evaluationKey();');
 f.eval('invalidateCustom({target:{closest:()=>({})}})');assert.equal(f.eval('S.last.id'),'result');
 f.eval('invalidateCustom({target:{id:"innUp"}})');assert.equal(f.eval('S.last.id'),'result');
 f.eval('S.bases=4;invalidateCustom({target:{id:"baseControls"}})');assert.equal(f.eval('S.last'),null);
});
test('unknown fielding stays visible in a collapsed DH group without inventing eligibility',()=>{
 const f=fixture();f.node('#myTeam').value='A';f.node('#dueBatter').value='Due';
 f.eval('S.roster.A={hitters:[{name:"Due",positions:{}},{name:"Unknown",positions:{},pa:5}]};S.bench=new Set(["Unknown"]);renderBench();');
 const html=f.node('#benchList').innerHTML;assert.match(html,/守位未收錄/);assert.match(html,/指定打擊/);assert.match(html,/aria-expanded="false"/);assert.equal((html.match(/class="bench-group"/g)||[]).length,4);
});

test('ended home and extra-inning away situations do not request an evaluation',async()=>{
 for(const [view,half,inning,mine,opponent] of [['offense','home',9,4,3],['defense','home',10,2,3],['offense','away',10,2,3]]) {
  const f=fixture();f.node('#myScore').value=String(mine);f.node('#oppScore').value=String(opponent);f.node('#pitchCount').value='10';f.node('#myTeam').value='A';f.node('#oppTeam').value='B';
  f.eval(`S.ready=true;S.view='${view}';S.half='${half}';S.inning=${inning};api=()=>{throw Error('must not evaluate ended game')}`);
  await f.eval('evaluateCustom()');assert.match(f.node('#formError').innerHTML,/比賽已結束/);assert.equal(f.eval('S.last'),null);
 }
});
test('per-batter chart preserves signed values and ignores missing values',()=>{
 const f=fixture();f.context.details=[{batter:'A',runs:.1,fatigue:.02},{batter:'B',runs:-.03,fatigue:0},{batter:'Missing',runs:NaN,fatigue:0}];
 const html=f.eval('pitcherMatchupChart(details)');assert.match(html,/\+0.120/);assert.match(html,/−0.030/);assert.doesNotMatch(html,/Missing|NaN/);assert.match(html,/非實際失分/);
});

test('per-batter chart retains a shared candidate scale',()=>{
 const f=fixture();f.context.details=[{batter:'A',runs:.1,fatigue:0}];
 assert.match(f.eval('pitcherMatchupChart(details,.2,[{batter:"A",runs:0,fatigue:0}])'),/width:24%/);
 assert.match(f.eval('pitcherMatchupChart(details,.2)'),/共用尺度/);
});

test('per-batter baseline matches batter identity, includes fatigue and does not invent missing data',()=>{
 const f=fixture();f.context.details=[{batter:'A',runs:.1,fatigue:0},{batter:'B',runs:-.1,fatigue:0}];
 f.context.baseline=[{batter:'Other',runs:9,fatigue:0},{batter:'A',runs:.15,fatigue:.05}];
 const html=f.eval('pitcherMatchupChart(details,.2,baseline)');
 assert.match(html,/left:50%;width:24%/);assert.match(html,/現任 \+0.200/);assert.match(html,/現任資料不足/);assert.doesNotMatch(html,/class="matchup-baseline"/);
});
test('hitter decomposition is collapsed while the fielding warning remains visible',()=>{
 const f=fixture(),base={角色:'現任',球員:'Current',階層式:0,機器學習:0,樣本球數:1000,本身能力:0,球路適性:0,左右優勢:0};
 f.context.result={candidates:[base,{...base,角色:'代打',球員:'One',相對現任:.2,守備說明:'需確認捕手'}]};
 const html=f.eval('comparisonPanel(result,null,"ph")');
 assert.ok(html.indexOf('需確認捕手')<html.indexOf('<details>'));
 assert.ok(html.indexOf('class="compare-values"')>html.indexOf('<details>'));
 assert.doesNotMatch(html,/<details open/);
});

test('bench summary counts all selected names regardless of search and excludes current batter',()=>{
 const f=fixture();f.node('#myTeam').value='A';f.node('#dueBatter').value='Due';f.node('#benchFilter').value='One';
 f.eval('S.roster.A={hitters:[{name:"Due",positions:{}},{name:"One",positions:{}},{name:"Two",positions:{}}]};S.bench=new Set(["Due","One","Two"]);renderBench();');
 const html=f.node('#benchAvailability').innerHTML;assert.match(html,/今日勾選 2 人/);assert.match(html,/One/);assert.match(html,/Two/);assert.doesNotMatch(html,/>Due</);
});
test('pitching colors compare with current pitcher rather than the sign of run value',()=>{
 const f=fixture();f.context.details=[{batter:'A',runs:-.01,fatigue:0},{batter:'B',runs:.01,fatigue:0}];f.context.current=[{batter:'A',runs:-.03,fatigue:0},{batter:'B',runs:.03,fatigue:0}];
 const html=f.eval('pitcherMatchupChart(details,.1,current)');assert.match(html,/<i class="unfavorable" style="left:40.4%/);assert.match(html,/<i class="favorable" style="left:50%/);
 assert.match(f.eval('pitcherMatchupChart(details,.1,[])'),/現任資料不足/);
});
test('availability preview keeps all names in an optional disclosure and escapes them',()=>{
 const f=fixture();f.context.names=['A','B','C','D','<E>','F'];
 const html=f.eval('availabilityNames(names,"續打")');
 assert.match(html,/另 2 人/);assert.ok(html.indexOf('>D<')<html.indexOf('<details'));
 assert.ok(html.indexOf('&lt;E&gt;')>html.indexOf('<details'));assert.doesNotMatch(html,/<details[^>]* open/);
 assert.match(f.eval('availabilityNames(names,"續打",true)'),/<details[^>]* open/);
 assert.match(f.eval('availabilityNames([],"續打")'),/僅比較續打/);
});
test('pitcher comparison keeps fatigue warning visible and collapses per-batter charts',()=>{
 const f=fixture(),base={角色:'場上',投手:'Current',階層式:0,機器學習:0,樣本球數:1000,預估失分:.2,對決明細:[{batter:'A',runs:.2,fatigue:0}]};
 f.context.result={bullpen:{next:['A'],rows:[base,{...base,角色:'牛棚',投手:'One',守方勝率增減:.1,疲勞:'球數偏高'}]}};
 const html=f.eval('comparisonPanel(result,null,"pen")');
 assert.ok(html.indexOf('球數偏高')<html.indexOf('<details>'));
 assert.ok(html.indexOf('class="next-matchup-chart benefit-chart"')>html.indexOf('<details>'));
 assert.doesNotMatch(html,/<details open/);assert.match(html,/查看差距拆解/);
});
test('mobile row details preserve sample and fatigue-adjusted value without inventing another score',()=>{
 const f=fixture();f.context.row={樣本球數:321,預估失分:-.023,疲勞調整:.012,可信度:'低'};
 const html=f.eval('mobileRowDetails(row,true)');
 assert.match(html,/321 球/);assert.match(html,/失分價值 -0.023 分/);assert.match(html,/含疲勞 \+0.012/);
 assert.doesNotMatch(html,/<details[^>]* open|NaN|undefined/);
 assert.match(f.eval('mobileRowDetails(row,false)'),/321 球 · 低樣本/);
});
test('hitter source chart compares actual values to current with a shared scale and missing components',()=>{
 const f=fixture();f.context.current={本身能力:.1,球路適性:.05};
 f.context.one={本身能力:.2,球路適性:.025};f.context.two={本身能力:.3,球路適性:.05};
 const html=f.eval('hitterComponentChart(one,current,[current,one,two])');
 assert.match(html,/class="favorable" style="left:50%;width:24/);
 assert.match(html,/class="unfavorable"/);assert.match(html,/−0.025/);assert.match(html,/現任 \+0.050/);assert.match(html,/資料不足/);
 assert.match(html,/僅拆解階層式估計/);assert.doesNotMatch(html,/NaN|undefined/);
});
test('compact fielding message retains replacement person, position and extra bench cost',()=>{
 const f=fixture();assert.equal(f.eval('compactFielding("需由 李勛傑 接守左外野（再消耗 1 名板凳）")'),'接守：李勛傑 · 左外野（另需 1 人）');
 assert.equal(f.eval('compactFielding("換下後板凳無人可守捕手")'),'無人接守捕手');
 assert.equal(f.eval('compactFielding("資格待確認")'),'資格待確認');
});
test('short assessment notes keep distinct cutoffs, missing metadata and historical roster uncertainty',()=>{
 const f=fixture();f.context.result={view:'replay',method:'集成',model_cutoff:'2025-07-01',ml_cutoff:'2025-06-01'};
 const html=f.eval('assessmentNotes(result)');
 assert.match(html,/2025-07-01/);assert.match(html,/2025-06-01/);assert.match(html,/不含截止日/);
 assert.match(html,/歷史名單與守位可能為推估/);assert.match(html,/不是完整預測區間/);
 assert.match(f.eval('assessmentNotes({})'),/逐球資料截止：未記錄/);
 assert.match(f.eval('assessmentNotes({method:"階層式"})'),/逐球資料截止：未使用/);
 const same=f.eval('assessmentNotes({model_cutoff:"2025-07-01",ml_cutoff:"2025-07-01"})');
 assert.equal((same.match(/2025-07-01/g)||[]).length,1);assert.match(same,/今日名單需人工確認/);
});
test('shared comparison uses opposite benefit directions but identical baseline markup',()=>{
 const f=fixture();f.context.data=[{name:'A',value:-.05,base:-.1},{name:'B',value:.05,base:.1},{name:'C',value:.02}];
 const batting=f.eval('valueComparisonChart(data,.1,"test",true,"")');
 const pitching=f.eval('valueComparisonChart(data,.1,"test",false,"")');
 assert.match(batting,/<i class="favorable" style="left:50%;width:24%/);
 assert.match(pitching,/<i class="unfavorable" style="left:26%;width:24%/);
 for(const html of [batting,pitching]){assert.doesNotMatch(html,/class="matchup-baseline"/);assert.match(html,/現任資料不足/);assert.match(html,/原始數值/);assert.match(html,/現任 0/);}
});
test('difference chart distinguishes equal, tiny and missing comparisons and never plots a missing baseline',()=>{
 const f=fixture();f.context.data=[{name:'Equal',value:.1,base:.1},{name:'Tiny',value:.10001,base:.1},{name:'Unknown',value:.1},{name:'Absent',base:.1}];
 const html=f.eval('valueComparisonChart(data,.1,"test",true,"")');
 assert.match(html,/相同/);assert.match(html,/差距極小/);assert.match(html,/現任資料不足/);assert.match(html,/資料不足/);
 assert.equal((html.match(/<i class=/g)||[]).length,2);assert.doesNotMatch(html,/NaN|undefined/);
});
test('fifth selection reports the actual evicted candidate and isolates feedback between offense and defense',()=>{
 const f=fixture();f.context.result={candidates:[{角色:'現任',球員:'Current'},...['A','B','C','D','E'].map(球員=>({角色:'代打',球員}))],bullpen:{rows:[{角色:'場上',投手:'P'},...['V','W','X','Y','Z'].map(投手=>({角色:'牛棚',投手}))]}};
 f.eval('comparisonNames(result,"ph");setComparisonName(result,"ph","E",true)');
 assert.match(f.eval('comparisonNotices.get(result).get("ph").message'),/已加入 E，移除最早選取的 A/);
 assert.equal(f.eval('comparisonNotices.get(result).has("pen")'),false);
 f.eval('comparisonNames(result,"pen");setComparisonName(result,"pen","Z",true)');
 assert.match(f.eval('comparisonNotices.get(result).get("pen").message'),/移除最早選取的 V/);
 assert.match(f.eval('comparisonNotices.get(result).get("ph").message'),/移除最早選取的 A/);
});


test('bullpen search filters visible names without modifying checked selection',()=>{
 const f=fixture(),labels=['One','Two','Current'].map((name,i)=>({hidden:false,input:{value:name,checked:i<2},querySelector(){return this.input;}}));
 f.context.document.querySelectorAll=selector=>selector==='#penList label'?labels:[];
 f.node('#penList').hidden=true;f.node('#penFilter').value='One';
 f.eval('renderPenVisibility(true)');
 assert.deepEqual(labels.map(x=>x.hidden),[false,true,true]);assert.equal(f.node('#penList').hidden,false);
 assert.deepEqual(labels.map(x=>x.input.checked),[true,true,false]);
 f.node('#penFilter').value='Absent';f.eval('renderPenVisibility(true)');
 assert.equal(f.node('#penToggleAll').disabled,true);assert.match(f.node('#penSearchStatus').textContent,/搜尋不會清除/);
 f.node('#penFilter').value='';f.eval('renderPenVisibility(true)');
 assert.deepEqual(labels.map(x=>x.hidden),[false,false,false]);assert.equal(f.node('#penToggleAll').disabled,false);
});

test('both roster searches retain completed and pending evaluation state',()=>{
 const f=fixture();f.eval('S.mode="custom";S.last={kept:true};');
 for(const id of ['benchFilter','penFilter']){f.context.event={target:{id}};f.eval('invalidateCustom(event)');assert.equal(f.eval('S.last.kept'),true);}
});

test('hitter primary assessment uses incumbent difference and preserves league value in disclosure',()=>{
 const f=fixture();f.context.result={situation:{pitcher:'P'},candidates:[{角色:'現任',球員:'A',相對現任:0,預估勝率:-.5,樣本球數:200,可信度:"中",價值分數:50,守備:'ok',守備說明:'目前守捕手'},{角色:'代打',球員:'B',相對現任:.2,預估勝率:-.3,樣本球數:100,可信度:"低",價值分數:60,守備:'ok',守備說明:'可接守捕手'}]};
 const html=f.eval('phTable(result)');
 assert.match(html,/勝率變化（相對現任）/);assert.match(html,/相對聯盟平均/);
 const values=[...html.matchAll(/<td class="evaluation-value">([\s\S]*?)<\/td>/g)].map(m=>m[1]);
 assert.match(values[0],/基準/);assert.match(values[1],/\+0.20 百分點/);assert.doesNotMatch(values.join(''),/−0.30|−0.50/);
});
