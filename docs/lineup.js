/* Shared own-team configuration. No evaluation formulas live here. */
(function(root){
  'use strict';
  const POS={C:'捕手','1B':'一壘','2B':'二壘','3B':'三壘',SS:'游擊',LF:'左外野',CF:'中外野',RF:'右外野',DH:'指定打擊'};
  let runtimeSeason=2025;
  function setRuntime(config){if(!Number.isInteger(config.season))throw Error('Invalid season');if(runtimeSeason!==config.season){states.clear();defaults={};defaultsMeta={};}runtimeSeason=config.season;}
  const clone=x=>JSON.parse(JSON.stringify(x));
  function migrateIdentity(config,team){
    if(!config)return false;
    const canonical={'樂天桃猿':'林子崴〔樂天〕','統一7-ELEVEn獅':'林子崴〔統一〕'}[team];
    if(!canonical)return false;
    let changed=false;
    const name=n=>{if(n==='林子崴'){changed=true;return canonical;}return n;};
    config.pitcher=name(config.pitcher);config.slots.forEach(s=>{s.name=name(s.name);});
    if(config.unavailable)config.unavailable=[...new Set(config.unavailable.map(name))];
    return changed;
  }
  const empty=()=>({slots:Object.keys(POS).map(pos=>({name:'',pos})),pitcher:''});
  function swapFieldingPositions(first,second){
    if(first===second)return;
    const pending=first.fieldingPending;
    [first.pos,second.pos]=[second.pos,first.pos];
    if(second.fieldingPending)first.fieldingPending=true;else delete first.fieldingPending;
    if(pending)second.fieldingPending=true;else delete second.fieldingPending;
  }
  function assignPlayer(config,index,name,fromField=false){
    if(index==='P'){config.pitcher=name;return;}
    const other=config.slots.findIndex(s=>s.name===name);
    if(other===index)return;
    if(other!==-1&&fromField){swapFieldingPositions(config.slots[index],config.slots[other]);return;}
    const old=config.slots[index].name;if(other!==-1)config.slots[other].name=old;config.slots[index].name=name;
  }
  function swapPlayers(config,a,b,mode){
    if(!['field','order'].includes(mode)||!Number.isInteger(a)||!Number.isInteger(b)||a<0||b<0||a>8||b>8||a===b||!config.slots[a].name||!config.slots[b].name)return false;
    if(mode==='field')swapFieldingPositions(config.slots[a],config.slots[b]);
    else [config.slots[a],config.slots[b]]=[config.slots[b],config.slots[a]];
    return true;
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
    const unavailable=config.unavailable||[];
    if(unavailable.some(n=>names.includes(n)||n===config.pitcher))errors.push('已退場／不可用球員不能仍配置在場上。');
    return errors;
  }
  function validState(s){
    const shape=c=>c&&Array.isArray(c.slots)&&c.slots.length===9&&c.slots.every(x=>x&&typeof x.name==='string'&&POS[x.pos]&&(x.fieldingPending===undefined||x.fieldingPending===true))&&new Set(c.slots.map(x=>x.pos)).size===9&&typeof c.pitcher==='string'&&(!c.unavailable||(Array.isArray(c.unavailable)&&c.unavailable.every(n=>typeof n==='string')&&new Set(c.unavailable).size===c.unavailable.length));
    return s&&[1,2].includes(s.version)&&s.season===runtimeSeason&&shape(s.draft)&&(!s.confirmed||shape(s.confirmed));
  }
  function readBackup(text,team,teamRoster){
    const data=JSON.parse(text);
    if(data?.type!=='baseball-lineup'||data.team!==team||!validState(data.state))
      throw Error('檔案的球隊、球季或名單格式不符。');
    const imported=data.state.draft;
    const hitters=new Set(teamRoster.hitters.map(player=>player.name));
    const pitchers=new Set(teamRoster.pitchers.map(player=>player.name));
    if(imported.slots.some(slot=>!Object.hasOwn(POS,slot.pos)||(slot.name&&!hitters.has(slot.name)))
      ||(imported.pitcher&&!pitchers.has(imported.pitcher))
      ||(imported.unavailable||[]).some(name=>!hitters.has(name)&&!pitchers.has(name)))
      throw Error('檔案含目前名單沒有的球員，或守位格式不符。');
    const inUse=imported.slots.filter(slot=>slot.name).map(slot=>slot.name);
    if(imported.pitcher)inUse.push(imported.pitcher);
    if(new Set(inUse).size!==inUse.length||inUse.some(name=>imported.unavailable?.includes(name)))
      throw Error('檔案中有人重複配置，或已退場球員仍在場上。');
    return clone(imported);
  }
  const states=new Map();let defaults={},defaultsMeta={},options,teamName='',roster,pickerIndex=null,pickerField=false,returnFocus=null;
  let swapMode=null,swapFirst=null,swapUndo=null;
  const q=s=>options.element.querySelector(s);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const label=n=>typeof PlayerIdentity!=='undefined'?PlayerIdentity.currentName(n):String(n??'');
  const key=t=>'cpbl-lineup-'+runtimeSeason+'-v1:'+t;
  function get(t){
    if(!states.has(t)){
      let s={version:2,season:runtimeSeason,draft:empty(),confirmed:null};
      let raw=null;
      try{raw=localStorage.getItem(key(t));if(raw){const parsed=JSON.parse(raw);if(!validState(parsed))throw Error('invalid');s={version:parsed.version,season:runtimeSeason,draft:parsed.draft,confirmed:parsed.confirmed||null,legacyRaw:raw};}s.savedRaw=raw;}
      catch{s.storageError=true;}
      const draftMigrated=typeof PlayerIdentity==='undefined'&&migrateIdentity(s.draft,t),confirmedMigrated=typeof PlayerIdentity==='undefined'&&migrateIdentity(s.confirmed,t);
      s.identityMigrated=draftMigrated||confirmedMigrated;
      // 預設名單只當作草稿；要按「套用配置」或「恢復預設名單」才進入依場上名單評估的球隊模式
      if(!raw&&!s.storageError&&defaults[t]){s.draft=clone(defaults[t]);s.isDefault=true;}
      states.set(t,s);
    }
    const s=states.get(t),r=typeof PlayerIdentity!=='undefined'&&PlayerIdentity.roster(t);
    if(r&&!s.identityChecked){
      const draft=PlayerIdentity.migrateLineup(s.draft,r),confirmed=PlayerIdentity.migrateLineup(s.confirmed,r);
      const unresolved=[...new Set([...draft.unresolved,...confirmed.unresolved])];
      if(s.legacyRaw&&(draft.changed||confirmed.changed||unresolved.length)){
        try{const backup=key(t)+':identity-backup';if(!localStorage.getItem(backup))localStorage.setItem(backup,s.legacyRaw);if(!localStorage.getItem(backup))throw Error('backup');}
        catch{s.storageError=true;}
      }
      s.draft=draft.value;s.confirmed=unresolved.length?null:confirmed.value;s.version=2;s.identityChecked=true;
      s.identityMigrated=draft.changed||confirmed.changed;s.identityUnresolved=unresolved;delete s.legacyRaw;
    }
    return s;
  }
  function persist(){
    const s=get(teamName);
    if(s.storageError)return 'unavailable';
    try{
      const storageKey=key(teamName);
      const raw=JSON.stringify({version:2,season:runtimeSeason,draft:s.draft,confirmed:s.confirmed});
      const latest=localStorage.getItem(storageKey);
      if(latest!==s.savedRaw&&latest!==raw)return 'conflict';
      if(latest!==raw)localStorage.setItem(storageKey,raw);
      if(localStorage.getItem(storageKey)!==raw)return 'unavailable';
      s.savedRaw=raw;
      return 'saved';
    }catch{return 'unavailable';}
  }
  function saveMessage(result,success,unavailable){
    if(result==='conflict')return '另一個分頁已更新名單。本分頁的變更僅保留在目前頁面，重新整理可讀取已保存的名單。';
    return result==='saved'?success:unavailable;
  }
  function current(t){const s=get(t);return s.confirmed&&(typeof PlayerIdentity==='undefined'||s.identityChecked)?clone(s.confirmed):null;}
  /* 改為不使用場上名單：保留草稿，評估頁回到可選所有球員 */
  function release(t){const s=get(t);if(!s.confirmed)return;s.confirmed=null;const prev=teamName;teamName=t;persist();teamName=prev;if(t===teamName&&options)render();}
  function message(text,error=false){q('#lineupMessage').textContent=text;q('#lineupMessage').setAttribute('role',error?'alert':'status');}
  function draftChanged(){delete get(teamName).isDefault;const saved=persist();render();message(saveMessage(saved,'草稿已保存；按「套用配置」更新評估頁。','草稿保留在本次頁面，無法保存到瀏覽器；按「套用配置」更新評估頁。'));return saved;}
  function resetSwap(){swapMode=null;swapFirst=null;swapUndo=null;}
  function focusSlot(i,mode){const c=get(teamName).draft;q(mode==='field'?`[data-field="${c.slots[i].pos}"]`:`[data-pick="${i}"]`)?.focus();}
  function swapSelect(i){
    const c=get(teamName).draft;if(!c.slots[i]?.name){message('請先選擇球員。',true);return;}
    if(swapFirst===i){swapFirst=null;render();focusSlot(i,swapMode);return;}
    if(swapFirst===null){swapFirst=i;render();focusSlot(i,swapMode);return;}
    const before=clone(c),a=swapFirst,names=label(c.slots[a].name)+'與'+label(c.slots[i].name);
    if(!swapPlayers(c,a,i,swapMode))return;
    const mode=swapMode;swapUndo=before;swapFirst=null;swapMode=null;const saved=draftChanged();[a,i].forEach(n=>q(mode==='field'?`[data-field="${c.slots[n].pos}"]`:`[data-pick="${n}"]`)?.classList.add('swap-updated'));focusSlot(i,mode);if(saved==='saved')message(names+'已互換'+(mode==='order'?'棒次':'守位')+'；套用後更新評估。');
  }
  function renderSwap(){
    ['field','order'].forEach(mode=>{const b=q(mode==='field'?'#lineupSwapField':'#lineupSwapOrder');b.setAttribute('aria-pressed',String(swapMode===mode));});
    q('#lineupSwapCancel').hidden=!swapMode;q('#lineupSwapUndo').hidden=!swapUndo;
    q('#lineupSwapHint').textContent=swapMode?(swapFirst===null?'選兩位球員互換'+(swapMode==='field'?'守位':'棒次')+'。':'已選 '+label(get(teamName).draft.slots[swapFirst].name)+'，再選一人；再點一次可取消選取。'):'';
    q('#lineupFieldHint').textContent=swapMode==='field'?q('#lineupSwapHint').textContent:'點守位選球員';
    q('#lineupOrderHint').textContent=swapMode==='order'?q('#lineupSwapHint').textContent:'↑↓ 調整棒次';
    options.element.querySelectorAll('[data-pick],[data-field]').forEach(b=>{const i=b.hasAttribute('data-field')?get(teamName).draft.slots.findIndex(s=>s.pos===b.dataset.field):Number(b.dataset.pick),selected=swapMode&&swapFirst===i&&((swapMode==='field')===b.hasAttribute('data-field'));b.classList.toggle('swap-selected',!!selected);b.setAttribute('aria-pressed',String(!!selected));});
  }
  function render(){
    const s=get(teamName),c=s.draft;
    q('#lineupTeam').value=teamName;
    q('#lineupStatus').textContent=(s.isDefault?'預設名單（'+runtimeSeason+' 最後 '+(defaultsMeta[teamName]?.games||30)+' 場先發）'+(s.confirmed?'':' · 尚未套用'):s.confirmed?(JSON.stringify(s.confirmed)===JSON.stringify(c)?'已有套用配置':'已套用配置 · 有未套用的修改'):(c.slots.some(x=>x.name)?'尚未套用':'尚未設定'))+' · 已填 '+c.slots.filter(x=>x.name).length+'/9 棒';
    q('#lineupRows').innerHTML=c.slots.map((slot,i)=>`<div class="lineup-row"><strong class="lineup-order">${i+1}</strong><button type="button" class="lineup-name" data-pick="${i}" aria-label="第 ${i+1} 棒選擇球員">${esc(label(slot.name)||'選擇球員')}<span aria-hidden="true">⌄</span></button><select data-position="${i}" aria-label="第 ${i+1} 棒守位">${Object.entries(POS).map(([p,label])=>`<option value="${p}" ${slot.pos===p?'selected':''}>${label}</option>`).join('')}</select><div class="lineup-move"><button type="button" data-move="${i}" data-step="-1" aria-label="第 ${i+1} 棒上移" ${i===0?'disabled':''}>↑</button><button type="button" data-move="${i}" data-step="1" aria-label="第 ${i+1} 棒下移" ${i===8?'disabled':''}>↓</button></div></div>`).join('');
    q('#lineupPitcherName').textContent=label(c.pitcher)||'選擇投手';
    const pending=c.slots.filter(slot=>slot.fieldingPending);
    q('#lineupApply').textContent=pending.length?'確認接守並套用':'套用配置';
    options.element.querySelectorAll('[data-field]').forEach(b=>{
      b.classList.remove('swap-updated');
      const pos=b.dataset.field,slot=c.slots.find(s=>s.pos===pos),name=pos==='P'?c.pitcher:slot?.name;
      const status=slot?.fieldingPending?'（接守待確認）':'';
      b.innerHTML=`<span>${pos==='P'?'投手':POS[pos]}${status}</span><strong>${esc(label(name)||'＋ 選擇')}</strong>`;
      b.setAttribute('aria-label',(pos==='P'?'投手':POS[pos])+status+'配置：'+(label(name)||'尚未設定'));
    });
    renderSwap();
    const warnings=c.slots.filter(s=>s.name&&s.pos!=='DH'&&!roster.hitters.find(h=>h.name===s.name)?.positions?.[s.pos]);
    q('#lineupWarnings').textContent=[
      pending.length?'請確認接守：'+pending.map(s=>POS[s.pos]).join('、')+'。可調整球員或守位後套用。':'',
      warnings.length?'守位經驗未收錄：'+warnings.map(s=>label(s.name)+'（'+POS[s.pos]+'）').join('、')+'。請依現場確認。':'',
    ].filter(Boolean).join(' ');
    q('#lineupUnavailable').innerHTML=[...roster.hitters,...roster.pitchers].map(p=>`<label class="toggle"><input type="checkbox" data-lineup-unavailable="${esc(p.name)}" ${(c.unavailable||[]).includes(p.name)?'checked':''}>${esc(label(p.name))}</label>`).join('');
    q('#lineupUnavailable').onchange=e=>{
      const name=e.target.dataset.lineupUnavailable;if(!name)return;
      const excluded=new Set(c.unavailable||[]);if(e.target.checked)excluded.add(name);else excluded.delete(name);
      c.unavailable=[...excluded];draftChanged();
      [...options.element.querySelectorAll('[data-lineup-unavailable]')].find(input=>input.dataset.lineupUnavailable===name)?.focus();
    };
  }
  function pickerRender(){
    const c=get(teamName).draft,list=pickerIndex==='P'?roster.pitchers:roster.hitters;
    const filter=q('#lineupSearch').value;
    q('#lineupPlayerList').innerHTML=list.filter(p=>options.matches(p.name,teamName,filter)).map(p=>`<button type="button" data-player="${esc(p.name)}"><strong>${esc(label(p.name))}</strong><span>${p.hand==='L'?'左':p.hand==='R'?'右':p.hand==='S'?'兩':'手別未記錄'}${pickerIndex==='P'?'投':'打'}${c.slots.some(s=>s.name===p.name)?' · 九棒中':''}</span></button>`).join('')||'<p>沒有符合的球員。</p>';
  }
  function openPicker(index,button){
    if(!roster||options.element.hasAttribute('aria-busy'))return;
    if(swapMode){if(index!=='P'&&((swapMode==='field')===!!button.hasAttribute?.('data-field')))swapSelect(index);else message('請在'+(swapMode==='field'?'球場圖':'棒次表')+'選擇兩位球員，或取消互換。');return;}
    pickerIndex=index;pickerField=button.hasAttribute?.('data-field')||false;returnFocus=button;
    q('#lineupPickerTitle').textContent=index==='P'?'選擇場上投手':'選擇第 '+(index+1)+' 棒球員';q('#lineupSearch').value='';pickerRender();q('#lineupPicker').showModal();q('#lineupSearch').focus();
  }
  async function selectTeam(name){
    resetSwap();const token=++selectTeam.generation;
    options.element.setAttribute('aria-busy','true');
    q('#lineupApply').disabled=true;
    try{const next=await options.team(name);if(token!==selectTeam.generation)return;teamName=name;roster=next;render();message(get(name).storageError?'保存記錄無法讀取；本次仍可設定。':get(name).identityUnresolved?.length?'舊名單已保留，部分球員需重新選取後套用。':get(name).identityMigrated?'已對應球員身份並保留原名單與棒次，請核對後套用。':'請依實際出賽名單設定。');}
    catch{if(token!==selectTeam.generation)return;if(roster)render();message('球員名單載入失敗，請重新選隊。',true);}
    finally{if(token===selectTeam.generation){options.element.removeAttribute('aria-busy');q('#lineupApply').disabled=!roster;}}
  }
  selectTeam.generation=0;
  function mount(o){
    options=o;
    ['field','order'].forEach(mode=>q(mode==='field'?'#lineupSwapField':'#lineupSwapOrder').onclick=()=>{if(options.element.hasAttribute('aria-busy'))return;swapMode=swapMode===mode?null:mode;swapFirst=null;render();});
    q('#lineupSwapCancel').onclick=()=>{swapMode=null;swapFirst=null;render();};
    q('#lineupSwapUndo').onclick=()=>{if(options.element.hasAttribute('aria-busy')||!swapUndo)return;get(teamName).draft=swapUndo;resetSwap();if(draftChanged()==='saved')message('已復原上一次互換；套用後更新評估。');};
    q('#lineupTeam').innerHTML=o.teams.map(t=>`<option>${esc(t)}</option>`).join('');
    q('#lineupTeam').onchange=e=>selectTeam(e.target.value);
    q('#lineupSearch').oninput=pickerRender;
    q('#lineupPickerClose').onclick=()=>q('#lineupPicker').close();
    q('#lineupPicker').addEventListener('keydown',e=>{if(e.key==='Escape'&&!e.isComposing){e.preventDefault();q('#lineupPicker').close();}});
    q('#lineupPicker').addEventListener('close',()=>{const target=returnFocus?.dataset.pick!==undefined?q(`[data-pick="${returnFocus.dataset.pick}"]`):returnFocus;target?.focus();});
    q('#lineupPlayerList').onclick=e=>{const button=e.target.closest('[data-player]');if(!button||button.disabled)return;swapUndo=null;assignPlayer(get(teamName).draft,pickerIndex,button.dataset.player,pickerField);q('#lineupPicker').close();draftChanged();};
    options.element.addEventListener('click',e=>{
      if(options.element.hasAttribute('aria-busy'))return;
      const pick=e.target.closest('[data-pick]'),move=e.target.closest('[data-move]');
      if(pick)openPicker(Number(pick.dataset.pick),pick);
      if(move){resetSwap();const c=get(teamName).draft,i=Number(move.dataset.move),j=i+Number(move.dataset.step);if(j>=0&&j<9){[c.slots[i],c.slots[j]]=[c.slots[j],c.slots[i]];draftChanged();const next=q(`[data-move="${j}"][data-step="${move.dataset.step}"]`);(next.disabled?q(`[data-pick="${j}"]`):next).focus();}}
    });
    options.element.querySelectorAll('[data-field]').forEach(button=>button.onclick=()=>{const pos=button.getAttribute('data-field');openPicker(pos==='P'?'P':get(teamName).draft.slots.findIndex(s=>s.pos===pos),button);});
    q('#lineupRows').onchange=e=>{
      if(options.element.hasAttribute('aria-busy')||!e.target.matches('[data-position]'))return;
      const c=get(teamName).draft,i=Number(e.target.dataset.position),j=c.slots.findIndex(s=>s.pos===e.target.value);
      if(!c.slots[i]||j===-1||i===j)return;
      resetSwap();
      swapFieldingPositions(c.slots[i],c.slots[j]);
      draftChanged();
      q(`[data-position="${i}"]`).focus();
    };
    q('#lineupPitcherPick').onclick=e=>openPicker('P',e.currentTarget);
    q('#lineupReset').onclick=async()=>{
      if(options.element.hasAttribute('aria-busy')||!defaults[teamName])return;
      const s=get(teamName);resetSwap();s.draft=clone(defaults[teamName]);s.confirmed=clone(defaults[teamName]);
      // 保存套用狀態，重新整理後仍維持依場上名單評估
      const saved=persist();
      // 與開啟網站時相同：換回預設先發投手時依角色帶入預設球數（先發 90／後援 15），不歸零
      s.isDefault=true;render();await o.applied(teamName,{pitcherSelected:false,resetPitchCount:false});message(saveMessage(saved,'已恢復預設名單並套用。','已恢復預設並套用；本次可用，但無法保存到瀏覽器。'));
    };
    q('#lineupApply').onclick=async()=>{
      const s=get(teamName),errors=validate(s.draft,roster);
      if(errors.length){message(errors.join(' '),true);return;}
      const old=s.confirmed,pitcherChanged=!old||old.pitcher!==s.draft.pitcher;
      resetSwap();delete s.isDefault;
      s.draft.slots.forEach(slot=>delete slot.fieldingPending);
      s.confirmed=clone(s.draft);const saved=persist();render();
      await o.applied(teamName,{pitcherSelected:pitcherChanged,resetPitchCount:pitcherChanged});
      message(saveMessage(saved,'配置已套用並保存。','配置已套用；本次可用，但無法保存到瀏覽器。'));
    };
    const exportButton=q('#lineupExport'), importInput=q('#lineupImport');
    exportButton.onclick=()=>{
      if(!roster||options.element.hasAttribute('aria-busy'))return;
      const {draft}=get(teamName);
      const state={version:2,season:runtimeSeason,draft,confirmed:null};
      const blob=new Blob([JSON.stringify({type:'baseball-lineup',team:teamName,state},null,2)],{type:'application/json'});
      const url=URL.createObjectURL(blob), link=document.createElement('a');
      link.href=url;link.download=`baseball-lineup-${runtimeSeason}.json`;link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
    let latestImport=0;
    importInput.onchange=async()=>{
      const request=++latestImport, selection=selectTeam.generation;
      const file=importInput.files?.[0], activeTeam=teamName, activeRoster=roster;
      importInput.value='';
      if(!file||!activeRoster||options.element.hasAttribute('aria-busy'))return;
      const state=get(activeTeam);
      const before=JSON.stringify([state.draft,state.confirmed]);
      const isCurrent=()=>request===latestImport&&selection===selectTeam.generation;
      try {
        if(file.size>65536)throw Error('請選擇小於 64 KB 的名單檔。');
        const text=await file.text();
        if(!isCurrent())return;
        if(JSON.stringify([state.draft,state.confirmed])!==before){
          message('讀取備份期間名單已變更。請重新選擇檔案以匯入草稿。',true);
          return;
        }
        const draft=readBackup(text,activeTeam,activeRoster);
        resetSwap();state.draft=draft;draftChanged();
      } catch(error) {
        if(isCurrent())message(error instanceof SyntaxError?'名單檔案不是有效的 JSON。':error.message,true);
      }
    };
  }
  /* 預設名單：{team:{slots,pitcher,games}}；只在此瀏覽器沒有保存記錄時帶入。 */
  function setDefaults(map){defaults={};defaultsMeta={};Object.entries(map||{}).forEach(([t,v])=>{const c={slots:v.slots.map(x=>({name:x.name,pos:x.pos})),pitcher:v.pitcher};if(c.slots.length===9&&c.slots.every(x=>POS[x.pos])&&new Set(c.slots.map(x=>x.pos)).size===9){defaults[t]=c;defaultsMeta[t]={games:v.games,through:v.through};}});states.forEach((s,t)=>{if(!s.confirmed&&defaults[t]&&!s.storageError&&(s.isDefault||!s.draft.pitcher)){s.draft=clone(defaults[t]);s.isDefault=true;}});}
  function defaultFor(t){return defaults[t]?clone(defaults[t]):null;}
  function persistSubstitution(t){
    const previous=teamName;
    teamName=t;
    const saved=persist();
    teamName=previous;
    if(t===teamName&&options&&roster)render();
    return {saved,notice:saveMessage(saved,'球隊名單已保存。','變更僅保留在目前頁面，無法保存到瀏覽器。')};
  }
  /* 換人：kind 為 'ph'（代打承接原棒次與守位）或 'pen'（換投）；被換下的球員記為已退場。回傳復原用的快照。 */
  function substitute(t,{kind,out,incoming,fieldingPending=false}){
    const s=get(t);if(!s.confirmed||!out||!incoming||out===incoming)return null;
    const c=s.confirmed;
    const canReplace=config=>(kind==='pen'?config.pitcher===out:config.slots.some(x=>x.name===out))
      &&config.pitcher!==incoming&&!config.slots.some(x=>x.name===incoming)&&!(config.unavailable||[]).includes(incoming);
    if(!canReplace(c))return null;
    const snapshot={draft:clone(s.draft),confirmed:clone(s.confirmed),isDefault:!!s.isDefault};
    const apply=config=>{
      if(kind==='pen'){if(config.pitcher===out)config.pitcher=incoming;}
      else{
        const slot=config.slots.find(x=>x.name===out);
        slot.name=incoming;
        if(fieldingPending&&slot.pos!=='DH')slot.fieldingPending=true;
        else delete slot.fieldingPending;
      }
      config.unavailable=[...new Set([...(config.unavailable||[]),out])].filter(n=>n!==incoming&&n!==config.pitcher&&!config.slots.some(x=>x.name===n));
    };
    const synced=JSON.stringify(s.draft)===JSON.stringify(s.confirmed);
    const samePosition=kind==='pen'||s.draft.slots.find(slot=>slot.name===out)?.pos===c.slots.find(slot=>slot.name===out).pos;
    const draftUpdated=synced||(samePosition&&canReplace(s.draft));
    apply(c);
    if(synced)s.draft=clone(c);
    else if(draftUpdated)apply(s.draft);
    snapshot.draftAfter=JSON.stringify(s.draft);
    delete s.isDefault;
    return {snapshot,draftPreserved:!draftUpdated,...persistSubstitution(t)};
  }
  function restore(t,snapshot){
    const s=get(t);if(!snapshot)return;
    const draftPreserved=JSON.stringify(s.draft)!==snapshot.draftAfter;
    if(!draftPreserved){
      s.draft=clone(snapshot.draft);
      if(snapshot.isDefault)s.isDefault=true;else delete s.isDefault;
    }
    s.confirmed=clone(snapshot.confirmed);
    return {draftPreserved,...persistSubstitution(t)};
  }
  function cancelSwap(){swapMode=null;swapFirst=null;if(options&&roster)render();}
  const api={setRuntime,release,setDefaults,defaultFor,substitute,restore,cancelSwap,mount,selectTeam,current,validate,empty,validState,assignPlayer,swapPlayers,migrateIdentity,readBackup};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.LineupBoard=api;
})(typeof window!=='undefined'?window:globalThis);
