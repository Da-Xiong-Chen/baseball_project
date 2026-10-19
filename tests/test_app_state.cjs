const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function fixture() {
  const nodes = new Map();
  const node = key => {
    if (!nodes.has(key)) nodes.set(key, {value:'', innerHTML:'', insertAdjacentHTML(where,s){this.innerHTML+=s;}, disabled:false, options:[],
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
  assert.equal(rec.kind,'neutral');assert.match(rec.text,/不必只依排序換人/);
  assert.match(rec.title,/差距極小/);
});

test('API and static reads work without the newer timeout API',async()=>{
  const f=fixture();f.context.AbortSignal={};
  assert.equal(f.eval('Object.keys(timeoutOptions(100)).length'),0);
  await f.eval("api('api/meta')");
  await f.eval("json('data/example.json')");
});

test('mobile result appears below the form and jumps there without smooth scrolling',async()=>{
  const f=fixture();let scroll;
  f.context.window.matchMedia=q=>({matches:q.includes('max-width')});
  f.node('#result').scrollIntoView=o=>{scroll=o;};
  f.eval('renderResult=()=>{};S.ready=true;');
  await f.eval("run(async()=>({id:'new'}),'offense')");
  assert.equal(scroll.block,'start');assert.notEqual(scroll.behavior,'smooth');
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
  assert.equal(f.context.lastMount,undefined);
  f.eval("S.last={view:'replay',situation:{date:'2025-09-20'},model_cutoff:'2025-09-20'};mountPitchChange('P');");assert.equal(f.context.lastMount.cutoff,'2025-09-20');
});

test('pitcher identity switches even when detail fails',async()=>{
  const f=fixture();f.eval("S.last={view:'offense',situation:{date:'2026-01-01'},model_cutoff:'2026-01-01'};api=async()=>{throw Error('offline')};");
  await f.eval("showDetail('B','NEW')");
  assert.equal(f.context.lastMount,undefined);
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
  b.resolve([{game:'B',date:'2025-09-20'},{game:'Future',date:'2025-09-21'}]);await second;a.resolve([{game:'A',date:'2025-09-20'}]);await first;
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
 f.eval('changeInning(-1)');assert.equal(f.eval('S.bases'),0);
 f.eval('S.inning=10;S.bases=5;changeInning(1);');assert.equal(f.eval('S.bases'),5);assert.equal(f.eval('S.outs'),2);
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
 assert.match(values[0],/基準/);assert.match(values[1].replace(/<[^>]+>/g,''),/\+0.20 百分點/);assert.doesNotMatch(values.join(''),/−0.30|−0.50/);
});


test('fielding guidance retains cover cost, catcher reserve warning and uncertain status',()=>{
 const f=fixture();f.context.row={守備:'warn',守備說明:'需由 A 接守捕手（再消耗 1 名板凳）；之後板凳已無備用捕手'};
 const html=f.eval('fieldingMessage(row)');assert.match(html,/另需接守人選/);assert.match(html,/A · 捕手（另需 1 人）/);assert.match(html,/無備用捕手/);
 assert.match(f.eval('fieldingMessage({守備:"ok",守備說明:"B 接任指定打擊"})'),/承接原 DH 棒次/);
 assert.match(f.eval('fieldingMessage({守備:"unknown",守備說明:"資格待確認"})'),/守位待確認/);
 assert.doesNotMatch(f.eval('fieldingMessage({守備:"unknown",守備說明:"資格待確認"})'),/推估可接守/);
});


test('2025 number aliases use team-specific exact strings, preserve 00, and keep names searchable',()=>{
 const f=fixture();f.eval('playerNumbers2025={A:{Zero:"0",Double:"00",One:"1",Eleven:"11"},B:{Other:"1"}}');
 for(const [name,team,q,expected] of [['One','A','1',true],['Eleven','A','1',false],['Zero','A','00',false],['Double','A','00',true],['Double','A','００',true],['One','A','#1',true],['One','A','1號',true],['Other','A','1',false],['Other','B','1',true],['Missing','A','99',false],['Missing','A','Miss',true]]) {
  assert.equal(f.eval(`matchesPlayerSearch(${JSON.stringify(name)},${JSON.stringify(team)},${JSON.stringify(q)})`),expected);
 }
 f.eval('playerNumbers2025={}');assert.equal(f.eval('matchesPlayerSearch("Name","A","Nam")'),true);assert.equal(f.eval('matchesPlayerSearch("Name","A","1")'),false);
});

test('every exported roster number searches exactly all matching 2025 team members',()=>{
 const aliases=JSON.parse(fs.readFileSync(path.join(__dirname,'../docs/data/player-numbers-2025.json'),'utf8'));
 const model=JSON.parse(fs.readFileSync(path.join(__dirname,'../docs/data/model.json'),'utf8'));
 assert.equal(aliases.season,2025);
 const f=fixture();f.context.aliases=aliases.teams;f.eval('playerNumbers2025=aliases');
 for(const [team,roster] of Object.entries(model.rosters)) {
  for(const kind of ['hitters','pitchers']) {
   const players=roster[kind];
   for(const player of players) {
    const number=aliases.teams[team][player.name];assert.match(number,/^[0-9]+$/);
    const expected=players.filter(p=>aliases.teams[team][p.name]===number).map(p=>p.name);
    f.context.players=players;f.context.team=team;f.context.number=number;
    const actual=f.eval('players.filter(p=>matchesPlayerSearch(p.name,team,number)).map(p=>p.name)');
    assert.deepEqual(Array.from(actual),expected);
   }
  }
 }
});

test('confirmed own lineup excludes field players and pitcher from bench without affecting reserves',()=>{
 const f=fixture();f.context.LineupBoard={current:()=>({slots:[{name:'Starter1',pos:'C'},{name:'Starter2',pos:'DH'}],pitcher:'P'}),validate:()=>[],unavailable:()=>['Retired']};
 f.node('#myTeam').value='A';f.eval("S.roster.A={hitters:[],pitchers:[]};audienceMode='team'");
 assert.equal(f.eval('benchEligible("Starter1")'),false);assert.equal(f.eval('benchEligible("Starter2")'),false);assert.equal(f.eval('benchEligible("Retired")'),true);assert.equal(f.eval('benchEligible("Reserve")'),true);
 assert.equal(f.eval('benchEligible("P")'),false);
});
test('invalid saved lineup cannot restrict manual evaluation',()=>{
 const f=fixture();f.context.LineupBoard={current:()=>({slots:[]}),validate:()=>['invalid'],unavailable:()=>[]};f.node('#myTeam').value='A';f.eval('S.roster.A={hitters:[],pitchers:[]}');assert.equal(f.eval('ownLineup()'),null);assert.equal(f.eval('benchEligible("Reserve")'),true);
});
test('season review verdict is plain language and divergent list links each plate appearance',()=>{
  const f=fixture();
  const sig={stay_diff_ci:[0.017,0.068]},none={stay_diff_ci:[-0.06,0.039]};
  assert.equal(f.eval(`timingVerdict(${JSON.stringify(sig)},true).ok`),true);
  assert.match(f.eval(`timingVerdict(${JSON.stringify(sig)},true).text`),/全聯盟回測：.*平均失分價值較高/);
  assert.equal(f.eval(`timingVerdict(${JSON.stringify(none)},false).ok`),false);
  assert.match(f.eval(`timingVerdict(${JSON.stringify(none)},false).text`),/僅供參考/);
  assert.match(f.eval('timingVerdict({},true).text'),/樣本不足/);
  const items=[{pa:'2025-001-a030',date:'2025-07-29',inning:8,half:'home',opp:'B<隊>',who:'甲',best:'乙',gain:8.92,outs:1,bases:3,bat_score:0,fld_score:0,result:'FO'}];
  const html=f.eval(`divergentList(${JSON.stringify(items)},'pen')`);
  assert.match(html,/data-review-pa="2025-001-a030"/);assert.match(html,/8 局下/);assert.match(html,/甲<\/b> 續投 → 建議換上 <b>乙/);
  assert.match(html,/B&lt;隊&gt;/);assert.doesNotMatch(html,/B<隊>/);
  assert.match(f.eval("divergentList([],'ph')"),/沒有系統建議換人/);
  assert.deepEqual(JSON.parse(f.eval('JSON.stringify(PAGES)')),['evaluation','lineup','review']);
});
test('default pitch count follows the inning for starters and stays 15 for relievers',()=>{
  const f=fixture();
  const pc=(starter,inning)=>f.eval(`S.starter=${starter};S.inning=${inning};defaultPitchCount()`);
  assert.equal(pc(true,1),0);assert.equal(pc(true,7),90);assert.equal(pc(true,12),105);assert.equal(pc(false,1),15);assert.equal(pc(false,9),15);
});

test('general audience ignores saved lineup without deleting team configuration',()=>{const f=fixture();f.context.LineupBoard={current:()=>({slots:[{name:'Starter',pos:'C'}],pitcher:'P'}),validate:()=>[]};f.node('#myTeam').value='A';f.eval('S.roster.A={hitters:[],pitchers:[]}');assert.equal(f.eval('ownLineup()'),null);assert.equal(f.eval('benchEligible("Starter")'),true);assert.ok(f.eval('confirmedOwnLineup()'));f.eval("audienceMode='team'");assert.equal(f.eval('benchEligible("Starter")'),false);});
test('team audience blocks evaluation without confirmed lineup before requesting scores',async()=>{const f=fixture();f.eval("S.ready=true;audienceMode='team';showFeaturePage=async p=>{window.targetPage=p};api=()=>{throw Error('must not evaluate')}");await f.eval('evaluateCustom()');assert.equal(f.context.window.targetPage,'lineup');assert.match(f.node('#formError').innerHTML,/先完成並套用/);});

test('historical fatigue preferences leave the current evaluation identity unchanged',()=>{const f=fixture();f.node('#fatigueD2').value='0';f.node('#fatigueD3').value='0';const before=f.eval('evaluationKey()');f.node('#fatigueD2').value='0.03';assert.equal(f.eval('evaluationKey()'),before);});
test('historical pitcher selector recovers failures through retry and ignores older team response',async()=>{const f=fixture(),a=deferred(),b=deferred();f.context.a=a.promise;f.context.b=b.promise;f.eval("mountHistoricalPitch=()=>{};json=async()=>({date:HISTORY_DATE,teams:{A:{pitchers:[{name:'Old'}]},B:{pitchers:[{name:'New'}]}}});team=n=>n==='A'?a:b");f.node('#reviewTeam').value='A';const first=f.eval('loadHistoricalPitchers()');f.node('#reviewTeam').value='B';const second=f.eval('loadHistoricalPitchers()');b.resolve({pitchers:[{name:'New'}]});await second;a.resolve({pitchers:[{name:'Old'}]});await first;assert.match(f.node('#historyPitcher').innerHTML,/New/);assert.doesNotMatch(f.node('#historyPitcher').innerHTML,/Old/);f.eval("team=async()=>{throw Error('offline')}");await f.eval('loadHistoricalPitchers()');assert.match(f.node('#historyPitchChange').innerHTML,/重新載入/);assert.equal(typeof f.node('#historyPitchRetry').onclick,'function');});
test('single-day summary never substitutes whole-season significance and retries missing data',async()=>{const f=fixture();f.node('#reviewTeam').value='A';f.eval("timingData={games:{}};json=async url=>url.endsWith('games.json')?[{date:'2025-09-20',game:'2025-340',away:'A',home:'B',away_score:1,home_score:2}]:{pas:[{pa_id:'one',bat_team:'A',fld_team:'B',is_ph:true}]}" );await f.eval('renderReview()');assert.match(f.node('#reviewBody').innerHTML,/實際代打/);assert.doesNotMatch(f.node('#reviewBody').innerHTML,/95%|全聯盟/);f.eval("json=async()=>{throw Error('offline')}");await f.eval('renderReview()');assert.match(f.node('#reviewBody').innerHTML,/重新載入/);});

test('rapid audience switches do not let an older team-mode action reopen lineup',async()=>{const f=fixture(),a=deferred(),b=deferred();f.context.a=a.promise;f.context.b=b.promise;f.eval("let audienceCall=0;applyOwnLineup=()=>++audienceCall===1?a:b;showFeaturePage=async p=>{window.targetPage=p}");const first=f.eval("setAudienceMode('team')"),second=f.eval("setAudienceMode('general')");b.resolve();await second;a.resolve();await first;assert.equal(f.eval('audienceMode'),'general');assert.equal(f.context.window.targetPage,undefined);});

test('general batting options put configured nine first and retain every reserve exactly once',()=>{const f=fixture(),c={slots:Array.from({length:9},(_,i)=>({name:'P'+i}))},roster={hitters:[...c.slots,{name:'Reserve',hand:'L'}]};f.context.config=c;f.context.roster=roster;const html=f.eval('battingOptions(roster,config,false)');assert.match(html,/已設定場上九棒/);assert.match(html,/其他球員/);assert.ok(html.indexOf('第 9 棒')<html.indexOf('Reserve'));assert.equal((html.match(/value="P0"/g)||[]).length,1);assert.doesNotMatch(f.eval('battingOptions(roster,config,true)'),/Reserve/);});
test('historical fatigue curve has onset, interpolation, capped extrapolation and reliever exclusion',()=>{const f=fixture();assert.equal(f.eval('historicalFatigue(80,true,[[85,0],[95,0.03],[105,0.05]])'),0);assert.equal(f.eval('historicalFatigue(95,true,[[85,0],[95,0.03],[105,0.05]])'),0.03);assert.equal(f.eval('historicalFatigue(160,true,[[85,0],[95,0.03],[105,0.05]])'),0.12);assert.equal(f.eval('historicalFatigue(100,false,[[85,0],[95,0.03]])'),0);});

test('current evaluation never inherits historical recency or streak fatigue preferences',()=>{const f=fixture();f.node('#recentWeight').value='100';f.node('#fatigueD2').value='0.03';f.node('#fatigueD3').value='0.06';assert.equal(f.eval('prefSettings().recent_weight'),0);assert.equal(f.eval('prefSettings().fatigue_d2'),0);assert.equal(f.eval('prefSettings().fatigue_d3'),0);});
test('advanced preset controls belong to the historical page instead of current evaluation',()=>{const html=fs.readFileSync(path.join(__dirname,'../docs/index.html'),'utf8'),prefs=html.indexOf('id="prefsPanel"');assert.ok(prefs>html.indexOf('id="reviewPage"'));assert.ok(prefs<html.indexOf('id="evaluationPage"'));assert.match(html,/重設歷史情境/);});

test('historical fatigue settings never clear an unchanged current evaluation',()=>{const f=fixture();f.node('#fatigueD2').value='0';f.eval('resultInputKey=evaluationKey();S.last={id:"old"};S.ready=true');f.node('#fatigueD2').value='0.03';f.eval('invalidateCustom()');assert.equal(f.eval('S.last.id'),'old');});

test('season review missing static game is explained without a doomed request and retry',async()=>{const f=fixture();f.eval("STATIC=true;timingData={by_team:{}};showFeaturePage=async()=>{};loadGames=async()=>{S.games=[]};loadGame=async()=>{throw Error('must not request absent file')}");await f.eval("openReplayPA('2025-999-a001','pen')");assert.equal(f.node('#replayNote').hidden,false);assert.match(f.node('#replayNote').textContent,/未收錄/);assert.match(f.node('#paList').innerHTML,/已收錄/);});


test('difference labels preserve tiny directions without rounding to signed zero or inventing missing values',()=>{
 const f=fixture();
 for(const [value,expected] of [[0,'0.00 百分點'],[-0,'0.00 百分點'],[.0001,'增加不到 0.01 百分點'],[-.009,'減少不到 0.01 百分點'],[.01,'+0.01 百分點'],[-.12,'−0.12 百分點']]){
  f.context.value=value;assert.equal(f.eval('deltaLabel(value)'),expected);
 }
 for(const value of [null,undefined,NaN,Infinity]){f.context.value=value;assert.equal(f.eval('deltaLabel(value)'),'資料不足');}
 assert.equal(f.eval('deltaLabel(-.00001,3,"分")'),'減少不到 0.001 分');
 assert.equal(f.eval('sign(-.00001,3)'),'0.000');
});

test('both comparison panels and evaluation tables use identical tiny difference wording',()=>{
 const f=fixture(),base={角色:'現任',球員:'Current',相對現任:0,階層式:0,機器學習:0,樣本球數:1000,預估勝率:0,價值分數:50,守備:'ok',守備說明:'目前守捕手'};
 const pen={角色:'場上',投手:'Pitcher',守方勝率增減:0,樣本球數:1000,預估失分:0,疲勞調整:0,疲勞:'-',價值分數:50};
 f.context.result={situation:{pitcher:'Pitcher'},candidates:[base,{...base,角色:'代打',球員:'Tiny',相對現任:-.00001}],bullpen:{next:['Next'],rows:[pen,{...pen,角色:'牛棚',投手:'Tiny',守方勝率增減:-.00001}]}};
 for(const code of ['comparisonPanel(result,null,"ph")','comparisonPanel(result,null,"pen")','phTable(result)','penTable(result)']){
  const html=f.eval(code);assert.match(html.replace(/<[^>]+>/g,''),/減少不到 0.01 百分點/);assert.doesNotMatch(html,/−0\.00|NaN|undefined/);
 }
 f.context.result.candidates[1]['相對現任']=null;
 assert.match(f.eval('comparisonPanel(result,null,"ph")'),/資料不足/);
 const missingTable=f.eval('phTable(result)');assert.match(missingTable,/資料不足/);assert.equal((missingTable.match(/class="dbar"/g)||[]).length,1);
 for(const value of [null,undefined,NaN,Infinity]){f.context.value=value;assert.equal(f.eval('dbar(value,0,1)'), '');}
});

test('fielding copy removes direct coverage repetition but retains extra player and backup catcher warnings',()=>{
 const f=fixture();assert.equal(f.eval('fieldingMessage({守備:"ok",守備說明:"A 可直接接守右外野"})'),'<strong class="fielding-label">推估可接守右外野</strong>');
 assert.equal(f.eval('fieldingMessage({守備:"ok",守備說明:"B 接任指定打擊"})'),'<strong class="fielding-label">承接原 DH 棒次</strong>');
 const html=f.eval('fieldingMessage({守備:"warn",守備說明:"需由 A 接守捕手（再消耗 1 名板凳）；之後板凳已無備用捕手"})');
 assert.match(html,/A · 捕手（另需 1 人）/);assert.match(html,/無備用捕手/);
});


test('preset persistence verifies writes and reports blocked storage without losing the session setting',()=>{
 const f=fixture();let raw=null;
 f.context.localStorage={getItem:()=>raw,setItem:()=>{}};
 assert.equal(f.eval('writePrefs({recentWeight:30})'),false);
 f.node('#myScore').value='3';f.node('#oppScore').value='2';f.eval('saveSituation()');
 assert.doesNotMatch(f.node('#presetStatus').textContent,/已存成預設/);
 f.node('#recentWeight').value='30';f.node('#fatigueD2').value='0.015';f.node('#fatigueD3').value='0.03';
 assert.doesNotThrow(()=>f.eval('savePrefSettings()'));assert.equal(f.node('#recentWeightOut').textContent,'30%');
 assert.match(f.node('#presetStatus').textContent,/無法保存/);
 f.context.localStorage.setItem=(k,value)=>{raw=value};
 assert.equal(f.eval('writePrefs({recentWeight:30})'),true);
});

test('malformed preset records cannot crash saving or overwrite the damaged record',()=>{
 for(const raw of ['broken','[]','42','"legacy string"','null']){
  const f=fixture();let writes=0;f.context.localStorage={getItem:()=>raw,setItem:()=>writes++};
  f.node('#myScore').value='0';f.node('#oppScore').value='0';
  assert.equal(f.eval('Object.keys(readPrefs()).length'),0);
  assert.doesNotThrow(()=>f.eval('saveSituation()'));assert.equal(writes,0);
  assert.match(f.node('#presetStatus').textContent,/無法保存/);
 }
});

test('saving a preset rejects invalid scores while preserving an existing valid preset',()=>{
 const f=fixture(),raw=JSON.stringify({situation:{inning:7,myScore:3,oppScore:2}});let writes=0;
 f.context.localStorage={getItem:()=>raw,setItem:()=>writes++};
 f.node('#oppScore').value='0';
 for(const score of ['', '-1', '2.5', 'Infinity']){
  f.node('#myScore').value=score;f.eval('saveSituation()');assert.equal(writes,0);assert.match(f.node('#presetStatus').textContent,/非負整數/);
 }
});


test('single-day review preserves the current date scope without reviving the seasonal dashboard',async()=>{
 const f=fixture(),root=path.join(__dirname,'../docs/data');
 const games=JSON.parse(fs.readFileSync(path.join(root,'replay/games.json'),'utf8'));
 const selected=games.filter(g=>g.date==='2025-09-20'&&(g.away==='樂天桃猿'||g.home==='樂天桃猿'));
 const files={'data/replay/games.json':games};
 for(const g of selected)files[`data/replay/${g.game}.json`]=JSON.parse(fs.readFileSync(path.join(root,'replay',g.game+'.json'),'utf8'));
 f.context.files=files;f.node('#reviewTeam').value='樂天桃猿';
 f.eval('json=async url=>files[url];timingData=null;');await f.eval('renderReview()');
 const html=f.node('#reviewBody').innerHTML;
 assert.equal((html.match(/<article /g)||[]).length,1);
 assert.match(html,/實際代打/);assert.match(html,/單日結果不代表模型準確度/);
 assert.match(html,new RegExp('data-history-game="'+selected[0].game+'"'));
 assert.doesNotMatch(html,/全聯盟回測|提早建議時的中位數|分歧最大的打席/);
});

test('matchup detail rounds tiny whiff differences without negative zero',async()=>{
 const f=fixture();f.context.detail={batter:'B',pitcher:'P',bhand:'R',phand:'R',mix_n:100,skill:0,fit:0,platoon:0,cells:['速球','滑卡','曲球','低落'].flatMap(g=>['高中','低'].map(z=>({cell:g+z,n:10,usage:.125,whiff_dev:-.00001})))};
 f.eval('S.last={model_cutoff:"2026-01-01",situation:{pitcher:"Other"}};mountPitchChange=()=>{};bindMixSwitch=()=>{};api=async()=>detail;');
 await f.eval('showDetail("B","P",null)');const html=f.node('#detail').innerHTML;
 assert.match(html,/揮空 0.0/);assert.doesNotMatch(html,/揮空 [−-]0.0/);
});

test('invalid historical pitcher counts never overwrite a valid saved preset',()=>{
 const f=fixture();let raw=JSON.stringify({history:{pitchCount:'90'}}),writes=0;
 f.context.localStorage={getItem:()=>raw,setItem:(k,v)=>{writes++;raw=v;}};
 f.node('#historyPlayer').value='P';
 for(const value of ['', '-1', '1.5', '161', 'Infinity']){
  f.node('#historyPitchCount').value=value;f.eval('saveHistoryPreset()');
  assert.equal(writes,0);assert.match(f.node('#presetStatus').textContent,/0–160/);
 }
 f.node('#historyPitchCount').value='90';f.eval('saveHistoryPreset()');
 assert.equal(writes,1);assert.equal(JSON.parse(raw).history.pitchCount,'90');
 f.node('#historyPlayer').disabled=true;f.eval('saveHistoryPreset()');assert.equal(writes,1);
});

test('hitter preset ignores a hidden invalid pitcher count',()=>{
 const f=fixture();let raw=null;f.context.localStorage={getItem:()=>raw,setItem:(k,v)=>{raw=v;}};
 f.node('#historyPlayer').value='H';f.node('#historyPitchCount').value='-1';f.eval('historyRole="hitters";saveHistoryPreset()');
 assert.equal(JSON.parse(raw).history.pitchCount,'0');assert.match(f.node('#presetStatus').textContent,/已保存/);
});

test('history player selection survives revisits and stays isolated by team and role',async()=>{
 const f=fixture();f.context.historyData={date:'2025-09-20',teams:{A:{pitchers:[{name:'P1',games14:3,last_date:'2025-09-19'},{name:'P2',games14:2,last_date:'2025-09-18'}],hitters:[{name:'H',games14:1,last_date:'2025-09-19'}]},B:{pitchers:[{name:'B1',games14:1,last_date:'2025-09-19'}]}}};
 f.eval('json=async()=>historyData;renderHistoryContext=()=>{}');f.node('#reviewTeam').value='A';
 await f.eval('loadHistoryContext()');f.node('#historyPlayer').value='P2';
 await f.eval('loadHistoryContext()');assert.equal(f.node('#historyPlayer').value,'P2');
 f.eval('historyRole="hitters"');await f.eval('loadHistoryContext()');assert.equal(f.node('#historyPlayer').value,'H');
 f.eval('historyRole="pitchers"');await f.eval('loadHistoryContext()');assert.equal(f.node('#historyPlayer').value,'P2');
 f.node('#reviewTeam').value='B';await f.eval('loadHistoryContext()');assert.equal(f.node('#historyPlayer').value,'B1');
 f.node('#reviewTeam').value='A';await f.eval('loadHistoryContext()');assert.equal(f.node('#historyPlayer').value,'P2');
});


test('single-day analysis ignores audience changes without clearing its result or opening lineup',async()=>{
 const f=fixture();f.eval("currentPage=()=> 'review';S.last={id:'historical'};applyOwnLineup=()=>{throw Error('must not apply current roster')}");
 await f.eval("setAudienceMode('team')");assert.equal(f.eval('S.last.id'),'historical');assert.equal(f.eval('audienceMode'),'team');
});
test('history subpage team is synchronized without changing the evaluation teams',()=>{
 const f=fixture();f.node('#customPanel').addEventListener=()=>{};f.node('#myTeam').value='樂天桃猿';f.node('#oppTeam').value='味全龍';
 f.eval("loadGames=()=>{};bindStatic()");f.node('#rpTeam').value='台鋼雄鷹';f.node('#rpTeam').onchange();
 assert.equal(f.node('#reviewTeam').value,'台鋼雄鷹');assert.equal(f.node('#myTeam').value,'樂天桃猿');assert.equal(f.node('#oppTeam').value,'味全龍');
});
test('pitch mix selection survives a review reload and excludes pitchers with no prior appearance',async()=>{
 const f=fixture();f.node('#reviewTeam').value='A';
 f.eval("team=async()=>({pitchers:[{name:'P1'},{name:'P2'},{name:'Future'}]});json=async()=>({date:HISTORY_DATE,teams:{A:{pitchers:[{name:'P1'},{name:'P2'}]}}});mountHistoricalPitch=()=>{}");
 await f.eval('loadHistoricalPitchers()');f.node('#historyPitcher').value='P2';await f.eval('loadHistoricalPitchers()');
 assert.equal(f.node('#historyPitcher').value,'P2');assert.doesNotMatch(f.node('#historyPitcher').innerHTML,/Future/);
});
test('static pitching replay uses the incumbent snapshot and retains actual incoming pitcher',async()=>{
 const f=fixture();f.context.files={'data/replay/day-2025-09-20/index.json':{schema_version:1,date:'2025-09-20',games:{},files:{'2025-340-h018':'2025-340-h018.json'}},'data/replay/day-2025-09-20/2025-340-h018.json':{date:'2025-09-20',pa_id:'2025-340-h018',ph:{situation:{pitcher:'New'},replay_context:{}},pen:{situation:{pitcher:'Old'},actual:{pitcher:'New'},replay_context:{}}}};
 f.eval('json=async u=>files[u]');const r=await f.eval("staticApi('api/replay?pa=2025-340-h018&decision=pen')");
 assert.equal(r.situation.pitcher,'Old');assert.equal(r.actual.pitcher,'New');assert.equal(r.replay_context.decision,'pen');
});
