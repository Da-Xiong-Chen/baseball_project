(function(root){
 'use strict';
 function mount({element,snapshot,label}){
  if(!element)return;
  const q=s=>element.querySelector(s),html=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let source=null;
  element.innerHTML='<summary>牛棚接續規劃</summary><div class="capacity-body"><p class="mut">依自行確認的打席容量安排接續，檢查是否夠用。</p><button type="button" class="link" data-refresh>帶入已選牛棚</button><label class="f">預計涵蓋打席數<input data-target type="number" min="1" max="1000" inputmode="numeric" placeholder="例如 6"></label><div data-rows class="capacity-rows"></div><button type="button" class="btn-primary" data-calculate>檢查接續</button><div data-output role="status" aria-live="polite"></div></div>';
  const clear=()=>{q('[data-output]').textContent='';};
  function refresh(){
   source=snapshot();clear();
   q('[data-rows]').innerHTML=source.pitchers.map((p,i)=>`<fieldset class="capacity-arm" data-arm="${i}"><legend>${html(label(p.id))}</legend><label>狀態<select data-status aria-label="${html(label(p.id))}狀態"><option value="available">可用</option><option value="unavailable">不使用</option><option value="retired">已退場</option></select></label><label>剩餘打席容量<input data-capacity type="number" min="0" max="1000" inputmode="numeric" aria-label="${html(label(p.id))}剩餘容量" placeholder="請確認"></label><label>接續順位<select data-order aria-label="${html(label(p.id))}接續順位"><option value="">保留</option>${source.pitchers.map((_,n)=>`<option value="${n+1}">${n+1}</option>`).join('')}</select></label></fieldset>`).join('')||'<p class="mut">請先選取牛棚投手，再帶入。</p>';
  }
  q('[data-refresh]').onclick=refresh;
  element.addEventListener('toggle',()=>{if(element.open&&(!source||source.key!==snapshot().key))refresh();});
  element.addEventListener('input',clear);element.addEventListener('change',clear);
  q('[data-calculate]').onclick=()=>{
   try{
    if(!source||source.key!==snapshot().key)throw Error('牛棚或場上設定已變更，請重新帶入已選牛棚。');
    const target=q('[data-target]');if(target.value===''||!target.checkValidity()||Number(target.value)<1)throw Error('請填寫正整數的目標打席數。');
    const ordered=[],pitchers=[...element.querySelectorAll('[data-arm]')].map((row,i)=>{
     const status=row.querySelector('[data-status]').value,cap=row.querySelector('[data-capacity]'),order=row.querySelector('[data-order]').value;
     if(cap.value!==''&&!cap.checkValidity())throw Error('剩餘容量請填寫 0–1000 的整數。');
     if(order)ordered.push({id:source.pitchers[i].id,order:Number(order)});
     return {id:source.pitchers[i].id,available:status==='available',retired:status==='retired',remaining:cap.value===''?null:Number(cap.value)};
    });
    if(new Set(ordered.map(x=>x.order)).size!==ordered.length)throw Error('接續順位不可重複。');
    const r=BullpenPlan.plan({target:Number(target.value),pitchers,order:ordered.sort((a,b)=>a.order-b.order).map(x=>x.id)});
    q('[data-output]').innerHTML=`<p><strong>${r.complete?'容量足夠':`尚缺 ${r.uncovered} 打席容量`}</strong> · 已涵蓋 ${r.covered}／${r.target} 打席</p><ol>${r.allocations.filter(p=>p.used).map(p=>`<li>${html(label(p.id))}：安排 ${p.assigned} 打席，剩餘 ${p.remaining}</li>`).join('')}</ol><p>保留：${r.reserve.map(p=>`${html(label(p.id))}（${p.remaining===null?'容量待確認':p.remaining+' 打席'}）`).join('、')||'無'}</p><small class="mut">${html(r.assumption)}</small>`;
   }catch(e){q('[data-output]').textContent=e.message;}
  };
 }
 root.BullpenPlanUI={mount};
})(typeof window!=='undefined'?window:globalThis);
