"use strict";
/* Historical decisions have no dependency on audience mode or current lineup. */
const BacktestView = (() => {
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=v=>Number.isFinite(v)?v.toFixed(4):'—';
  const sign=v=>Number.isFinite(v)?(v>0?'+':'')+v.toFixed(3):'—';
  const metric=v=>Number.isFinite(v)?v.toFixed(6):'—';
  const metricSign=v=>Number.isFinite(v)?(v>0?'+':'')+v.toFixed(6):'—';
  const outcome=v=>({SO:'三振',BB:'保送',uBB:'保送',iBB:'故意四壞',HBP:'觸身球','1B':'一壘安打','2B':'二壘安打','3B':'三壘安打',HR:'全壘打',GO:'滾地出局',FO:'出局',AO:'飛球出局',FC:'野手選擇'}[v]||v||'未提供');
  const relativeReduction=row=>Number.isFinite(row?.baseline_mse)&&Number.isFinite(row?.mse_reduction)&&row.baseline_mse>0?100*row.mse_reduction/row.baseline_mse:null;
  function intervalMark(row,extent){
    const span=extent*2,place=v=>100*(v+extent)/span;
    const lo=row.mse_reduction_ci[0],hi=row.mse_reduction_ci[1],point=row.mse_reduction;
    return `<div class="bt-interval" role="img" aria-label="相對基準誤差減少 ${(100*point/row.baseline_mse).toFixed(2)}%，95% 區間 ${(100*lo/row.baseline_mse).toFixed(2)}% 至 ${(100*hi/row.baseline_mse).toFixed(2)}%"><span class="bt-zero"></span><span class="bt-ci" style="left:${place(lo)}%;width:${100*(hi-lo)/span}%"></span><span class="bt-dot" style="left:${place(point)}%"></span></div>`;
  }

  function decisions(pas, marks, team, kind, threshold=1) {
    const last={}, rows=[];
    for(const p of pas){
      const previous=last[p.fld_team]; last[p.fld_team]=p.pitcher;
      if((kind==='pen'?p.fld_team:p.bat_team)!==team)continue;
      const raw=marks?.[p.pa_id],gain=raw?.[kind==='pen'?0:3];
      const eligible=p.inning>=6&&typeof gain==='number'&&Number.isFinite(gain);
      rows.push({pa:p,actual:kind==='pen'?!!previous&&previous!==p.pitcher:!!p.is_ph,
                 gain:eligible?gain:null,suggested:eligible&&gain>=threshold,
                 incumbent:kind==='pen'?(raw?.[2]||previous||null):(raw?.[5]||(!p.is_ph?p.batter:null)),
                 best:raw?.[kind==='pen'?1:4]||null,eligible,
                 reason:p.inning<6?'六局前，研究範圍外':!eligible?'缺少可比較候選／估計':'可評估'});
    }
    return rows;
  }
  function cells(rows){
    const c={both:[],system:[],actual:[],neither:[],unknown:[],outside:[]};
    for(const r of rows){const key=r.pa.inning<6?'outside':!r.eligible?'unknown':r.suggested?(r.actual?'both':'system'):(r.actual?'actual':'neither');c[key].push(r);}
    return c;
  }
  function promptRuns(rows){
    const groups=[];
    for(const r of rows){
      const previous=groups.at(-1), last=previous?.at(-1);
      if(last&&r.suggested&&last.suggested&&!r.actual&&!last.actual&&r.incumbent===last.incumbent&&
         r.index===last.index+1)previous.push(r);
      else groups.push([r]);
    }
    return groups;
  }
  function timeline({element,pas,marks,team,open,disclosure=()=>({}),setDisclosure=()=>{}}){
    let kind='pen', filter='all', selected=null;
    function render(){
      const rows=decisions(pas,marks,team,kind).map((r,index)=>({...r,index})),groups=cells(rows);
      rows.forEach((r,i)=>{r.firstPrompt=r.suggested&&(!rows[i-1]?.suggested||rows[i-1].incumbent!==r.incumbent);});
      const labels={both:'有提示、有換人',system:'只有系統提示',actual:'只有實際換人',neither:'無提示、未換人',unknown:'資料不足／不可評估',outside:'六局前：示範範圍'};
      const visible=filter==='all'?rows.filter(r=>r.actual||r.suggested):groups[filter];
      const event=r=>`<button type="button" class="bt-event" data-bt-pa="${esc(r.pa.pa_id)}" aria-pressed="${selected===r.pa.pa_id}"><span>${r.pa.inning}局${r.pa.half==='away'?'上':'下'} · ${r.pa.outs}出局</span><span>${esc(r.incumbent||'原人選未知')}</span><span class="bt-prompt">${r.suggested?'◇ '+(r.firstPrompt?'本段首次提示 ':'持續提示 ')+sign(r.gain)+' 百分點':r.eligible?'— 未達門檻':esc(r.reason)}</span><span>${r.actual?'● 實際換人':'○ 實際未換'}</span></button>`;
      element.innerHTML=`<div class="bt-kind"><button type="button" data-bt-kind="pen" aria-pressed="${kind==='pen'}">換投回顧</button><button type="button" data-bt-kind="ph" aria-pressed="${kind==='ph'}">換打回顧</button></div>
        <div class="bt-groups" aria-label="依決策打席分類">${Object.entries(labels).map(([key,label])=>`<button type="button" data-bt-filter="${key}" aria-pressed="${filter===key}">${label}<strong>${groups[key].length}</strong></button>`).join('')}<button type="button" data-bt-filter="all" aria-pressed="${filter==='all'}">所有提示／調度</button></div>
        <p class="mut">數量單位：打席。同時換人不表示雙方選了同一位；首次提示限目前觀測窗。</p>
        <div class="bt-lanes" aria-hidden="true"><span>決策時點</span><span>原人選</span><span>系統提示軌</span><span>實際調度軌</span></div>
        <div class="bt-timeline" aria-label="依時間排列的決策">${visible.length?promptRuns(visible).map(run=>run.length===1?event(run[0]):`<details class="bt-prompt-run"><summary>${run[0].pa.inning}局起 · ${esc(run[0].incumbent)}連續 ${run.length} 打席提示（未實際換人）</summary>${run.map(event).join('')}</details>`).join(''):'<p>此分類沒有收錄打席。</p>'}</div>
        <div class="bt-decision" aria-live="polite"></div>`;
      element.querySelectorAll('[data-bt-kind]').forEach(b=>b.onclick=()=>{kind=b.dataset.btKind;filter='all';selected=null;render();});
      element.querySelectorAll('[data-bt-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.btFilter;selected=null;render();});
      element.querySelectorAll('[data-bt-pa]').forEach(b=>b.onclick=()=>{
        selected=b.dataset.btPa; const r=rows.find(r=>r.pa.pa_id===selected),p=r.pa;
        element.querySelectorAll('[data-bt-pa]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));
        const detail=element.querySelector('.bt-decision'),selectedPid=selected,state=disclosure(selectedPid);
        detail.innerHTML=`<h4>決策前 · ${p.inning}局${p.half==='away'?'上':'下'} ${p.bat_score}：${p.fld_score}（攻：守）</h4><p>${esc(r.incumbent||'原人選未知')} ${r.best?'與 '+esc(r.best)+' 比較':'尚無可評估候選'} · ${r.gain===null?esc(r.reason):'估計相對差 '+sign(r.gain)+' 百分點'}</p><button type="button" data-bt-open>查看當時完整人選比較</button><details data-bt-action ${state.action?'open':''}><summary>揭示實際調度</summary><p>${r.actual?'實際換上 '+esc(kind==='pen'?p.pitcher:p.batter):'實際續留原人選'}</p><details data-bt-outcome ${state.outcome?'open':''}><summary>揭示這個打席的結果</summary><p>${esc(outcome(p.result))} · 攻方 WPA ${sign(p.WPA*100)} 百分點</p><p class="mut">未發生的另一選擇結果仍未知。</p></details></details>`;
        const action=detail.querySelector('[data-bt-action]'),outcomeDetails=detail.querySelector('[data-bt-outcome]');
        action.ontoggle=()=>{setDisclosure('action',action.open,selectedPid);if(!action.open)outcomeDetails.open=false;};
        outcomeDetails.ontoggle=()=>setDisclosure('outcome',outcomeDetails.open,selectedPid);
        detail.querySelector('[data-bt-open]').onclick=()=>open(selected,kind);
      });
    }
    render();
  }

  async function validation(element,fetcher,expectedBatch){
    element.innerHTML='<p role="status">載入同測試集模型比較…</p>';
    let report;
    const nonnegative=v=>Number.isFinite(v)&&v>=0;
    const validMetric=r=>r&&['mse','mae','baseline_mse','mse_reduction'].every(k=>Number.isFinite(r[k]))&&r.mse>=0&&r.mae>=0&&r.baseline_mse>0&&Number.isInteger(r.n)&&r.n>0&&Array.isArray(r.mse_reduction_ci)&&r.mse_reduction_ci.length===2&&r.mse_reduction_ci.every(Number.isFinite)&&r.mse_reduction_ci[0]<=r.mse_reduction_ci[1];
    // Validate displayed diagnostics before rendering any conclusion or controls.
    const validDiagnostics=r=>(r.sampling_sensitivity==null||(Array.isArray(r.sampling_sensitivity)&&r.sampling_sensitivity.every(x=>x&&nonnegative(x.mean_absolute_prediction_shift))))&&
      (r.decision_sampling_sensitivity==null||((d=>Number.isInteger(d.cases)&&d.cases>0&&Array.isArray(d.variants)&&d.variants.length>0&&d.variants.every(v=>v&&Number.isInteger(v.sample)&&v.sample>0&&Number.isInteger(v.seed)&&v.seed>=0&&['top1_changes','threshold_changes'].every(k=>Number.isInteger(v[k])&&v[k]>=0&&v[k]<=d.cases)&&nonnegative(v.max_gain_shift)))(r.decision_sampling_sensitivity)));
    const validReport=r=>Array.isArray(r.candidates)&&Array.isArray(r.monthly)&&
      ['s1_w0','s1_w1',r.current_key,r.selected_key].every(key=>typeof key==='string'&&r.candidates.filter(c=>c.key===key).length===1&&['development','time_check'].every(period=>validMetric(r.candidates.find(c=>c.key===key)[period])))&&
      r.monthly.every(m=>typeof m.month==='string'&&['development','time_check'].includes(m.period)&&validMetric(m.current)&&validMetric(m.selected))&&validDiagnostics(r);
    try{report=await fetcher('data/model-evaluation.json');if(report.schema_version!==1||report.training_version!==4||report.engine_contract!==4||!report.batch_id||(expectedBatch&&report.batch_id!==expectedBatch)||report.status!=='evaluated'||!validReport(report))throw Error('schema');}
    catch{element.innerHTML='<div role="alert"><h3>無法載入模型驗證</h3><p>驗證資料載入失敗、內容不完整或與目前模型版本不一致。請重新載入；若仍失敗，重新整理網站後再試。</p></div><button type="button">重新載入驗證結果</button>';element.querySelector('button').onclick=()=>validation(element,fetcher,expectedBatch);return;}
    const names=[['s1_w0','階層式'],['s1_w1','GBT'],[report.current_key,'現行集成'],[report.selected_key,'開發期最佳候選']];
    function render(period){
      const list=names.map(([key,label])=>({label,row:report.candidates.find(c=>c.key===key)?.[period]})).filter(x=>x.row);
      const current=report.candidates.find(c=>c.key===report.current_key)?.[period],pct=relativeReduction(current);
      const ci=current?.mse_reduction_ci||[],crosses=ci.length===2&&ci[0]<=0&&ci[1]>=0;
      const months=report.monthly.filter(m=>(m.period===period));
      const declined=months.filter(m=>m.current.mse_reduction<0).map(m=>m.month.slice(5)+'月');
      const conclusion=pct===null?'缺少可比較基準':crosses?'改善尚不明確':pct>0?'此期間誤差較低':'此期間誤差較高';
      const extent=Math.max(1e-6,...names.flatMap(([key])=>{
        const r=report.candidates.find(c=>c.key===key);
        return r?['development','time_check'].flatMap(p=>r[p].mse_reduction_ci.map(Math.abs)):[];
      }))*1.15;
      element.innerHTML=`<h3>未來月份的打席預測，是否優於基準？</h3><p class="mut">回溯式滾動驗證 · 目標：單打席 RE24 · MSE 越低越好</p><div class="bt-verdict"><strong>${conclusion}</strong><p>現行集成相較聯盟基準，${pct===null?'無法計算誤差變化':`誤差${pct>=0?'減少':'增加'} <b>${Math.abs(pct).toFixed(2)}%</b>`}。</p><p>${ci.length===2&&current.baseline_mse>0?`95% 區間：${(100*ci[0]/current.baseline_mse).toFixed(2)}% 至 ${(100*ci[1]/current.baseline_mse).toFixed(2)}%（正值為改善）。`:''}${crosses?'區間跨過 0，還不能確認比基準更好。':''}</p><p>較基準退步的月份：${declined.length?declined.join('、'):'此期間無'}。</p></div><div class="bt-kind"><button type="button" data-period="development" aria-pressed="${period==='development'}">5–8月：開發比較</button><button type="button" data-period="time_check" aria-pressed="${period==='time_check'}">9–10月：時間檢查</button></div><div class="bt-models"><div><strong>聯盟基準</strong><span>MSE ${metric(list[0]?.row.baseline_mse)}</span></div>${list.map(x=>`<div><strong>${esc(x.label)}</strong><span>相對基準誤差${relativeReduction(x.row)>=0?'減少':'增加'} ${relativeReduction(x.row)===null?'—':Math.abs(relativeReduction(x.row)).toFixed(2)+'%'}</span><details><summary>數值與樣本</summary><span>MSE ${metric(x.row.mse)} · MAE ${metric(x.row.mae)}</span><span>相對基準誤差減少 ${metricSign(x.row.mse_reduction)}</span><span class="mut">比賽重抽樣 95% 區間 [${x.row.mse_reduction_ci.map(metricSign).join(', ')}] · ${x.row.n.toLocaleString()} 打席</span></details></div>`).join('')}</div><h4>每月穩定度</h4><div class="bt-months">${report.monthly.map(m=>`<div><strong>${m.month}</strong><span class="${m.current.mse_reduction>=0?'pos':'neg'}">現行 ${relativeReduction(m.current)===null?'—':(relativeReduction(m.current)>0?'+':'')+relativeReduction(m.current).toFixed(2)+'%'}</span><details><summary>候選對照</summary><span>開發期候選 ${Number.isFinite(relativeReduction(m.selected))?(relativeReduction(m.selected)>0?'+':'')+relativeReduction(m.selected).toFixed(2):'—'}%</span></details></div>`).join('')}</div><p class="mut">正值為誤差減少；區間跨零代表差異尚不明確。這是觀測打席的預測驗證，不是換人後會增加多少勝率。</p>`;
      element.querySelectorAll('.bt-models>div').forEach((el,i)=>{if(i>0)el.insertAdjacentHTML('beforeend',intervalMark(list[i-1].row,extent));});
      element.querySelector('.bt-models').insertAdjacentHTML('beforeend',`<div class="bt-axis"><span>較差 ${(100*-extent/current.baseline_mse).toFixed(2)}%</span><span>0（相對基準）</span><span>較佳 ${(100*extent/current.baseline_mse).toFixed(2)}%</span></div>`);
      element.querySelectorAll('[data-period]').forEach(b=>b.onclick=()=>render(b.dataset.period));
      if(report.adopted_key){
        const adopted=report.adopted_key===report.current_key;
        element.insertAdjacentHTML('beforeend',`<details class="bt-adoption"><summary>${adopted?'現行集成的採用依據':'候選模型的採用依據'}</summary><p>${adopted?'目前採用 0.5／0.5 集成；開發期最佳候選及區間用於描述，不作獨立勝出證據。':'開發期的配對比賽重抽樣改善區間高於零。'}9–10 月只做時間檢查，不回頭選參數。</p></details>`);
      }
      if(report.decision_sampling_sensitivity){
        const diagnostic=report.decision_sampling_sensitivity,variants=diagnostic.variants;
        element.insertAdjacentHTML('beforeend',`<details><summary>候選排序與提示門檻的抽樣敏感度</summary><p>2025/09/20 各隊、各決策類型，抽取最接近 1 百分點門檻及差距最大的可評估打席，共 ${diagnostic.cases} 組情境；同情境對照 75／300 球及另一種子。</p><ul>${variants.map(v=>`<li>${v.sample} 球、種子 ${v.seed}：首選改變 ${v.top1_changes}/${diagnostic.cases}，提示改變 ${v.threshold_changes}/${diagnostic.cases}，最大差值位移 ${v.max_gain_shift.toFixed(3)} 百分點。</li>`).join('')}</ul><p class="mut">這是刻意挑選邊界與強提示的單日診斷，不能外推全季穩定率，也不是完整集成區間或換人成功機率。</p></details>`);
      }
      if(report.sampling_sensitivity?.length){
        const checks=report.sampling_sensitivity;
        element.insertAdjacentHTML('beforeend',`<details><summary>模擬抽樣穩定度</summary><p>對照每位投手抽 75、150、300 球及另一個隨機種子。各月平均預測位移介於 ${num(Math.min(...checks.map(x=>x.mean_absolute_prediction_shift)))} 至 ${num(Math.max(...checks.map(x=>x.mean_absolute_prediction_shift)))} RE24；此檢查未用於選參數，也不代表名次一定穩定。</p></details>`);
      }
    }
    render('time_check');
  }
  return {decisions,cells,promptRuns,timeline,validation,relativeReduction};
})();
if(typeof module!=='undefined')module.exports=BacktestView;
