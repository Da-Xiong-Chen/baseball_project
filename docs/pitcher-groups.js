/* Local shortlist presets only; never alter model values. */
(function(root) {
  const prefix='cpbl-pitcher-groups-v2:', legacy='cpbl-pitcher-groups-v1:';
  function sanitize(rows) {
    if (!Array.isArray(rows)) return [];
    const seen=new Set();
    return rows.filter(g=>g && typeof g.name==='string' && g.name.trim() &&
      g.name.length<=30 && Array.isArray(g.members) && g.members.length &&
      g.members.every(n=>typeof n==='string' && n.length<=100) &&
      !seen.has(g.name) && seen.add(g.name)).slice(0,30)
      .map(g=>({name:g.name,members:[...new Set(g.members)]}));
  }
  function read(storage,team) {
    try {
      const saved=storage.getItem(prefix+team);
      return sanitize(saved != null ? JSON.parse(saved).groups :
        JSON.parse(storage.getItem(legacy+team)||'[]'));
    } catch {return [];}
  }
  function write(storage,team,groups,selected='') {
    try {
      const data=JSON.stringify({groups,selected});
      storage.setItem(prefix+team,data);
      return storage.getItem(prefix+team)===data;
    } catch {return false;}
  }
  const closers={'中信兄弟':'吳俊偉','台鋼雄鷹':'林詩翔','味全龍':'陳冠偉','富邦悍將':'曾峻岳','樂天桃猿':'陳柏豪','統一7-ELEVEn獅':'陳韻文'};
  function defaults(pitchers,team) {
    const relievers=pitchers.filter(p=>p.role==='後援')
      .sort((a,b)=>Number(b.name===closers[team])-Number(a.name===closers[team]) ||
        (b.games||0)-(a.games||0)||a.name.localeCompare(b.name,'zh-Hant'));
    const split=Math.min(3,Math.max(1,relievers.length-1));
    return [{name:'勝投組',members:relievers.slice(0,split).map(p=>p.name)},
      {name:'敗投組',members:relievers.slice(split).map(p=>p.name)}].filter(g=>g.members.length);
  }
  function load(storage,team,pitchers) {
    let groups=read(storage,team);
    try {if(storage.getItem(prefix+team)!=null)return groups;}catch {}
    for(const group of defaults(pitchers,team)) if(!groups.some(g=>g.name===group.name)&&groups.length<30)groups.push(group);
    return groups;
  }
  function membership(group,available) {
    const names=new Set(available);
    return {selected:group.members.filter(n=>names.has(n)),missing:group.members.filter(n=>!names.has(n))};
  }
  function mount({element,list,team,pitchers,changed,storage}) {
    if(!storage){try{storage=root.localStorage;}catch{}}
    let groups=load(storage,team,pitchers);
    const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    element.innerHTML=`<div class="pitcher-group-select"><label class="f" for="pitcherGroupSelect">投手群組</label><div class="pitcher-group-actions"><select id="pitcherGroupSelect"></select><button type="button" class="link" id="pitcherGroupApply">套用</button><button type="button" class="link" id="pitcherGroupNew">新增</button></div></div><details class="pitcher-group-editor"><summary>編輯群組</summary><form id="pitcherGroupForm"><label class="f" for="pitcherGroupName">群組名稱</label><input id="pitcherGroupName" type="text" maxlength="30" required placeholder="例如：勝投組"><p class="mut">2025 後援範本，非官方分組；可自行調整。</p><div class="checklist group-members" aria-label="群組成員"></div><div class="pitcher-group-actions"><button type="submit" class="link" id="pitcherGroupSave">儲存群組</button><button type="button" class="link" id="pitcherGroupDelete">刪除群組</button></div></form></details><p class="pitcher-group-status" role="status"></p>`;
    const q=s=>element.querySelector(s),select=q('select'),name=q('#pitcherGroupName'),editor=q('details');
    let editing='',draft=new Set();
    const tell=text=>{q('[role=status]').textContent=text;};
    const boxes=()=>Array.from(list.querySelectorAll('input[type=checkbox]'));
    const showMembers=()=>{
      const known=new Set(pitchers.map(p=>p.name));
      q('.group-members').innerHTML=pitchers.map(p=>`<label><input type="checkbox" value="${esc(p.name)}" ${draft.has(p.name)?'checked':''}>${esc(p.name)}<span class="meta">${esc(p.role)}</span></label>`).join('')+
        [...draft].filter(n=>!known.has(n)).map(n=>`<label><input type="checkbox" value="${esc(n)}" checked>${esc(n)}<span class="meta">未收錄</span></label>`).join('');
    };
    const render=(selected='')=>{
      select.replaceChildren(new Option('選擇群組', ''));
      groups.forEach(g=>select.add(new Option(g.name+' · '+g.members.length+' 人',g.name)));
      select.value=selected;
      q('#pitcherGroupApply').disabled=!selected;
      q('#pitcherGroupDelete').disabled=!selected;
    };
    const choose=()=>{
      const group=groups.find(g=>g.name===select.value);
      editing=group?.name||'';name.value=editing;
      draft=new Set(group?.members||[]);showMembers();
      q('#pitcherGroupApply').disabled=!group;q('#pitcherGroupDelete').disabled=!group;
      tell(group?group.members.join('、'):'');
    };
    q('.group-members').onchange=e=>{
      if(e.target.type==='checkbox'){if(e.target.checked)draft.add(e.target.value);else draft.delete(e.target.value);}
    };
    select.onchange=choose;
    q('#pitcherGroupNew').onclick=()=>{
      render();editing='';name.value='';draft=new Set();showMembers();
      editor.open=true;name.focus();tell('命名並勾選群組成員。');
    };
    q('#pitcherGroupApply').onclick=()=>{
      const group=groups.find(g=>g.name===select.value);if(!group)return;
      const {selected,missing}=membership(group,boxes().map(i=>i.value));
      if(!selected.length){tell('此組沒有可選投手，請編輯成員。');return;}
      const chosen=new Set(selected);boxes().forEach(i=>{i.checked=chosen.has(i.value);});changed();
      tell('已套用 '+group.name+' · '+selected.length+' 人'+(missing.length?'；未收錄：'+missing.join('、'):'，可再微調。'));
    };
    q('form').onsubmit=e=>{
      e.preventDefault();
      const title=name.value.trim(),members=[...draft];
      if(!title||title.length>30){tell('名稱請填寫 1–30 字。');name.focus();return;}
      if(!members.length){tell('請勾選至少一位群組成員。');return;}
      if(groups.some(g=>g.name===title&&g.name!==editing)){tell('名稱已存在，請選取該組編輯。');return;}
      if(!editing&&groups.length>=30){tell('最多建立 30 組。');return;}
      const next=groups.filter(g=>g.name!==editing).concat({name:title,members});
      if(!write(storage,team,next,title)){tell('儲存失敗，請確認瀏覽器允許網站儲存，再重試；成員仍保留。');return;}
      groups=next;render(title);editing=title;tell('已儲存 '+title+' · '+members.length+' 人（此瀏覽器）。');
    };
    q('#pitcherGroupDelete').onclick=()=>{
      if(!editing)return;
      const title=editing,next=groups.filter(g=>g.name!==title);
      if(!write(storage,team,next)){tell('刪除失敗，請重試。');return;}
      groups=next;render();choose();tell('已刪除 '+title+'，今日勾選不變。');
    };
    let selected=groups[0]?.name||'';
    try {const old=JSON.parse(storage.getItem(prefix+team)||'null');if(groups.some(g=>g.name===old?.selected))selected=old.selected;}catch{}
    render(selected);choose();
  }
  root.PitcherGroups={read,write,defaults,load,membership,mount};
  if(typeof module!=='undefined')module.exports=root.PitcherGroups;
})(typeof window!=='undefined'?window:globalThis);
