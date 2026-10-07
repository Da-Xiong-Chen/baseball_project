/* Shared own-team configuration. No evaluation formulas live here. */
(function(root){
  'use strict';
  const POS={C:'捕手','1B':'一壘','2B':'二壘','3B':'三壘',SS:'游擊',LF:'左外野',CF:'中外野',RF:'右外野',DH:'指定打擊'};
  const clone=x=>JSON.parse(JSON.stringify(x));
  const empty=()=>({slots:Object.keys(POS).map(pos=>({name:'',pos})),pitcher:''});
  function assignPlayer(config,index,name,fromField=false){
    if(index==='P'){config.pitcher=name;return;}
    const other=config.slots.findIndex(s=>s.name===name);
    if(other===index)return;
    if(other!==-1&&fromField){[config.slots[index].pos,config.slots[other].pos]=[config.slots[other].pos,config.slots[index].pos];return;}
    const old=config.slots[index].name;if(other!==-1)config.slots[other].name=old;config.slots[index].name=name;
  }
  function validate(config,roster){
    const errors=[];
    if(!config||!Array.isArray(config.slots)||config.slots.length!==9)return ['請設定完整九棒。'];
    const names=config.slots.map(x=>x?.name),positions=config.slots.map(x=>x?.pos);
    if(names.some(n=>!n))errors.push('九個棒次都需要球員。');
    if(names.filter(Boolean).length!==new Set(names.filter(Boolean)).size)errors.push('同一球員不能占兩個棒次。');
    if(positions.some(p=>!POS[p])||new Set(positions).size!==9)errors.push('每個守位與 DH 各需一人。');
    if(names.some(n=>n&&!roster.hitters.some(h=>h.name===n)))errors.push('有球員不在此隊資料中，請重新選擇。');
    if(!roster.pitchers.some(p=>p.name===config.pitcher))errors.push('請選擇場上投手。');
    if(config.pitcher&&names.includes(config.pitcher))errors.push('投打雙向或特殊 DH 配置尚未支援，請改用手動評估。');
    return errors;
  }
  function validState(s){
    const shape=c=>c&&Array.isArray(c.slots)&&c.slots.length===9&&c.slots.every(x=>x&&typeof x.name==='string'&&POS[x.pos])&&typeof c.pitcher==='string';
    return s&&s.version===1&&s.season===2025&&shape(s.draft)&&(!s.confirmed||shape(s.confirmed));
  }
  const states=new Map();let options,teamName='',roster,pickerIndex=null,pickerField=false,returnFocus=null;
  const q=s=>options.element.querySelector(s);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const key=t=>'cpbl-lineup-2025-v1:'+t;
  function get(t){
    if(!states.has(t)){
      let s={version:1,season:2025,draft:empty(),confirmed:null};
      try{const raw=localStorage.getItem(key(t));if(raw){const parsed=JSON.parse(raw);if(!validState(parsed))throw Error('invalid');s={version:1,season:2025,draft:parsed.draft,confirmed:parsed.confirmed||null};}}
      catch{s.storageError=true;}
      states.set(t,s);
    }
    return states.get(t);
  }
  function persist(){
    const s=get(teamName);
    if(s.storageError){message('本次可用；舊資料無法讀取，未覆寫瀏覽器記錄。');return false;}
    try{const raw=JSON.stringify(s);localStorage.setItem(key(teamName),raw);if(localStorage.getItem(key(teamName))!==raw)throw Error('not saved');return true;}
    catch{message('本次可用，但無法保存到瀏覽器。');return false;}
  }
  function current(t){const s=get(t);return s.confirmed?clone(s.confirmed):null;}
  function message(text,error=false){q('#lineupMessage').textContent=text;q('#lineupMessage').setAttribute('role',error?'alert':'status');}
  function draftChanged(){const saved=persist();render();message(saved?'草稿已保存；按「套用配置」更新評估頁。':'草稿保留在本次頁面，無法保存到瀏覽器；按「套用配置」更新評估頁。');}
  function render(){
    const s=get(teamName),c=s.draft;
    q('#lineupTeam').value=teamName;
    q('#lineupStatus').textContent=(s.confirmed?'已有套用配置':'尚未設定')+' · 已填 '+c.slots.filter(x=>x.name).length+'/9 棒';
    q('#lineupRows').innerHTML=c.slots.map((slot,i)=>`<div class="lineup-row"><strong class="lineup-order">${i+1}</strong><button type="button" class="lineup-name" data-pick="${i}" aria-label="第 ${i+1} 棒選擇球員">${esc(slot.name||'選擇球員')}<span aria-hidden="true">⌄</span></button><select data-position="${i}" aria-label="第 ${i+1} 棒守位">${Object.entries(POS).map(([p,label])=>`<option value="${p}" ${slot.pos===p?'selected':''}>${label}</option>`).join('')}</select><div class="lineup-move"><button type="button" data-move="${i}" data-step="-1" aria-label="第 ${i+1} 棒上移" ${i===0?'disabled':''}>↑</button><button type="button" data-move="${i}" data-step="1" aria-label="第 ${i+1} 棒下移" ${i===8?'disabled':''}>↓</button></div></div>`).join('');
    q('#lineupPitcherName').textContent=c.pitcher||'選擇投手';
    options.element.querySelectorAll('[data-field]').forEach(b=>{
      const pos=b.dataset.field,slot=c.slots.find(s=>s.pos===pos),name=pos==='P'?c.pitcher:slot?.name;
      b.innerHTML=`<span>${pos==='P'?'投手':POS[pos]}</span><strong>${esc(name||'＋ 選擇')}</strong>`;
      b.setAttribute('aria-label',(pos==='P'?'投手':POS[pos])+'配置：'+(name||'尚未設定'));
    });
    const warnings=c.slots.filter(s=>s.name&&s.pos!=='DH'&&!roster.hitters.find(h=>h.name===s.name)?.positions?.[s.pos]);
    q('#lineupWarnings').textContent=warnings.length?'守位經驗未收錄：'+warnings.map(s=>s.name+'（'+POS[s.pos]+'）').join('、')+'。請依現場確認。':'';
  }
  function pickerRender(){
    const c=get(teamName).draft,list=pickerIndex==='P'?roster.pitchers:roster.hitters;
    const filter=q('#lineupSearch').value;
    q('#lineupPlayerList').innerHTML=list.filter(p=>options.matches(p.name,teamName,filter)).map(p=>`<button type="button" data-player="${esc(p.name)}"><strong>${esc(p.name)}</strong><span>${p.hand==='L'?'左':p.hand==='R'?'右':'兩'}${pickerIndex==='P'?'投':'打'}${c.slots.some(s=>s.name===p.name)?' · 九棒中':''}</span></button>`).join('')||'<p>沒有符合的球員。</p>';
  }
  function openPicker(index,button){
    if(options.element.hasAttribute('aria-busy'))return;
    pickerIndex=index;pickerField=button.hasAttribute?.('data-field')||false;returnFocus=button;
    q('#lineupPickerTitle').textContent=index==='P'?'選擇場上投手':'選擇第 '+(index+1)+' 棒球員';q('#lineupSearch').value='';pickerRender();q('#lineupPicker').showModal();q('#lineupSearch').focus();
  }
  async function selectTeam(name){
    const token=++selectTeam.generation;
    options.element.setAttribute('aria-busy','true');
    q('#lineupApply').disabled=true;
    try{const next=await options.team(name);if(token!==selectTeam.generation)return;teamName=name;roster=next;render();message(get(name).storageError?'保存記錄無法讀取；本次仍可設定。':'請依實際出賽名單設定。');}
    catch{message('球員名單載入失敗，請重新選隊。',true);}
    finally{if(token===selectTeam.generation){options.element.removeAttribute('aria-busy');q('#lineupApply').disabled=teamName!==name;}}
  }
  selectTeam.generation=0;
  function mount(o){
    options=o;q('#lineupTeam').innerHTML=o.teams.map(t=>`<option>${esc(t)}</option>`).join('');
    q('#lineupTeam').onchange=e=>selectTeam(e.target.value);
    q('#lineupSearch').oninput=pickerRender;
    q('#lineupPickerClose').onclick=()=>q('#lineupPicker').close();
    q('#lineupPicker').addEventListener('close',()=>{const target=returnFocus?.dataset.pick!==undefined?q(`[data-pick="${returnFocus.dataset.pick}"]`):returnFocus;target?.focus();});
    q('#lineupPlayerList').onclick=e=>{const button=e.target.closest('[data-player]');if(!button||button.disabled)return;assignPlayer(get(teamName).draft,pickerIndex,button.dataset.player,pickerField);q('#lineupPicker').close();draftChanged();};
    options.element.addEventListener('click',e=>{
      const pick=e.target.closest('[data-pick]'),move=e.target.closest('[data-move]');
      if(pick)openPicker(Number(pick.dataset.pick),pick);
      if(move){const c=get(teamName).draft,i=Number(move.dataset.move),j=i+Number(move.dataset.step);if(j>=0&&j<9){[c.slots[i],c.slots[j]]=[c.slots[j],c.slots[i]];draftChanged();q(`[data-move="${j}"][data-step="${move.dataset.step}"]`).focus();}}
    });
    options.element.querySelectorAll('[data-field]').forEach(button=>button.onclick=()=>{const pos=button.getAttribute('data-field');openPicker(pos==='P'?'P':get(teamName).draft.slots.findIndex(s=>s.pos===pos),button);});
    q('#lineupRows').onchange=e=>{if(!e.target.matches('[data-position]'))return;const c=get(teamName).draft,i=Number(e.target.dataset.position),pos=e.target.value,j=c.slots.findIndex(s=>s.pos===pos);if(j!==-1)c.slots[j].pos=c.slots[i].pos;c.slots[i].pos=pos;draftChanged();};
    q('#lineupPitcherPick').onclick=e=>openPicker('P',e.currentTarget);
    q('#lineupApply').onclick=async()=>{
      const s=get(teamName),errors=validate(s.draft,roster);
      if(errors.length){message(errors.join(' '),true);return;}
      const old=s.confirmed,pitcherChanged=!old||old.pitcher!==s.draft.pitcher;
      s.confirmed=clone(s.draft);const saved=persist();render();
      await o.applied(teamName,{pitcherSelected:pitcherChanged,resetPitchCount:pitcherChanged});
      message(saved?'配置已套用並保存。':'配置已套用；本次可用，但無法保存到瀏覽器。');
    };
  }
  const api={mount,selectTeam,current,validate,empty,validState,assignPlayer};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.LineupBoard=api;
})(typeof window!=='undefined'?window:globalThis);
