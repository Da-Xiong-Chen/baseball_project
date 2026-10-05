/* Local candidate presets; never changes model values or availability rules. */
(function(root) {
  const names=['勝投組','敗投組','自訂義群組'], prefix='cpbl-pitcher-groups-v3:';
  const sessions=new Map();
  const copy=g=>({name:g.name,members:[...g.members]});
  function sanitize(rows) {
    if(!Array.isArray(rows)) throw Error('格式不完整');
    const seen=new Set();
    return rows.filter(g=>g&&typeof g.name==='string'&&g.name.trim()&&g.name.length<=30&&Array.isArray(g.members)&&g.members.every(n=>typeof n==='string'&&n.length<=100)&&!seen.has(g.name)&&seen.add(g.name))
      .map(g=>({name:g.name,members:[...new Set(g.members)]}));
  }
  function read(storage,team) {
    const raw=storage.getItem(prefix+team);
    if(raw==null)return [];
    const data=JSON.parse(raw);
    if(data.version!==3||!Array.isArray(data.groups))throw Error('群組格式無效');
    const groups=sanitize(data.groups);
    if(groups.length!==3||!names.every(n=>groups.some(g=>g.name===n)))throw Error('群組格式無效');
    return names.map(n=>groups.find(g=>g.name===n));
  }
  function write(storage,team,groups,selected=names[0]) {
    try {
      const rows=sanitize(groups);
      if(rows.length!==3||!names.every(n=>rows.some(g=>g.name===n)))return false;
      const data=JSON.stringify({version:3,groups:names.map(n=>rows.find(g=>g.name===n)),selected});
      storage.setItem(prefix+team,data);return storage.getItem(prefix+team)===data;
    } catch{return false;}
  }
  const closers={'中信兄弟':'吳俊偉','台鋼雄鷹':'林詩翔','味全龍':'陳冠偉','富邦悍將':'曾峻岳','樂天桃猿':'陳柏豪','統一7-ELEVEn獅':'陳韻文'};
  function defaults(pitchers,team) {
    const relievers=pitchers.filter(p=>p.role==='後援').slice().sort((a,b)=>Number(b.name===closers[team])-Number(a.name===closers[team])||(b.games||0)-(a.games||0)||a.name.localeCompare(b.name,'zh-Hant'));
    const split=Math.min(3,Math.max(1,relievers.length-1));
    return [{name:names[0],members:relievers.slice(0,split).map(p=>p.name)},{name:names[1],members:relievers.slice(split).map(p=>p.name)},{name:names[2],members:[]}];
  }
  function loadState(storage,team,pitchers) {
    const fallback=defaults(pitchers,team);
    try {
      if(!storage)throw Error('無法取得網站儲存');
      const existing=read(storage,team);
      if(existing.length) {
        const saved=JSON.parse(storage.getItem(prefix+team));
        let preserved=[];
        try { const older=storage.getItem('cpbl-pitcher-groups-v2:'+team);preserved=sanitize(older?JSON.parse(older).groups:JSON.parse(storage.getItem('cpbl-pitcher-groups-v1:'+team)||'[]')); } catch {}
        return {groups:existing,legacy:preserved,selected:names.includes(saved.selected)?saved.selected:names[0],error:''};
      }
      const raw=storage.getItem('cpbl-pitcher-groups-v2:'+team), old=raw==null?null:JSON.parse(raw);
      const legacy=sanitize(old?old.groups:JSON.parse(storage.getItem('cpbl-pitcher-groups-v1:'+team)||'[]'));
      const custom=legacy.filter(g=>!names.includes(g.name));
      const chosen=legacy.find(g=>g.name===names[2])||custom.find(g=>g.name===old?.selected)||(custom.length===1?custom[0]:null);
      const groups=fallback.map(g=>copy(legacy.find(o=>o.name===g.name)||(g.name===names[2]&&chosen?{...chosen,name:names[2]}:g)));
      const selected=names.includes(old?.selected)?old.selected:chosen?names[2]:names[0];
      return {groups,legacy,selected,error:write(storage,team,groups,selected)?'':'儲存不可用；可手動選人，群組尚未保存。'};
    } catch{return {groups:fallback,legacy:[],selected:names[0],error:'無法讀取群組；原設定保留，可手動選人。',blocked:true};}
  }
  const load=(storage,team,pitchers)=>loadState(storage,team,pitchers).groups;
  function membership(group,available) {
    const known=new Set(available);return {selected:group.members.filter(n=>known.has(n)),missing:group.members.filter(n=>!known.has(n))};
  }
  const equal=(a,b)=>a.size===b.size&&[...a].every(n=>b.has(n));
  function mount({element,list,team,pitchers,changed,availability,current=()=>'',storage}) {
    if(!storage){try{storage=root.localStorage;}catch{}}
    let state=loadState(storage,team,pitchers),groups=state.groups;
    if(!sessions.has(team))sessions.set(team,{drafts:new Map(),selected:state.selected,applied:null});
    const session=sessions.get(team);
    const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    element.innerHTML=`<label class="f" for="pitcherGroupSelect">投手群組</label><div class="pitcher-group-actions"><select id="pitcherGroupSelect"></select><button type="button" class="link" id="pitcherGroupApply">套用</button></div><details class="pitcher-group-editor"><summary>編輯群組成員</summary><p class="mut">2025 後援範本，非官方分組。</p><div class="checklist group-members" aria-label="群組成員"></div><label class="legacy-import hidden">從舊群組帶入<select aria-label="從舊群組帶入"><option value="">選擇舊群組</option></select></label><div class="pitcher-group-actions"><button type="button" class="link" id="pitcherGroupSave">儲存</button><button type="button" class="link" id="pitcherGroupCancel">取消修改</button><span class="draft-state" role="status"></span></div></details><p class="pitcher-group-status" role="status"></p>${availability?'':'<div class="today-availability" aria-live="polite"></div>'}`;
    const q=s=>element.querySelector(s),select=q('#pitcherGroupSelect'),status=q('.pitcher-group-status'),availabilityBox=availability||q('.today-availability');
    const boxes=()=>Array.from(list.querySelectorAll('input[type=checkbox]'));
    const group=()=>groups.find(g=>g.name===select.value);
    const draft=()=>{if(!session.drafts.has(select.value))session.drafts.set(select.value,new Set(group().members));return session.drafts.get(select.value);};
    const dirty=()=>!equal(draft(),new Set(group().members));
    const effective=()=>new Set(boxes().filter(i=>i.checked&&i.value!==current()).map(i=>i.value));
    function feedback(message='') {
      boxes().forEach(input=>{input.disabled=input.value===current();input.title=input.disabled?'場上投手，固定為比較基準':'';});
      const selected=[...effective()],count=selected.length, applied=session.applied;
      const namesOpen=availabilityBox.querySelector('.availability-more')?.open;
      availabilityBox.innerHTML=`<div class="today-availability-head"><strong>今日勾選 ${count} 人</strong><span>請排除休息、未登錄與已退場者</span></div><div class="today-availability-names">${selected.length?selected.slice(0,4).map(name=>`<span class="chip">${esc(name)}</span>`).join('')+(selected.length>4?`<details class="availability-more" ${namesOpen?'open':''}><summary>另 ${selected.length-4} 人</summary><div class="availability-extra">${selected.slice(4).map(name=>`<span class="chip">${esc(name)}</span>`).join('')}</div></details>`:''):'<span>未勾選候選，僅比較續投</span>'}</div>`;
      const same=applied&&equal(effective(),new Set(applied.members.filter(n=>n!==current())));
      status.textContent=message||state.error||(applied?applied.name+' · '+(same?'已套用':'已微調'):'');
    }
    function updateDraft() {
      session.dirty=[...session.drafts].some(([name,set])=>!equal(set,new Set(groups.find(g=>g.name===name).members)));
      q('.draft-state').textContent=dirty()?'尚未儲存':'';
      q('#pitcherGroupSave').disabled=!dirty()&&!state.error;
      q('#pitcherGroupCancel').disabled=!dirty();
      q('#pitcherGroupApply').disabled=!group().members.length;
    }
    function choose() {
      session.selected=select.value;
      const known=new Set(pitchers.map(p=>p.name)), members=draft();
      q('.group-members').innerHTML=pitchers.map(p=>`<label><input type="checkbox" value="${esc(p.name)}" ${members.has(p.name)?'checked':''}>${esc(p.name)}<span class="meta">${esc(p.role)}</span></label>`).join('')+[...members].filter(n=>!known.has(n)).map(n=>`<label><input type="checkbox" value="${esc(n)}" checked>${esc(n)}<span class="meta">未收錄</span></label>`).join('');
      updateDraft();feedback(group().members.length?'':'尚未設定成員；可在下方編輯。');
    }
    const render=()=>{select.replaceChildren();groups.forEach(g=>select.add(new Option(g.name+' · '+g.members.length+' 人',g.name)));select.value=session.selected;choose();};
    select.onchange=choose;
    q('.group-members').onchange=e=>{if(e.target.type==='checkbox'){e.target.checked?draft().add(e.target.value):draft().delete(e.target.value);updateDraft();}};
    q('#pitcherGroupSave').onclick=()=>{
      if(state.blocked){const hadChanges=dirty(),retry=loadState(storage,team,pitchers);if(retry.blocked){feedback('原設定無法讀取；請先恢復網站儲存後重試，草稿仍保留。');return;}state=retry;groups=retry.groups;if(!hadChanges)session.drafts.set(select.value,new Set(group().members));render();feedback(hadChanges?'已恢復原設定；請核對草稿後再次儲存。':'已恢復原設定。');return;}
      const next=groups.map(g=>g.name===select.value?{name:g.name,members:[...draft()]}:copy(g));
      if(!write(storage,team,next,select.value)){feedback('儲存失敗；草稿保留，請確認網站儲存後重試。');return;}
      groups=next;state.error='';render();feedback('已儲存 '+select.value+'（此網站／瀏覽器）');
    };
    q('#pitcherGroupCancel').onclick=()=>{session.drafts.set(select.value,new Set(group().members));choose();};
    q('#pitcherGroupApply').onclick=()=>{
      if(dirty()){feedback('此組尚未儲存；請先儲存或取消修改。');q('details').open=true;return;}
      const {selected,missing}=membership(group(),boxes().map(i=>i.value));
      if(!selected.length){feedback('此組沒有收錄的可選投手；請編輯成員。');return;}
      const chosen=new Set(selected);boxes().forEach(i=>{i.checked=chosen.has(i.value);});
      session.applied={name:select.value,members:selected};changed();feedback(missing.length?'已套用 '+select.value+'；'+missing.length+' 人未收錄':'');
    };
    const old=state.legacy.filter(g=>!names.includes(g.name));
    if(old.length){q('.legacy-import').classList.remove('hidden');old.forEach((g,i)=>q('.legacy-import select').add(new Option(g.name,String(i))));q('.legacy-import select').onchange=e=>{if(e.target.value==='')return;select.value=names[2];session.selected=names[2];session.drafts.set(names[2],new Set(old[Number(e.target.value)].members));choose();};}
    list.onchange=()=>{changed();feedback();};
    render();
    return {refresh:()=>feedback()};
  }
  if(root.addEventListener)root.addEventListener('beforeunload',e=>{
    if([...sessions.values()].some(s=>s.dirty)){e.preventDefault();e.returnValue='';}
  });
  root.PitcherGroups={read,write,defaults,load,loadState,membership,mount,names};
  if(typeof module!=='undefined')module.exports=root.PitcherGroups;
})(typeof window!=='undefined'?window:globalThis);
