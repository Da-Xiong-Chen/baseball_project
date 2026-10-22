const {test}=require('node:test');const assert=require('node:assert/strict');
const B=require(process.env.BASEBALL_BACKTEST_SCRIPT||'../docs/backtest.js');
const pa=(id,inning,pitcher,other={})=>({pa_id:id,inning,pitcher,fld_team:'A',bat_team:'B',is_ph:false,...other});
test('four groups partition evaluated PA and keep unknown estimates separate',()=>{
 const rows=B.decisions([pa('1',5,'P'),pa('2',6,'P'),pa('3',6,'Q'),pa('4',7,'Q'),pa('5',7,'R'),pa('6',8,'R')],
 {'2':[2,'X','P'],'3':[2,'X','P'],'4':[.1,'X','Q'],'5':[.1,'X','Q']},'A','pen');
 const c=B.cells(rows);assert.deepEqual(Object.fromEntries(Object.entries(c).map(([k,v])=>[k,v.length])),{both:1,system:1,actual:1,neither:1,unknown:1,outside:1});
 assert.equal(rows[2].incumbent,'P');assert.equal(rows[2].pa.pitcher,'Q');
});
test('consecutive prompt PA stay separate observations, not claimed as multiple substitutions',()=>{
 const rows=B.decisions([pa('1',6,'P'),pa('2',6,'P'),pa('3',7,'P')],{'1':[2,'X','P'],'2':[3,'X','P'],'3':[4,'X','P']},'A','pen');
 assert.equal(rows.filter(x=>x.suggested).length,3);assert.equal(rows.filter(x=>x.actual).length,0);
 const groups=B.promptRuns(rows.map((r,index)=>({...r,index})));assert.equal(groups.length,1);assert.equal(groups[0].length,3);
});
test('pinch hitting uses the batting observation team and leaves original hitter unknown when absent',()=>{
 const rows=B.decisions([pa('1',7,'P',{is_ph:true,batter:'New'})],{},'B','ph');
 assert.equal(rows[0].actual,true);assert.equal(rows[0].incumbent,null);assert.equal(rows[0].eligible,false);
 assert.equal(B.decisions([pa('1',7,'P')],{},'A','ph').length,0);
});
test('model validation keeps small improvements visible and distinguishes candidate from adoption',async()=>{
 const metric={n:5396,mse:.225711,mae:.361129,baseline_mse:.225998,mse_reduction:.000287,mse_reduction_ci:[-.000575,.001115]};
 const candidates=['s1_w0','s1_w1','current','candidate'].map(key=>({key,time_check:metric,development:metric}));
 const buttons=[{dataset:{period:'development'}},{dataset:{period:'time_check'}}];
 const el={innerHTML:'',querySelector:()=>({insertAdjacentHTML(){}}),querySelectorAll:sel=>sel==='[data-period]'?buttons:Array.from({length:5},()=>({insertAdjacentHTML(){}})),insertAdjacentHTML(pos,html){this.innerHTML+=html;}};
 await B.validation(el,async()=>({schema_version:1,training_version:4,engine_contract:4,batch_id:'test-batch',status:'evaluated',current_key:'current',selected_key:'candidate',adopted_key:'current',candidates,monthly:[]}));
 assert.match(el.innerHTML,/改善尚不明確/);assert.match(el.innerHTML,/0\.13%/);assert.match(el.innerHTML,/0\.225711/);assert.match(el.innerHTML,/\+0\.000287/);
 assert.match(el.innerHTML,/現行集成的採用依據/);assert.match(el.innerHTML,/開發期最佳候選/);
 buttons[0].onclick();assert.match(el.innerHTML,/5–8月：開發比較/);
});


test('same version from another model batch is rejected',async()=>{
 const el={innerHTML:'',querySelector:()=>({})};
 await B.validation(el,async()=>({schema_version:1,training_version:4,engine_contract:4,batch_id:'other',status:'evaluated'}),'expected');
 assert.match(el.innerHTML,/無法載入模型驗證/);
});

test('validation failure offers a working retry without claiming training is unfinished',async()=>{
 let calls=0;const retry={};
 const el={innerHTML:'',querySelector:()=>retry};
 const fetcher=async()=>{calls++;throw Error('offline');};
 await B.validation(el,fetcher,'expected');
 assert.match(el.innerHTML,/role="alert"/);
 assert.doesNotMatch(el.innerHTML,/尚未完成|正在重建/);
 assert.equal(typeof retry.onclick,'function');
 await retry.onclick();assert.equal(calls,2);
});

test('truncated or invalid metrics never produce a partial validation conclusion',async()=>{
 const good={n:1,mse:.2,mae:.1,baseline_mse:.3,mse_reduction:.1,mse_reduction_ci:[-.1,.2]};
 for(const bad of [null,{...good,mse:NaN},{...good,baseline_mse:0},{...good,mse_reduction_ci:[.2,-.1]}]){
  const el={innerHTML:'',querySelector:()=>({})};
  const candidates=['s1_w0','s1_w1','current','candidate'].map(key=>({key,time_check:bad,development:good}));
  await B.validation(el,async()=>({schema_version:1,training_version:4,engine_contract:4,batch_id:'expected',status:'evaluated',current_key:'current',selected_key:'candidate',candidates,monthly:[]}),'expected');
  assert.match(el.innerHTML,/無法載入模型驗證/);assert.doesNotMatch(el.innerHTML,/bt-verdict/);
 }
});


test('relative error change uses baseline MSE and rejects zero or missing baselines',()=>{
 assert.equal(B.relativeReduction({baseline_mse:.2,mse_reduction:.002}),1);
 assert.equal(B.relativeReduction({baseline_mse:.2,mse_reduction:-.004}),-2);
 assert.equal(B.relativeReduction({baseline_mse:0,mse_reduction:1}),null);
});

test('incomplete optional diagnostics fail before any model conclusion is displayed',async()=>{
 const metric={n:1,mse:.2,mae:.1,baseline_mse:.3,mse_reduction:.1,mse_reduction_ci:[-.1,.2]};
 const report={schema_version:1,training_version:4,engine_contract:4,batch_id:'expected',status:'evaluated',current_key:'current',selected_key:'candidate',
  candidates:['s1_w0','s1_w1','current','candidate'].map(key=>({key,time_check:metric,development:metric})),monthly:[]};
 const variant={sample:75,seed:0,top1_changes:0,threshold_changes:0,max_gain_shift:.01};
 const diagnostic={cases:17,variants:[variant]};
 const badFields=[{decision_sampling_sensitivity:{}},{decision_sampling_sensitivity:{...diagnostic,variants:[{...variant,max_gain_shift:null}]}},
  {decision_sampling_sensitivity:{...diagnostic,variants:[{...variant,top1_changes:18}]}},
  {sampling_sensitivity:'truncated'}, {sampling_sensitivity:[{}]}, {sampling_sensitivity:[{mean_absolute_prediction_shift:-.1}]},
  {candidates:report.candidates.map(c=>({...c,time_check:{...metric,mse:-.2}}))}];
 for(const extra of badFields){
  const retry={insertAdjacentHTML(){}};const el={innerHTML:'',querySelector:()=>retry,querySelectorAll:()=>[],insertAdjacentHTML(pos,html){this.innerHTML+=html;}};
  await B.validation(el,async()=>({...report,...extra}),'expected');
  assert.match(el.innerHTML,/role="alert"/);assert.doesNotMatch(el.innerHTML,/bt-verdict/);assert.equal(typeof retry.onclick,'function');
 }
});

test('complete release diagnostics render with finite values',async()=>{
 const report=require('../docs/data/model-evaluation.json');
 const el={innerHTML:'',querySelector:()=>({insertAdjacentHTML(){}}),querySelectorAll:()=>[],insertAdjacentHTML(pos,html){this.innerHTML+=html;}};
 await B.validation(el,async()=>report,report.batch_id);
 assert.match(el.innerHTML,/bt-verdict/);assert.match(el.innerHTML,/最大差值位移/);assert.doesNotMatch(el.innerHTML,/NaN|undefined/);
});


test('timeline PA opens details, formats outcome and forwards disclosure to full comparison',()=>{
 const action={open:false},outcome={open:false},openButton={},button={dataset:{btPa:'p'},setAttribute(){}};
 const detail={innerHTML:'',querySelector:s=>s==='[data-bt-action]'?action:s==='[data-bt-outcome]'?outcome:openButton};
 const el={innerHTML:'',querySelector:()=>detail,querySelectorAll:s=>s==='[data-bt-pa]'?[button]:[]};
 const changes=[];let opened;
 B.timeline({element:el,pas:[pa('p',6,'P',{half:'away',outs:0,bat_score:1,fld_score:2,result:'2B',WPA:.02})],
   marks:{p:[2,'Q','P']},team:'A',open:(pid,kind)=>{opened=[pid,kind]},
   disclosure:()=>({action:true,outcome:false}),setDisclosure:(...args)=>changes.push(args)});
 button.onclick();assert.match(detail.innerHTML,/二壘安打/);assert.match(detail.innerHTML,/data-bt-action open/);
 outcome.open=true;outcome.ontoggle();assert.deepEqual(changes,[['outcome',true,'p']]);
 openButton.onclick();assert.deepEqual(opened,['p','pen']);
});
