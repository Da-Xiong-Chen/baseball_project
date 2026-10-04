"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const POS = { C: "捕手", "1B": "一壘", "2B": "二壘", "3B": "三壘", SS: "游擊", LF: "左外野", CF: "中外野", RF: "右外野", DH: "指定打擊" };
const GROUPS = ["速球", "滑卡", "曲球", "低落"];
const GROUP_COLOR = { 速球: "#d9534f", 滑卡: "#e0a03a", 曲球: "#4a7fd0", 低落: "#3f9a6b" };
let officialPlayers = {};
function officialPlayerLink(name) {
  const ids = officialPlayers[name];
  const direct = Array.isArray(ids) && ids.length === 1 && /^\d{10}$/.test(ids[0]);
  const url = direct ? `https://www.cpbl.com.tw/team/person?acnt=${ids[0]}` : `https://stats.cpbl.com.tw/players?playerName=${encodeURIComponent(String(name).replace(/〔.*〕$/, ''))}`;
  return `<a class="player-official" href="${esc(url)}" target="_blank" rel="noopener noreferrer" aria-label="${esc(name)}：CPBL ${direct ? '官方球員資料' : '官方球員搜尋'}（另開分頁）">${esc(name)}</a>`;
}
const RESULT_LABELS={SO:'三振',BB:'保送',uBB:'保送',iBB:'保送',HBP:'觸身球','1B':'一壘安打','2B':'二壘安打','3B':'三壘安打',HR:'全壘打',FC:'野手選擇',FO:'出局',GO:'出局',AO:'出局'};
const resultLabel=code=>RESULT_LABELS[code]||(code?'其他結果':'未提供');
const BASES = { 0: "無人", 1: "一壘", 2: "二壘", 3: "一二壘", 4: "三壘", 5: "一三壘", 6: "二三壘", 7: "滿壘" };

const S = {
  mode: "custom", view: "offense", starter: false, inning: 7, half: "home", outs: 1, bases: 3,
  teams: [], roster: {}, games: [], game: null, pa: null, last: null, selected: null,
  bench: new Set(), ready: false,
};
let resultInputKey = null, loadedTeams = {my:'',opp:''}, groupControl = null;
const benchOpen = new Map(), benchSearchOpen = new Map(), fieldErrors = new Map();
const comparisonSelections = new WeakMap();
function evaluationKey() {
  const value=id=>$(id)?.value || '';
  return JSON.stringify([S.view,S.inning,S.half,S.outs,S.bases,value('#myTeam'),value('#oppTeam'),value('#myScore'),value('#oppScore'),
    S.view==='offense'?[value('#dueBatter'),value('#duePos'),value('#oppPitcher'),[...S.bench].filter(n=>n!==value('#dueBatter')).sort()]:
    [value('#myPitcher'),value('#pitchCount'),S.starter,...['#nb1','#nb2','#nb3'].map(value),$$('#penList input:checked').map(i=>i.value).filter(n=>n!==value('#myPitcher')).sort()]]);
}
function showFieldError(id,message) {
  fieldErrors.set(id,message);$('#'+id).setAttribute('aria-invalid','true');$('#'+id).setAttribute('aria-describedby','formError');
  $('#formError').innerHTML=`<p role="alert">${esc(message)}</p>`;$('#'+id).focus();
}
function clearValidErrors() {
  const hadErrors=fieldErrors.size>0;
  for(const [id] of fieldErrors) {
    const input=$('#'+id), duplicate=id.startsWith('nb')&&['nb1','nb2','nb3'].filter(k=>$('#'+k).value===input.value).length>1;
    if(input.value!==''&&input.checkValidity()&&(!id.startsWith('nb')?Number.isInteger(Number(input.value)):!duplicate)) {
      fieldErrors.delete(id);input.removeAttribute('aria-invalid');input.removeAttribute('aria-describedby');
    }
  }
  if(hadErrors&&!fieldErrors.size&&$('#formError [role="alert"]'))$('#formError').innerHTML='';
}
function changeInning(delta) {
  const next=Math.max(1,Math.min(12,S.inning+delta));
  if(next===S.inning)return;
  S.inning=next;if(S.mode==='custom'&&next>=10)S.bases=2;renderState();
}
let rosterGeneration = 0, gamesGeneration = 0, gameGeneration = 0, runGeneration = 0;
function clearResult() {
  ++runGeneration;
  ++detailGeneration;
  S.last = null;
  resultInputKey = null;
  $("#resultBody").innerHTML = "";
  $("#resultBody").classList.add("hidden");
  $("#emptyState").classList.remove("hidden");
  $("#evalBtn").disabled = !S.ready;
  $("#evalBtn").innerHTML = uiIcon("compare") + "評估";
}
function invalidateCustom(event) {
  clearValidErrors();
  if (S.mode !== 'custom' || event?.target?.id === 'benchFilter' || event?.target?.closest?.('#pitcherGroups')) return;
  if(resultInputKey!==null&&evaluationKey()===resultInputKey)return;
  clearResult();
}
function stepScore(id, delta) {
  const input = $('#' + id), value = input.value === '' ? 0 : Number(input.value);
  if (!Number.isSafeInteger(value) || value < 0) {
    input.setAttribute('aria-invalid','true'); input.focus();
    $('#formError').innerHTML = '<p role="alert">得分請填寫非負整數。</p>'; return;
  }
  const next = Math.max(0, value + delta);
  if (!Number.isSafeInteger(next)) return;
  input.value = String(next); input.removeAttribute('aria-invalid');
  invalidateCustom({target:input}); syncScoreControls();
}
function syncScoreControls() {
  $$('[data-score][data-delta="-1"]').forEach(button => { button.disabled = Number($('#'+button.dataset.score).value) <= 0; });
}
function listError(selector, message, retry) {
  $(selector).innerHTML = `<div class="err-box" role="alert">${esc(message)}<button type="button" class="retry">重新載入</button></div>`;
  $(selector + " .retry").onclick = retry;
}

/* 有本機伺服器（python server.py）時呼叫 API；否則（GitHub Pages）用瀏覽器內的 Engine 與預先計算的回放資料。 */
let STATIC = false;
const cache = {};
// Older mobile browsers can fetch normally even without AbortSignal.timeout.
const timeoutOptions = ms => typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function" ? {signal:AbortSignal.timeout(ms)} : {};
async function fetchTimed(url, options = {}, ms = 30000) {
  if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') return fetch(url, {...options, ...timeoutOptions(ms)});
  if (typeof AbortController === 'undefined') return fetch(url, options);
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), ms);
  try { return await fetch(url, {...options, signal:controller.signal}); } finally { clearTimeout(timer); }
}
async function json(url) {
  if (!cache[url]) cache[url] = fetchTimed(url, {cache:"no-cache"}).then((r) => { if (!r.ok) throw new Error(`${r.status} ${url}`); return r.json(); }).catch(e => { delete cache[url]; throw e; });
  return cache[url];
}
async function staticApi(path, body) {
  const u = new URL(path, location.href), q = (k) => u.searchParams.get(k);
  const M = Engine.model();
  switch (u.pathname.split("/").pop()) {
    case "meta": return { teams: M.teams };
    case "team": return M.rosters[q("team")];
    case "games": {
      const t = q("team");
      return (await json("data/replay/games.json")).filter((g) => g.away === t || g.home === t);
    }
    case "game": return (await json(`data/replay/${q("game")}.json`)).pas;
    case "replay": {
      const pa = q("pa"), gid = pa.split("-").slice(0, 2).join("-");
      const r = (await json(`data/replay/${gid}.json`)).results[pa];
      if (!r) throw new Error("靜態版只收錄實際有換代打的打席");
      return r;
    }
    case "evaluate": return Engine.evaluate(body);
    case "detail": {
      const key = `${q("batter")}|${q("pitcher")}`;
      if (S.last && S.last.details && S.last.details[key]) return S.last.details[key];
      if (S.last?.view === "replay") throw new Error("此歷史對決明細未匯出；不使用全季資料補缺");
      return Engine.detail(q("batter"), q("pitcher"));
    }
  }
  throw new Error("unknown " + path);
}

async function api(path, body) {
  if (STATIC) return staticApi(path, body);
  const res = await fetchTimed(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}, 120000);
  const j = await res.json();
  if (!res.ok || j.error) throw new Error(j.error || res.statusText);
  return j;
}
async function team(name) {
  if (!S.roster[name]) S.roster[name] = await api(`api/team?team=${encodeURIComponent(name)}`);
  return S.roster[name];
}
const sign = (v, d = 2) => (v > 0 ? "+" : v < 0 ? "−" : "±") + Math.abs(v).toFixed(d);
const cls = (v, eps = 0.005) => (v > eps ? "pos" : v < -eps ? "neg" : "mut");
const handChip = (h) => `<span class="chip hand-${esc(h)}">${h === "L" ? "左" : h === "R" ? "右" : "兩"}</span>`;
const posChips = (p) => Object.keys(p || {}).slice(0, 3).map((k) => `<span class="chip">${POS[k] || k}</span>`).join("");

/* ---------------- 初始化 ---------------- */
async function init() {
  try { officialPlayers = (await json('data/cpbl-players.json')).players || {}; } catch { /* Search remains available when the mapping cannot load. */ }
  try {
    const r = await fetchTimed("api/meta");
    if (!r.ok || !(r.headers.get("content-type") || "").includes("json")) throw 0;
  } catch {
    STATIC = true;
    await Engine.load();
    document.body.classList.add("static");
  }
  const meta = await api("api/meta");
  S.teams = meta.teams;
  const opts = S.teams.map((t) => `<option>${esc(t)}</option>`).join("");
  $("#myTeam").innerHTML = opts;
  $("#oppTeam").innerHTML = opts;
  $("#rpTeam").innerHTML = opts;
  $("#myTeam").value = "樂天桃猿";
  $("#oppTeam").value = "味全龍";
  $("#duePos").innerHTML = Object.entries(POS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
  bindStatic();
  renderState();
  await refreshCustom();
}

function bindStatic() {
  $$('[data-score]').forEach(button => button.onclick = () => stepScore(button.dataset.score, Number(button.dataset.delta)));
  ['#myScore','#oppScore'].forEach(id => $(id).oninput = syncScoreControls);
  syncScoreControls();
  const panel = $("#customPanel");
  panel.addEventListener('input', invalidateCustom);
  panel.addEventListener('change', invalidateCustom);
  panel.addEventListener('click', event => {
    if (event.target.closest('#halfSeg button, #outs button, #diamond .base, #baseControls button, #roleSeg button, #innUp, #innDown, #benchList button[data-group], #benchAll, #benchNone, #penAll, #penNone')) invalidateCustom(event);
  });
  $$("#modeSeg button").forEach((b) => b.onclick = () => setMode(b.dataset.mode));
  $$("#viewSeg button").forEach((b) => b.onclick = () => setView(b.dataset.view));
  $$("#halfSeg button").forEach((b) => b.onclick = () => { S.half = b.dataset.half; renderState(); });
  $("#innUp").onclick = () => { changeInning(1); };
  $("#innDown").onclick = () => { changeInning(-1); };
  $$("#outs button").forEach((b) => b.onclick = () => { const o = +b.dataset.o; S.outs = S.outs === o ? o - 1 : o; renderState(); });
  $$("#diamond .base").forEach((b) => b.onclick = () => { S.bases ^= +b.dataset.b; renderState(); });
  $$("#baseControls button").forEach(b => b.onclick = () => { S.bases ^= +b.dataset.b; renderState(); });
  $("#myTeam").onchange = () => { syncTeamChoices('myTeam'); refreshCustom(); };
  $("#oppTeam").onchange = () => { syncTeamChoices('oppTeam'); refreshCustom(); };
  $("#dueBatter").onchange = () => { autoPos(); renderBench(); };
  $("#benchFilter").oninput = () => renderBench();
  $("#benchToggleAll").onclick = () => toggleBenchGroups();
  ["nb1","nb2","nb3"].forEach(id => $("#"+id).onchange = syncNextBatters);
  $("#benchList").onchange = e => { if (e.target.matches('input')) { if (e.target.checked) S.bench.add(e.target.value); else S.bench.delete(e.target.value); renderBench(); } };
  $("#benchList").onclick = e => {
    const b = e.target.closest("button[data-group]");
    if (!b) return;
    const names = b.dataset.group.split("|");
    const all = names.every((n) => S.bench.has(n));
    names.forEach((n) => (all ? S.bench.delete(n) : S.bench.add(n)));
    invalidateCustom();
    renderBench();
  };
  $("#duePos").onchange = () => renderBench();
  $("#benchAll").onclick = () => { S.bench = new Set(S.roster[$("#myTeam").value].hitters.filter(h => h.name !== $("#dueBatter").value).map(h => h.name)); renderBench(); };
  $("#benchNone").onclick = () => { S.bench.clear(); renderBench(); };
  $("#penAll").onclick = () => { $$("#penList input").forEach((i) => i.checked = true); invalidateCustom();groupControl?.refresh(); };
  $("#penNone").onclick = () => { $$("#penList input").forEach((i) => i.checked = false); invalidateCustom();groupControl?.refresh(); };
  $("#evalBtn").onclick = evaluateCustom;
  $("#myPitcher").onchange = syncRole;
  $$("#roleSeg button").forEach((b) => b.onclick = () => { S.starter = b.dataset.r === "1"; renderRole(); });
  $("#pitchCount").oninput = renderRole;
  $("#rpTeam").onchange = loadGames;
  $("#onlyPhGames").onchange = renderGames;
  $("#lateOnly").onchange = renderPAs;
}

function syncRole() {
  const my = S.roster[$("#myTeam").value];
  const p = my && my.pitchers.find((x) => x.name === $("#myPitcher").value);
  S.starter = !!p && p.role === "先發";
  $("#pitchCount").value = S.starter ? 90 : 15;
  renderRole();
}
function renderRole() {
  groupControl?.refresh();
  $$("#roleSeg button").forEach((b) => b.classList.toggle("on", (b.dataset.r === "1") === S.starter));
  syncPressed();
  const pc = +$("#pitchCount").value || 0;
  $("#pcHint").textContent = S.starter
    ? (pc >= 85 ? "球數偏高，請確認狀況。" : "")
    : (pc >= 30 ? "後援球數偏高；僅提示。" : "");
}

function setMode(m) {
  if(m===S.mode)return;
  clearResult();
  S.mode = m;
  $$("#modeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.mode === m));
  syncPressed();
  $("#customPanel").classList.toggle("hidden", m !== "custom");
  $("#replayPanel").classList.toggle("hidden", m !== "replay");
  if (m === "replay" && !S.games.length) loadGames();
}
function setView(v) {
  if(v===S.view)return;
  clearResult();
  S.view = v;
  $$("#viewSeg button").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  syncPressed();
  $("#offenseFields").classList.toggle("hidden", v !== "offense");
  $("#defenseFields").classList.toggle("hidden", v !== "defense");
}
function renderState() {
  $("#innVal").textContent = S.inning;
  $("#outsValue").textContent = S.outs + ' 出局';
  $$("#baseControls button").forEach(b => b.setAttribute("aria-pressed", String((S.bases & +b.dataset.b) > 0)));
  $$("#halfSeg button").forEach((b) => b.classList.toggle("on", b.dataset.half === S.half));
  $$("#outs button").forEach((b) => b.classList.toggle("on", +b.dataset.o <= S.outs));
  $$("#diamond .base").forEach((b) => b.classList.toggle("on", (S.bases & +b.dataset.b) > 0));
  syncPressed();
}
function syncPressed() {
  $$(".seg button, #outs button").forEach(b => b.setAttribute("aria-pressed", String(b.classList.contains("on"))));
}

/* ---------------- 自訂情境 ---------------- */
function syncTeamChoices(changed = 'myTeam') {
  const mine=$('#myTeam'),opp=$('#oppTeam'),other=changed==='myTeam'?opp:mine;
  if(mine.value===opp.value) other.value=S.teams.find(t=>t!==(changed==='myTeam'?mine.value:opp.value))||'';
  Array.from(mine.options).forEach(o=>{o.disabled=o.value===opp.value;});
  Array.from(opp.options).forEach(o=>{o.disabled=o.value===mine.value;});
}
async function refreshCustom() {
  syncTeamChoices();
  const token = ++rosterGeneration;
  S.ready = false;
  clearResult();
  $("#formError").innerHTML = '<span role="status">正在載入名單…</span>';
  const myName = $("#myTeam").value, oppName = $("#oppTeam").value;
  const myChanged=loadedTeams.my!==myName,oppChanged=loadedTeams.opp!==oppName;
  let my, opp;
  try {
    [my, opp] = await Promise.all([team(myName), team(oppName)]);
  } catch (e) {
    if (token === rosterGeneration) listError('#formError', '名單載入失敗，請重試。', refreshCustom);
    return;
  }
  if (token !== rosterGeneration) return;
  $("#formError").innerHTML = '';
  const pOpt = (ps) => {
    const g = (role) => ps.filter((p) => p.role === role).map((p) => `<option value="${esc(p.name)}">${esc(p.name)}（${p.hand === "L" ? "左" : "右"}投・${p.games}場）</option>`).join("");
    return `<optgroup label="後援">${g("後援")}</optgroup><optgroup label="先發">${g("先發")}</optgroup>`;
  };
  const hOpt = hs => hs.map(h=>`<option value="${esc(h.name)}">${esc(h.name)}（${h.hand==='L'?'左':h.hand==='R'?'右':'兩'}打）</option>`).join('');
  if(oppChanged) {
    $('#oppPitcher').innerHTML=pOpt(opp.pitchers);
    ['#nb1','#nb2','#nb3'].forEach((id,i)=>{$(id).innerHTML=hOpt(opp.hitters);$(id).selectedIndex=i;});syncNextBatters();
  }
  if(myChanged) {
    $('#myPitcher').innerHTML=pOpt(my.pitchers);$('#dueBatter').innerHTML=hOpt(my.hitters);
    $('#dueBatter').selectedIndex=Math.min(8,my.hitters.length-1);autoPos();$('#benchFilter').value='';renderBench(true);syncRole();
    $('#penList').innerHTML=my.pitchers.map(p=>`<label><input type="checkbox" value="${esc(p.name)}" ${p.role==='後援'?'checked':''}>${esc(p.name)}<span class="meta">${handChip(p.hand)}<span class="chip">${p.role}</span></span></label>`).join('');
    if(typeof PitcherGroups!=='undefined')groupControl=PitcherGroups.mount({element:$('#pitcherGroups'),list:$('#penList'),team:myName,pitchers:my.pitchers,current:()=>$('#myPitcher').value,changed:()=>invalidateCustom()});
  }
  loadedTeams={my:myName,opp:oppName};S.ready=true;$('#evalBtn').disabled=false;

}
function autoPos() {
  const my = S.roster[$("#myTeam").value];
  const h = my.hitters.find((x) => x.name === $("#dueBatter").value);
  const top = h && Object.keys(h.positions || {})[0];
  $("#duePos").value = top || "DH";
}
const POS_ORDER = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"];
const BENCH_GROUPS = [
  ["捕手", ["C"]],
  ["內野手", ["1B", "2B", "3B", "SS"]],
  ["外野手", ["LF", "CF", "RF"]],
  ["指定打擊", []],
];
// 依主守位（出賽最多的位置）分組；同組內依守位順序、再依打席數排列
function benchGroupOf(h) {
  const main = Object.keys(h.positions || {})[0];
  const i = BENCH_GROUPS.findIndex(([, ps]) => ps.includes(main));
  return i < 0 ? BENCH_GROUPS.length - 1 : i;
}
function syncNextBatters() {
  ['nb1','nb2','nb3'].forEach(id=>{
    const input=$('#'+id), badge=$('[data-next-hand="'+id+'"]');
    if(!input||!badge)return;
    const h=S.roster[$('#oppTeam').value]?.hitters.find(h=>h.name===input.value);
    badge.textContent=h?(h.hand==='L'?'左打':h.hand==='R'?'右打':'兩打'):'';
    // Keep full names visible; handedness has its own fixed label.
    Array.from(input.options).forEach(option=>option.textContent=option.value);
  });
}
function updateBenchToggle() {
  const buttons=$$('#benchList [data-expand]:not(:disabled)'),control=$('#benchToggleAll');
  const all=buttons.length>0&&buttons.every(b=>b.getAttribute('aria-expanded')==='true'),q=$('#benchFilter').value.trim();
  control.textContent=q?(all?'收起搜尋結果':'展開搜尋結果'):(all?'全部收起':'全部展開');
  control.disabled=!buttons.length;
}
function toggleBenchGroups() {
  const buttons=$$('#benchList [data-expand]:not(:disabled)'),collapse=buttons.length>0&&buttons.every(b=>b.getAttribute('aria-expanded')==='true');
  const key=$('#myTeam').value,q=$('#benchFilter').value.trim();
  const open=q?benchSearchOpen.get(key)?.open:benchOpen.get(key);
  if(!open)return;
  buttons.forEach(b=>{const i=Number(b.dataset.expand);collapse?open.delete(i):open.add(i);});
  renderBench();$('#benchToggleAll').focus({preventScroll:true});
}
function renderBench(reset) {
  const my = S.roster[$("#myTeam").value];
  const due = $("#dueBatter").value;
  const duePos = $("#duePos").value;
  const q = $("#benchFilter").value.trim();
  const list = my.hitters.filter((h) => h.name !== due);
  // 預設勾選：出賽較少的球員（較可能在板凳）
  const regulars = new Set(my.hitters.slice(0, 9).map((h) => h.name));
  if (reset === true) S.bench = new Set(list.filter(h => !regulars.has(h.name)).map(h => h.name));
  S.bench.delete(due);
  const shown = list.filter((h) => !q || h.name.includes(q));
  const posRank = (h) => { const p = Object.keys(h.positions || {})[0]; const i = POS_ORDER.indexOf(p); return i < 0 ? 99 : i; };
  const teamKey=$('#myTeam').value;
  if(!benchOpen.has(teamKey))benchOpen.set(teamKey,new Set());
  if(q&&benchSearchOpen.get(teamKey)?.query!==q)benchSearchOpen.set(teamKey,{query:q,open:new Set(BENCH_GROUPS.map((_,i)=>i))});
  if(!q)benchSearchOpen.delete(teamKey);
  const open=q?benchSearchOpen.get(teamKey).open:benchOpen.get(teamKey);
  const groups=BENCH_GROUPS.map(([label],index)=>({label,index,all:list.filter(h=>benchGroupOf(h)===index),players:shown.filter(h=>benchGroupOf(h)===index)}));
  const html=groups.filter(g=>!q||g.players.length).map(g=>{
    g.players.sort((a,b)=>posRank(a)-posRank(b)||b.pa-a.pa);
    const picked=g.all.filter(h=>S.bench.has(h.name)).length, allPicked=g.players.length>0&&g.players.every(h=>S.bench.has(h.name));
    const names=esc(g.players.map(h=>h.name).join('|'));
    const rows=g.players.map(h=>{
      const cover=duePos&&duePos!=='DH'&&Object.keys(h.positions||{}).includes(duePos);
      return `<label><input type="checkbox" value="${esc(h.name)}" ${S.bench.has(h.name)?'checked':''}>${esc(h.name)}${cover?'<span class="chip cover">可接守</span>':''}<span class="meta">${handChip(h.hand)}${Object.keys(h.positions||{}).length?posChips(h.positions):'<span class="chip">守位未收錄</span>'}<span class="chip">${h.pa} 打席</span></span></label>`;
    }).join('');
    return `<section class="bench-group"><div class="bench-group-h"><button type="button" class="bench-expand" data-expand="${g.index}" aria-expanded="${!!(open.has(g.index))}" aria-controls="bench-group-${g.index}" ${!g.all.length?'disabled':''}><span class="bench-group-name">${g.label}</span><span class="mut bench-group-count">${picked}/${g.all.length}${q?' · 符合 '+g.players.length+' 人':''}</span><span aria-hidden="true" class="chevron">⌄</span></button><button type="button" class="link" data-group="${names}" aria-label="${esc(g.label)}：${allPicked?'取消選取':'全選'}${q?'符合者':''}" ${!g.players.length?'disabled':''}>${q?(allPicked?'取消符合者':'選取符合者'):(allPicked?'全不選':'全選')}</button></div><div id="bench-group-${g.index}" ${open.has(g.index)?'':'hidden'}>${rows}</div></section>`;
  }).join('');
  $('#benchAll').innerHTML=uiIcon('check')+'全選球員';$('#benchNone').innerHTML=uiIcon('clear')+'清除選取';

  const box = $("#benchList"), top = box.scrollTop;
  const focusValue=box.contains?.(document.activeElement)?document.activeElement.value:null;
  box.innerHTML = html || '<p role="status">沒有符合的球員；搜尋不會清除已選名單。</p>';
  box.scrollTop = top;
  box.querySelectorAll('[data-expand]').forEach(button=>button.onclick=()=>{
    const index=Number(button.dataset.expand),panel=$('#bench-group-'+index),expanded=button.getAttribute('aria-expanded')==='true';
    panel.hidden=expanded;button.setAttribute('aria-expanded',String(!expanded));expanded?open.delete(index):open.add(index);updateBenchToggle();
  });
  updateBenchToggle();
  if(focusValue)Array.from(box.querySelectorAll('input')).find(i=>i.value===focusValue)?.focus({preventScroll:true});
}

async function evaluateCustom() {
  if (!S.ready) return;
  clearResult();
  $("#formError").innerHTML = '';
  for (const id of ['myScore','oppScore', ...(S.view === 'defense' ? ['pitchCount'] : [])]) {
    const input = $('#' + id);
    if (input.value === '' || !input.checkValidity() || !Number.isInteger(Number(input.value))) {
      showFieldError(id,id==='pitchCount'?'本場球數須為 0–160 的整數。':(id==='myScore'?'我方':'對手')+'得分須為非負整數。');return;
    }
    input.removeAttribute('aria-invalid');
  }
  const my = $("#myTeam").value, opp = $("#oppTeam").value;
  if (my === opp) { $("#formError").innerHTML = '<p role="alert">我方與對手須為不同球隊。</p>'; return; }
  const myScore = +$("#myScore").value || 0, oppScore = +$("#oppScore").value || 0;
  const battingScore=S.view==='offense'?myScore:oppScore, fieldingScore=S.view==='offense'?oppScore:myScore;
  if(S.inning>=9&&((S.half==='home'&&battingScore>fieldingScore)||(S.half==='away'&&S.inning>=10&&fieldingScore>battingScore))) {
    $('#formError').innerHTML='<p role="alert">此局面比賽已結束，沒有下一打席；請確認局數、上下半局與比分。</p>';return;
  }
  let body;
  if (S.view === "offense") {
    const bench = [...S.bench].filter(n => n !== $("#dueBatter").value);
    body = { inning: S.inning, half: S.half, outs: S.outs, bases: S.bases, bat_score: myScore, fld_score: oppScore,
      pitcher: $("#oppPitcher").value, due: $("#dueBatter").value, due_pos: $("#duePos").value, bench,
      bat_team: my, fld_team: opp };
  } else {
    const nb = ["#nb1", "#nb2", "#nb3"].map((s) => $(s).value);
    if(new Set(nb).size!==3){const duplicated=nb.find(n=>nb.filter(x=>x===n).length>1);['nb1','nb2','nb3'].filter((id,i)=>nb[i]===duplicated).reverse().forEach(id=>showFieldError(id,'接下來三棒須為不同打者。'));return;}
    body = { inning: S.inning, half: S.half, outs: S.outs, bases: S.bases, bat_score: oppScore, fld_score: myScore,
      pitcher: $("#myPitcher").value, due: nb[0], due_pos: "DH", bench: [], bat_team: opp, fld_team: my,
      next_batters: nb, pen: $$("#penList input:checked").map((i) => i.value).filter(name=>name!==$("#myPitcher").value),
      pitch_count: +$("#pitchCount").value || 0, starter: S.starter };
  }
  await run(() => api("api/evaluate", body), S.view);
}

async function run(fn, view) {
  const token = ++runGeneration;
  resultInputKey=S.mode==='custom'?evaluationKey():null;
  const btn = $("#evalBtn");
  btn.disabled = true; btn.innerHTML = `<span class="loading"></span> 計算中…`;
  $("#emptyState").classList.add("hidden");
  const box = $("#resultBody");
  box.classList.remove("hidden");
  if (!S.last) box.innerHTML = `<div class="card empty" role="status"><span class="loading"></span> 正在比較人選…</div>`;
  try {
    const result = await fn();
    if (token !== runGeneration) return;
    S.last = result;
    S.last.view = view;
    S.selected = null;
    renderResult();
    if (window.matchMedia("(max-width: 1000px)").matches) $("#result").scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    else window.scrollTo({ top: 0, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  } catch (e) {
    if (token !== runGeneration) return;
    S.last = null;
  resultInputKey = null;
    box.innerHTML = `<div class="err-box" role="alert">評估未完成，請重試。<button class="retry">重新評估</button></div>`;
    box.querySelector('.retry').onclick = () => run(fn, view);
  } finally {
    if (token === runGeneration) { btn.disabled = !S.ready; btn.innerHTML = uiIcon("compare") + "評估"; }
  }
}

/* ---------------- 歷史回放 ---------------- */
async function loadGames() {
  const token = ++gamesGeneration;
  ++gameGeneration;
  clearResult();
  S.games = []; S.pas = null; S.game = null; S.pa = null;
  $("#paList").innerHTML = '<p>先選一場比賽</p>';
  $("#gameList").innerHTML = `<div class="empty" style="padding:24px"><span class="loading"></span></div>`;
  try {
    const games = await api(`api/games?team=${encodeURIComponent($("#rpTeam").value)}`);
    if (token !== gamesGeneration) return;
    S.games = games;
  } catch (e) { if (token === gamesGeneration) listError('#gameList', '比賽列表載入失敗。', loadGames); return; }
  renderGames();
}
function renderGames() {
  const only = $("#onlyPhGames").checked;
  const gs = S.games.filter((g) => !only || g.ph > 0);
  $("#gameList").innerHTML = gs.map((g) => `
    <button type="button" class="item ${S.game === g.game ? "on" : ""}" data-g="${g.game}" aria-pressed="${S.game === g.game}">
      <span class="num mut" style="font-size:12px">${g.date.slice(5)}</span>
      <span>${esc(g.away)} <b class="num">${g.away_score}</b> : <b class="num">${g.home_score}</b> ${esc(g.home)}</span>
      ${g.ph ? `<span class="chip tag-ph" style="margin-left:auto">代打 ${g.ph}</span>` : ""}
    </button>`).join("") || `<div class="empty" style="padding:24px">沒有符合的比賽</div>`;
  $$("#gameList .item").forEach((el) => el.onclick = () => loadGame(el.dataset.g));
}
async function loadGame(gid) {
  const token = ++gameGeneration;
  clearResult();
  S.pas = null; S.pa = null;
  S.game = gid;
  renderGames();
  $("#paList").innerHTML = `<div class="empty" style="padding:24px"><span class="loading"></span></div>`;
  try {
    const pas = await api(`api/game?game=${gid}`);
    if (token !== gameGeneration) return;
    S.pas = pas;
  } catch (e) { if (token === gameGeneration) listError('#paList', '打席列表載入失敗。', () => loadGame(gid)); return; }
  renderPAs();
}
function renderPAs() {
  if (!S.pas) return;
  const late = $("#lateOnly").checked;
  let html = "", lastKey = "";
  for (const p of S.pas.filter((p) => !late || p.inning >= 7)) {
    const key = `${p.inning}-${p.half}`;
    if (key !== lastKey) {
      html += `<div class="inning-h">${p.inning} 局${p.half === "away" ? "上" : "下"}・${esc(p.bat_team)} 攻擊</div>`;
      lastKey = key;
    }
    const off = STATIC && !p.is_ph;
    html += `<button type="button" class="item ${S.pa === p.pa_id ? "on" : ""} ${off ? "off" : ""}" data-p="${p.pa_id}" aria-pressed="${S.pa === p.pa_id}" ${off ? 'disabled title="靜態版只收錄實際換代打的打席"' : ""}>
      <span class="chip num">${p.outs} 出・${BASES[p.bases]}</span>
      <span>${esc(p.batter)}</span>
      ${p.is_ph ? `<span class="chip tag-ph">代打</span>` : ""}
      <span class="mut" style="margin-left:auto;font-size:12px">${esc(resultLabel(p.result))}</span></button>`;
  }
  $("#paList").innerHTML = (STATIC ? `<div class="inning-h" style="position:static">2025 代打情境；可選取標示「代打」的打席。</div>` : "") + (html || `<div class="empty" style="padding:24px">沒有打席</div>`);
  $$("#paList .item:not(.off)").forEach((el) => el.onclick = () => {
    S.pa = el.dataset.p;
    renderPAs();
    $(`#paList [data-p="${S.pa}"]`)?.focus();
    run(() => api(`api/replay?pa=${el.dataset.p}`), "replay");
  });
}

/* ---------------- 結果呈現 ---------------- */
const COMPARISON_LIMIT = 4;
function uiIcon(name) { return `<svg class="ui-icon" aria-hidden="true"><use href="#icon-${name}"/></svg>`; }
function comparisonNames(R,tab) {
  let state=comparisonSelections.get(R);if(!state){state=new Map();comparisonSelections.set(R,state);}
  if(!state.has(tab)) {
    const rows=tab==='pen'?R.bullpen?.rows:R.candidates,key=tab==='pen'?'投手':'球員';
    state.set(tab,new Set((rows||[]).filter(r=>r['角色']!==(tab==='pen'?'場上':'現任')).slice(0,COMPARISON_LIMIT).map(r=>r[key])));
  }
  return state.get(tab);
}
function setComparisonName(R,tab,name,checked) {
  const rows=tab==='pen'?R.bullpen?.rows:R.candidates,key=tab==='pen'?'投手':'球員';
  if(!(rows||[]).some(r=>r[key]===name&&r['角色']!==(tab==='pen'?'場上':'現任')))return false;
  const names=comparisonNames(R,tab);
  if(checked&&!names.has(name)&&names.size>=COMPARISON_LIMIT)names.delete(names.values().next().value);
  checked?names.add(name):names.delete(name);return true;
}
function bindComparison(R,tab) {
  const box=$('#candidateCompare');
  const update=(name,checked)=>{
    setComparisonName(R,tab,name,checked);box.innerHTML=comparisonPanel(R,null,tab);bindComparison(R,tab);
    syncComparisonChoices(R,tab);
    const target=Array.from(document.querySelectorAll('[data-table-compare]')).find(i=>i.value===name);
    target?.focus({preventScroll:true});
  };
  box.querySelectorAll('[data-remove-compare]').forEach(b=>b.onclick=()=>update(b.dataset.removeCompare,false));
}
function comparisonCircle(R,tab,name) {
  return `<label class="comparison-circle"><input type="checkbox" data-table-compare value="${esc(name)}" aria-label="比較並查看 ${esc(name)} 對決" ${comparisonNames(R,tab).has(name)?'checked':''}></label>`;
}
function syncComparisonChoices(R,tab) {
  $$('[data-table-compare]').forEach(i=>i.checked=comparisonNames(R,tab).has(i.value));
}
function bindTableComparison(R,tab) {
  $$('[data-table-compare]').forEach(input=>input.onchange=()=>{
    setComparisonName(R,tab,input.value,input.checked);
    $('#candidateCompare').innerHTML=comparisonPanel(R,null,tab);bindComparison(R,tab);syncComparisonChoices(R,tab);
    if(input.checked){const tr=input.closest('tr');showDetail(tab==='pen'?R.bullpen.next[0]:input.value,tab==='pen'?input.value:R.situation.pitcher,tr);}
  });
}
function pitcherMatchupChart(details, sharedScale, currentDetails = []) {
  const data=(details||[]).map(d=>({name:d.batter,value:d.runs+d.fatigue})).filter(d=>Number.isFinite(d.value));
  if(!data.length)return '';
  const baseline=new Map();
  for(const d of currentDetails||[]) {
    const value=d.runs+d.fatigue;
    if(Number.isFinite(value))baseline.set(d.batter,baseline.has(d.batter)?null:value);
  }
  const scale=Math.max(.01,sharedScale||0,...data.map(d=>Math.abs(d.value)),...data.map(d=>baseline.get(d.name)).filter(Number.isFinite).map(Math.abs));
  return `<div class="next-matchup-chart"><p class="mut">逐棒失分價值 · 分（越低越好）</p><div class="matchup-legend"><span><i></i>候選</span><span><b></b>現任</span></div>${data.map(d=>{
    const width=Math.abs(d.value)/scale*48,base=baseline.get(d.name),hasBase=Number.isFinite(base);
    return `<div class="next-matchup-row"><span>${esc(d.name)}</span><div class="next-matchup-track" aria-hidden="true"><i style="left:${d.value>=0?50:50-width}%;width:${width}%"></i>${hasBase?`<b class="matchup-baseline" style="left:${50+base/scale*48}%" title="現任 ${sign(base,3)} 分"></b>`:''}</div><span class="num"><strong>${sign(d.value,3)}</strong><small>現任 ${hasBase?sign(base,3):'未提供'}</small></span></div>`;
  }).join('')}<small class="mut">中線為 0；候選共用尺度。含疲勞，非實際失分。</small></div>`;
}
function comparisonPanel(R, selected, tab) {
  if (!R) return '';
  const pen = tab === 'pen', rows = pen ? R.bullpen?.rows : R.candidates;
  if (!Array.isArray(rows)) return '';
  const nameKey = pen ? '投手' : '球員', current = rows.find(r => r['角色'] === (pen ? '場上' : '現任'));
  if (!current) return '';
  let choices = rows.filter(r => r !== current);
  if (selected && selected !== current[nameKey]) choices = choices.filter(r => r[nameKey] === selected);
  else choices = [...comparisonNames(R,tab)].map(name=>choices.find(r=>r[nameKey]===name)).filter(Boolean);
  const deltaKey = pen ? '守方勝率增減' : '相對現任';
  const chartScale = Math.max(0.01, ...rows.map(r => Math.abs(r[deltaKey])).filter(Number.isFinite));
  const chart = choices.length ? `<div class="candidate-chart"><div class="candidate-chart-key"><span>較不利</span><span>現任 0</span><span>較有利</span></div>${choices.map(x => {
    const delta = x[deltaKey];
    if (!Number.isFinite(delta)) return '';
    const width = Math.abs(delta) / chartScale * 48;
    return `<div class="candidate-chart-row"><span class="candidate-chart-name">${esc(x[nameKey])}</span><div class="candidate-chart-track" aria-hidden="true"><i class="${delta >= 0 ? 'positive' : 'negative'}" style="left:${delta >= 0 ? 50 : 50-width}%;width:${width}%"></i></div><span class="num">${sign(delta)}<small> 百分點</small></span></div>`;
  }).join('')}</div>` : '';
  const card = x => {
    const hDelta = x['階層式'] - current['階層式'];
    const gDelta = x['機器學習'] == null || current['機器學習'] == null ? null : x['機器學習'] - current['機器學習'];
    const disagreement = gDelta != null && hDelta * gDelta <= 0;
    const delta = pen ? x['守方勝率增減'] : x['相對現任'];
    const low = x['樣本球數'] < 500 || current['樣本球數'] < 500 || !!x['資料警示'] || !!current['資料警示'];
    const status = low ? '資料有限' : disagreement ? '模型分歧' : Math.abs(delta) < 0.005 ? '差距極小，難以區分' : '排序僅供參考';
    const direction = pen ? '失分價值越低越好' : '得分值越高越好';
    const reason = pen
      ? (x['疲勞'] && x['疲勞'] !== '-' ? `<p class="compare-warning">${esc(x['疲勞'])}</p>` : '')
      : `<p>${esc(x['守備說明'])}</p>`;
    const decomposition=pen?'':`<dl class="compare-values">${[['本身能力','本身能力'],['球路適性','球路適性'],['左右投打','左右優勢']].map(([label,key]) => `<div><dt>${label}差值</dt><dd>${sign(x[key]-current[key],3)}</dd></div>`).join('')}</dl>`;
    const matchupScale=Math.max(.01,...rows.flatMap(r=>(r['對決明細']||[]).map(d=>Math.abs(d.runs+d.fatigue))).filter(Number.isFinite));
    const matchupChart = pen ? pitcherMatchupChart(x['對決明細'],matchupScale,current['對決明細']) : '';
    return `<article class="compare-card"><h3>${esc(x[nameKey])}<span class="chip">${status}</span></h3>
      <p class="compare-delta num">相對現任 ${sign(delta)} 百分點</p>${reason}${matchupChart}
      <details><summary>詳細拆解</summary>${decomposition}${pen?`<p class="num">失分價值：候選 ${x['預估失分'].toFixed(3)}／現任 ${current['預估失分'].toFixed(3)}</p>`:''}<p>${direction}；${pen ? '以下為疲勞調整前的合計' : '以下為每打席得分值'}。</p>
      <p class="num">階層式差值 ${Number.isFinite(hDelta) ? sign(hDelta,3) : '未匯出'}；逐球模型差值 ${gDelta == null ? '未使用／未匯出' : sign(gDelta,3)}</p>${pen ? '<p>這是得分期望變化的價值，可為負值；不是實際失分數。單位為分。</p>' : ''}
      <p>候選 ${Math.round(x['樣本球數'])} 球；現任 ${Math.round(current['樣本球數'])} 球。${!pen ? `投手對此側 ${x['投手對此側樣本'] ?? '未記錄'} 球。` : ''}比較池 ${x['比較池人數'] ?? '未記錄'} 人。</p>
      <p>${esc(x['資料警示'] || '')}${x['資料警示'] && current['資料警示'] ? '；' : ''}${esc(current['資料警示'] || '')}</p><p>模型分歧與樣本量是判讀線索，不能解讀為候選勝出的機率。</p></details></article>`;
  };
  return `<div class="card comparison"><div class="card-h"><h2>現任與候選比較</h2><span class="hint">基準：${esc(current[nameKey])}</span></div><div class="card-b">
    <p class="mut">${pen ? `對上接下來 ${R.bullpen.next.length} 棒。` : '同一投手、同一局勢。'}</p>
    <p class="compare-limit mut" role="status">最近選取 ${choices.length}/${COMPARISON_LIMIT}</p>
    <div class="compare-chips">${choices.map(r=>`<button type="button" data-remove-compare="${esc(r[nameKey])}" aria-label="移除 ${esc(r[nameKey])} 的比較">${esc(r[nameKey])} <span aria-hidden="true">×</span></button>`).join('')}</div>
    ${chart}<div class="compare-grid">${choices.length ? choices.map(card).join('') : rows.length>1?'<p>選擇候選加入比較。</p>':'<p>沒有其他已確認可用人選，目前只能評估現任。</p>'}</div></div></div>`;
}
function recommendation(cands) {
  const cur = cands.find((c) => c["角色"] === "現任");
  const bench = cands.filter((c) => c["角色"] === "代打");
  const playable = bench.filter((c) => c["守備"] !== "bad");
  if (!playable.length) return { kind: "neutral", title: `建議讓 ${cur["球員"]} 續打`, text: "板凳沒有可用且守備排得出來的人選。" };
  const best = playable[0];
  const diff = best["預估勝率"] - cur["預估勝率"];
  if (Math.abs(diff) < 0.005) return {kind:'neutral', title:'差距極小，難以區分',
    text:`相對 ${cur["球員"]}，估計差值 ${sign(diff,4)} 百分點；差距低於顯示精度，並非統計上的相等，不能只依排序認定必須換人。`};
  if (diff <= 0) return { kind: "neutral", title: `目前估計以 ${cur["球員"]} 續打較佳`, text: "可用候選沒有更高的估計值；這不是續打必然較好的保證。" };
  const def = best["守備"] === "warn" ? `　${best["守備說明"]}` : "";
  const disagree = best["機器學習"] != null && cur["機器學習"] != null &&
    (best["階層式"] - cur["階層式"]) * (best["機器學習"] - cur["機器學習"]) <= 0;
  const low = best["樣本球數"] < 500 || cur["樣本球數"] < 500 || !!best['資料警示'] || !!cur['資料警示'];
  return {kind:best["守備"] === "warn" ? "warn" : "neutral", best:best["球員"],
    title:disagree ? "兩模型分歧" : low ? "候選資料有限，需審慎判斷" : `估計較佳人選：${best["球員"]}`,
    text:`比 ${cur["球員"]} ${sign(diff)} 百分點。${disagree ? "估計有分歧，請審慎判斷。" : "差值僅供參考，仍須確認上場狀況。"}${def}`};
}

function renderResult(preserveTabs = false) {
  const retainedTabs = preserveTabs ? $('#resultBody .tabs') : null;
  const focusedTab = retainedTabs?.contains(document.activeElement) ? document.activeElement : null;
  ++detailGeneration;
  const R = S.last, s = R.situation;
  const view = R.view;
  const activeTab = view === 'replay' ? (S.tab || 'ph') : view === 'defense' ? 'pen' : 'ph';
  const halfZh = s.half === "away" ? "上" : "下";
  const outs = [1, 2].map((i) => `<i class="${i <= s.outs ? "on" : ""}"></i>`).join("");
  const levPct = Math.min(100, R.leverage / 30 * 100), avgPct = R.league_leverage / 30 * 100;
  const diff = s.bat_score - s.fld_score;
  const levTxt = R.leverage >= 15 ? "高張力" : R.leverage >= 10 ? "中高張力" : R.leverage >= 6 ? "一般" : "低張力";

  let html = `
  <div class="card">
    <div class="scoreboard">
      <div class="sb-top">
      <div class="sb-inning num">${s.inning}<small>局${halfZh}</small></div>
      <div class="sb-score">
        <div class="sb-team"><div class="t">${esc(s.bat_team || "進攻方")}</div><div class="s num">${s.bat_score}</div></div>
        <div class="sb-vs">:</div>
        <div class="sb-team"><div class="t">${esc(s.fld_team || "防守方")}</div><div class="s num">${s.fld_score}</div></div>
      </div>
      </div><div class="sb-context">
      <div class="sb-mini">${miniDiamond(s.bases)}<div><div class="outs-ro">${outs}</div><div class="mut" style="font-size:12px;margin-top:2px">${s.outs} 出局・${BASES[s.bases]}</div></div></div>
      <div class="sb-pitcher"><span class="mut">投手</span> <b>${esc(s.pitcher)}</b> ${handChip(s.phand)}
        ${s.pitch_count != null ? `<div class="mut num" style="font-size:12px">${s.starter ? "先發" : "後援"}・本場已投 <b class="${(s.starter && s.pitch_count >= 90) || (!s.starter && s.pitch_count >= 30) ? "neg" : ""}">${s.pitch_count}</b> 球</div>` : ""}</div>
      </div><div class="lev">
        <div class="lbl"><span>局勢張力：<b class="big">${levTxt}</b></span><span>1 分 ≈ <b class="num">${R.leverage.toFixed(1)} 百分點</b></span></div>
        <div class="bar"><div class="fill" style="width:${levPct}%"></div><div class="avg" style="left:${avgPct}%" title="聯盟平均每分 ${R.league_leverage.toFixed(1)} 百分點"></div></div>
        <div class="lbl" style="margin-top:2px"><span>${diff === 0 ? "平手" : diff > 0 ? `進攻方領先 ${diff}` : `進攻方落後 ${-diff}`}</span><span>平均每分 ${R.league_leverage.toFixed(1)} 百分點</span></div>
      </div>
    </div>`;

  if (activeTab === 'ph') {
    const rec = recommendation(R.candidates);
    S.bestName = rec.best;
    html += `<div class="reco ${rec.kind === "go" ? "" : rec.kind}" style="border-top:1px solid var(--line)">
      <div class="ic">${rec.kind === "go" ? "↑" : rec.kind === "warn" ? "!" : "="}</div>
      <div><h3>${esc(rec.title)}</h3><p>${esc(rec.text)}</p></div></div>`;
  } else {
    const rows = R.bullpen.rows, best = rows.filter((r) => r["角色"] === "牛棚")[0];
    const curP = rows.find((r) => r["角色"] === "場上");
    const fat = curP && curP["疲勞調整"] > 0.0005 ? `已計入 ${esc(s.pitcher)} ${curP["用球數"]} 球的疲勞（${R.bullpen.next.length} 打席 +${curP["疲勞調整"].toFixed(3)} 分）。` : "";
    S.bestName = null;
    if (best && Math.abs(best["守方勝率增減"]) < 0.005) {
      html += `<div class="reco neutral" style="border-top:1px solid var(--line)"><div class="ic">=</div><div><h3>差距極小，難以區分</h3><p>相對場上投手，估計差值 ${sign(best["守方勝率增減"],4)} 百分點；差距低於顯示精度，不宜只依排序換投。${fat}</p></div></div>`;
    } else if (best && best["守方勝率增減"] > 0) {
      html += `<div class="reco" style="border-top:1px solid var(--line)"><div class="ic">↻</div><div><h3>可考慮換上 ${esc(best["投手"])}</h3>
        <p>對上接下來 ${R.bullpen.next.length} 棒，相對場上投手的守方勝率換算差值 ${sign(best["守方勝率增減"])} 百分點。請確認今日可用狀態。${fat}${best["疲勞"] !== "-" ? `　警示 ${esc(best["投手"])}：${esc(best["疲勞"])}` : ""}</p></div></div>`;
    } else {
      html += `<div class="reco neutral" style="border-top:1px solid var(--line)"><div class="ic">=</div><div><h3>${best ? `目前估計以 ${esc(s.pitcher)} 續投較佳` : "沒有勾選可用牛棚"}</h3><p>${best ? "候選沒有較低的估計失分；不代表已證明續投最佳。" : "目前只能顯示場上投手；請確認是否有可用後援。"}${fat}</p></div></div>`;
    }
  }
  if(s.inning>=10)html+=`<p class="situation-note">延長局數沿用第 9 局換算，僅供參考。</p>`;
  if(s.inning>=9&&s.half==='home'&&((activeTab==='pen'?s.fld_score:s.bat_score)>(activeTab==='pen'?s.bat_score:s.fld_score)))html+=`<p class="situation-note">此情境主隊已領先，請確認是否仍有下一打席。</p>`;
  if (R.actual) {
    const a = R.actual;
    const bench = R.candidates.filter((c) => c["角色"] === "代打");
    const rank = bench.findIndex((c) => c["球員"] === a.batter) + 1;
    html += `<div class="actual"><span class="mut">實際發生：</span>
      <span>${a.is_ph ? `換上 <b>${esc(a.batter)}</b> 代打${rank ? `（系統排名第 ${rank} / ${bench.length}）` : ""}` : `<b>${esc(a.batter)}</b> 續打`}</span>
      <span>結果 <b>${esc(resultLabel(a.result))}</b></span><span>WPA <b class="${cls(a.WPA, 0)}">${sign(a.WPA, 3)}</b></span></div>`;
  }
  html += `</div>`;


  // 主表 + 側欄

  const showTabs = view === "replay";
  const tab = S.tab || (view === "defense" ? "pen" : "ph");
  html += `<div class="card evaluation-card">`;
  if (showTabs) html += `<div class="tabs"><button data-t="ph" class="${tab === "ph" ? "on" : ""}">代打評估（進攻方）</button><button data-t="pen" class="${tab === "pen" ? "on" : ""}">換投評估（防守方）</button></div>`;
  else html += `<div class="card-h"><h2>${view === "defense" ? "換投評估" : "代打評估"}</h2><span class="hint">${view === "defense" ? "" : ""}</span></div>`;
  html += `<div class="tbl-wrap" tabindex="0" role="region" aria-label="球員評估表，可左右捲動">${(showTabs ? tab : view === "defense" ? "pen" : "ph") === "pen" ? penTable(R) : phTable(R)}</div></div>`;
  html += `<div id="candidateCompare">${comparisonPanel(R,null,activeTab)}</div><div id="pitchArsenal">${mixCard(R)}</div>`;
  html += `<div class="detail-grid"><div id="pitchChange"></div><div id="detail"></div></div>`;
  html += `<div id="detailStatus" class="sr-only" role="status"></div><div class="foot"><p>分數為相對排名，非成功機率。請確認今日可上場名單。</p><details><summary>資料與評估依據</summary>評估方法：<b>${esc(R.method || "階層式")}</b>。<br>
    表中細線僅為階層式估計的近似標準誤，不是完整集成區間或排名把握度。球路拆解也只解釋階層式部分。失分價值可為負值，不是實際失分數。<br>
    階層式截止：${esc(R.model_cutoff)}；逐球模型截止：${esc(R.ml_cutoff || '舊快照未記錄')}（均不含截止日）。<br>
    ${esc(R.availability || '歷史快照的可用名單與守位可能包含推估資訊，請審慎使用')}。<br>
    ${esc(R.fielding_source || '守位來源未記錄')}。資料來源：Rebas、ldkrsi／中華職棒守位統計。</details><details class="rules-note"><summary>換人規則提醒</summary><ul><li>已退場球員不可再上場；名單須排除已退場與未登錄者。</li><li>代打承接原棒次；替換指定打擊時須確認 DH 資格。</li><li>新任投手、換局時已上丘投手須符合最低投球義務及例外規定；接下來三棒是評估範圍，不是換投規則。</li><li>2024–2025 一軍例行賽延長局最多 12 局；突破僵局的二壘預設可按實際局面修改。</li></ul><p>本站未追蹤完整換人紀錄、DH 存續及登錄資格，不能取代裁判或正式攻守名單。</p><a href="https://www.cpbl.com.tw/" target="_blank" rel="noopener noreferrer">CPBL 官方規則入口（官網頁尾）</a></details></div>`;
  $("#resultBody").innerHTML = html;
  if (retainedTabs) {
    $('#resultBody .tabs').replaceWith(retainedTabs);
    retainedTabs.getBoundingClientRect(); // Establish the previous marker position before changing sides.
    retainedTabs.querySelectorAll('button').forEach(b=>{
      b.classList.toggle('on', b.dataset.t===activeTab);
      b.setAttribute('aria-pressed',String(b.dataset.t===activeTab));
    });
    focusedTab?.focus({preventScroll:true});
  }
  bindComparison(R,activeTab);
  bindTableComparison(R,activeTab);
  bindMixSwitch();
  mountPitchChange(R.situation.pitcher);

  $$(".tabs button").forEach((b) => {
    b.setAttribute('aria-pressed',String(b.dataset.t===activeTab));
    b.onclick = () => { if(S.tab===b.dataset.t)return;S.tab = b.dataset.t; renderResult(true); };
  });
  $$("tr[data-batter]").forEach((tr) => tr.onclick = e => {if(e.target.closest('a,input,label'))return;showDetail(tr.dataset.batter, R.situation.pitcher, tr);});
  $$('tr[data-pitcher]').forEach(tr=>{
    const radio=tr.querySelector('[name="viewPitcher"]');
    const select=()=>showDetail(R.bullpen.next[0],tr.dataset.pitcher,tr);
    if(radio)radio.onchange=select;tr.onclick=e=>{if(e.target.closest('a,input,label'))return;select();};
  });
  $$(".player-official").forEach(link => link.onclick = event => event.stopPropagation());
  const first = $("tr[data-batter].best-row") || $("tr[data-batter]");
  if (first && (showTabs ? tab : view === "defense" ? "pen" : "ph") === "ph") showDetail(first.dataset.batter, R.situation.pitcher, first, false);
  const currentPitcher = $('tr[data-pitcher].cur') || $('tr[data-pitcher]');
  if (currentPitcher && (showTabs ? tab : view === 'defense' ? 'pen' : 'ph') === 'pen') showDetail(R.bullpen.next[0], currentPitcher.dataset.pitcher, currentPitcher, false);
}

const TIER = (v) => (v >= 80 ? ["s5", "極佳"] : v >= 60 ? ["s4", "佳"] : v >= 40 ? ["s3", "普通"] : v >= 20 ? ["s2", "不利"] : ["s1", "很不利"]);
function scoreBadge(v, tip) {
  if (v == null) return '<span class="mut">基準不足</span>';
  const [c, lab] = TIER(v);
  return `<div class="score ${c}" title="${esc(tip)}"><div>${v}<small>${lab}</small></div></div>`;
}
const SCORE_LEGEND = `<div class="score-legend"><span>價值分數：</span><span><i style="background:#1f8a55"></i>80+ 極佳</span>
  <span><i style="background:#7fd9a8"></i>60–79 佳</span><span><i style="background:#999"></i>40–59 普通</span>
  <span><i style="background:#f0b27a"></i>20–39 不利</span><span><i style="background:#c2412d"></i>&lt;20 很不利</span></div>`;

function miniDiamond(b) {
  const f = (bit) => (b & bit ? "var(--warn)" : "var(--panel)");
  return `<svg viewBox="0 0 40 34" width="40" height="34"><g stroke="var(--muted)" stroke-width="1.5">
    <rect x="16" y="2" width="8" height="8" transform="rotate(45 20 6)" fill="${f(2)}"/>
    <rect x="29" y="14" width="8" height="8" transform="rotate(45 33 18)" fill="${f(1)}"/>
    <rect x="3" y="14" width="8" height="8" transform="rotate(45 7 18)" fill="${f(4)}"/></g></svg>`;
}

function dbar(v, err, scale) {
  const w = 45, px = (x) => Math.max(-w, Math.min(w, x / scale * w));
  const len = px(v);
  const left = len >= 0 ? w : w + len;
  const e1 = w + px(v - err), e2 = w + px(v + err);
  return `<div class="dbar"><div class="axis"></div><div class="b ${v >= 0 ? "p" : "n"}" style="left:${left}px;width:${Math.abs(len)}px"></div>
    <div class="err" style="left:${e1}px;width:${Math.max(1, e2 - e1)}px"></div></div>`;
}

function phTable(R) {
  const c = R.candidates;
  const scale = Math.max(0.3, ...c.map((x) => Math.abs(x["預估勝率"]) + x["誤差"]));
  const rows = c.map((x) => {
    const cur = x["角色"] === "現任", best = x["球員"] === S.bestName;
    const d = x["守備"];
    return `<tr data-batter="${esc(x["球員"])}" class="${cur ? "cur" : ""} ${best ? "best-row" : ""}">
      <td class="ncell"><span class="role">${cur ? "現任" : "代打"}</span>${cur?`<button type="button" class="baseline-detail" aria-label="查看 ${esc(x["球員"])} 對決">基準</button>`:comparisonCircle(R,"ph",x["球員"])}${officialPlayerLink(x["球員"])} ${handChip(x["打擊"])}${best ? `<span class="best">估計較佳</span>` : ""}
        <div class="parts">${(x["可守"] || "-").split(",").map((p) => POS[p] || p).join("・")}</div></td>
      <td>${scoreBadge(x["價值分數"], `面對 ${R.situation.pitcher} 的比较池百分位；截止日之前達門檻的打者，早季回退前一季`)}</td>
      <td><div class="vcell" title="${x["機器學習"] != null ? `階層式 ${sign(x["階層式"], 3)}・梯度提升樹 ${sign(x["機器學習"], 3)}（每打席得分值，各占一半）` : ""}"><div class="vnum num"><span class="${cls(x["預估勝率"], 0.02)}">${sign(x["預估勝率"])} 百分點</span>${cur ? "" : `<div class="parts ${cls(x["相對現任"], 0.02)}">比現任 ${sign(x["相對現任"])} 百分點</div>`}</div>${dbar(x["預估勝率"], x["誤差"], scale)}</div></td>
      <td style="white-space:nowrap"><span class="chip c-${x["可信度"]}">${x["可信度"]}樣本</span><div class="mut num" style="font-size:11px">${Math.round(x["樣本球數"])} 球</div></td>
      <td><div class="def"><span class="d ${d}">${d === "ok" ? "✓" : d === "warn" ? "!" : "✕"}</span><span>${esc(x["守備說明"])}</span></div></td>
    </tr>`;
  }).join("");
  return `<div class="card-b" style="padding-bottom:0">${SCORE_LEGEND}</div><table class="t"><thead><tr><th>球員</th><th title="比較池百分位；不是成功機率">價值分數</th><th>勝率變化（相對聯盟平均）</th><th>樣本充分度</th><th>守備檢查</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function penTable(R) {
  const rows = R.bullpen.rows;
  const scale = Math.max(0.5, ...rows.map((x) => Math.abs(x["守方勝率增減"])));
  const body = rows.map((x, i) => {
    const cur = x["角色"] === "場上";
    const best = !cur && i === 1 && x["守方勝率增減"] > 0;
    return `<tr data-pitcher="${esc(x["投手"])}" class="${cur ? "cur" : ""}">
      <td class="ncell" title="樣本 ${x["樣本球數"]} 球"><span class="role">${cur ? "場上" : "牛棚"}</span>${cur?`<button type="button" class="baseline-detail" aria-label="查看 ${esc(x["投手"])} 配球與對決">基準</button>`:comparisonCircle(R,"pen",x["投手"])}${officialPlayerLink(x["投手"])} ${handChip(x["投"] || "R")}${best ? `<span class="best">估計較佳</span>` : ""}
        <div class="parts">${cur ? `本場已投 ${x["用球數"] ?? "—"} 球` : "未登板"}</div></td>
      <td>${scoreBadge(x["價值分數"], '對上後續打者的比較池百分位；截止日之前達門檻的後援，早季回退前一季')}</td>
      <td><div class="vcell"><span class="vnum num ${cls(x["守方勝率增減"], 0.02)}">${cur ? "基準" : sign(x["守方勝率增減"]) + " 百分點"}</span>${dbar(x["守方勝率增減"], 0, scale)}</div></td>
      <td class="num">${x["預估失分"].toFixed(3)}${x["疲勞調整"] > 0.0005 ? `<div class="neg" style="font-size:11px">含疲勞 +${x["疲勞調整"].toFixed(3)}</div>` : ""}</td>
      <td>${x["疲勞"] === "-" ? `<span class="mut">—</span>` : `<span class="chip c-中">${esc(x["疲勞"])}</span>`}</td></tr>`;
  }).join("");
  return `<div class="card-b mut" style="font-size:12px;padding-bottom:0">對上接下來 ${R.bullpen.next.length} 棒：${R.bullpen.next.map(esc).join("、")}<div style="margin-top:6px">${SCORE_LEGEND}</div></div>
    <table class="t"><caption class="sr-only">固定三打席比較，未模擬換局與後續調度。</caption><thead><tr><th>投手</th><th title="比較池百分位；不是成功機率">價值分數</th><th>勝率變化（相對場上投手）</th><th>失分價值（${R.bullpen.next.length} 打席）</th><th>疲勞／警示</th></tr></thead><tbody>${body}</tbody></table>`;
}

function mixCard(R) {
  const mix = R.pitch_mix;
  const defaultHand=R.mix_hand||'R';
  const panel = h => {
    if (!mix?.[h]) return '<p class="mut">此側資料未提供。</p>';
    if(!mix[h].n)return '<p class="mut">此側沒有可用個人逐球紀錄；對決估計採聯盟回退。</p>';
    const cells = mix[h].cells;
    const groups = GROUPS.map(g => ({g, hi:cells[g+'高中'] || 0, lo:cells[g+'低'] || 0})).sort((a,b) => (b.hi+b.lo)-(a.hi+a.lo));
    return `<p class="mix-count">有效樣本 ${mix[h].n} 球 · 主要球種：${esc(groups[0].g)}${groups[1].hi+groups[1].lo > 0 ? `、${esc(groups[1].g)}` : ''}</p><div class="arsenal-grid">${groups.map(({g,hi,lo}) => `<article class="arsenal-pitch" style="--pitch-color:${GROUP_COLOR[g]}"><h3>${esc(g)}</h3><strong class="num">${((hi+lo)*100).toFixed(1)}<small>%</small></strong><div class="arsenal-meter" aria-hidden="true"><i style="width:${(hi+lo)*100}%"></i></div><p>中高區 ${(hi*100).toFixed(1)}% · 低球 ${(lo*100).toFixed(1)}%</p></article>`).join('')}</div>`;
  };
  return `<section class="card arsenal-card"><div class="card-h"><h2>${esc(R.situation.pitcher)} 的球路</h2><div class="mix-switch" role="group" aria-label="球路面對的打者"><button type="button" data-mix-hand="R" aria-pressed="${defaultHand==='R'}">對右打</button><button type="button" data-mix-hand="L" aria-pressed="${defaultHand==='L'}">對左打</button></div></div><div class="card-b"><div data-mix-panel="R" ${defaultHand==='R'?'':'hidden'}>${panel('R')}</div><div data-mix-panel="L" ${defaultHand==='L'?'':'hidden'}>${panel('L')}</div><p class="mix-count">四類球種的模型配球估計；高低區為比例分類。</p></div></section>`;
}
function bindMixSwitch() {
  $$('[data-mix-hand]').forEach(button => button.onclick = () => {
    $$('[data-mix-hand]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
    $$('[data-mix-panel]').forEach(panel => { panel.hidden = panel.dataset.mixPanel !== button.dataset.mixHand; });
  });
}

let detailGeneration = 0;
function mountPitchChange(pitcher, hand = "ALL") {
  const cutoff = String(S.last.view === 'replay' ? S.last.situation.date : S.last.model_cutoff).slice(0, 10);
  const season = S.last.view === "replay" ? Number(cutoff.slice(0, 4)) : 2025;
  PitchChange.mount({element: $("#pitchChange"), pitcher, cutoff, season, hand,
    fetcher: STATIC ? PitchChange.staticResult : (o) => api(`api/pitch-change?${new URLSearchParams(o)}`)});
}
async function showDetail(batter, pitcher, tr, updateComparison = true) {
  const token = ++detailGeneration;
  $$("tr.sel").forEach((x) => x.classList.remove("sel"));
  tr?.classList.add("sel");
  const radio=tr?.querySelector?.('[name="viewPitcher"]');if(radio)radio.checked=true;
  // Detail browsing is independent of the two-candidate comparison selection.
  mountPitchChange(pitcher); // Independent of a failing eight-cell detail request.
  const box = $("#detail");
  $('#pitchArsenal').innerHTML=`<section class="card"><div class="card-h"><h2>${esc(pitcher)} 的球路</h2></div><p class="card-b">載入中…</p></section>`;
  box.innerHTML = `<div class="card" style="margin-top:16px"><div class="card-b"><span class="loading"></span></div></div>`;
  try {
    const d = await api(`api/detail?batter=${encodeURIComponent(batter)}&pitcher=${encodeURIComponent(pitcher)}&date=${S.last.model_cutoff}`);
    if (token !== detailGeneration || box !== $("#detail")) return;
    mountPitchChange(pitcher, d.bhand);
    const mixPayload={situation:{pitcher},mix_hand:d.bhand,pitch_mix:{[d.bhand]:{n:d.mix_n,cells:Object.fromEntries(d.cells.map(c=>[c.cell,c.usage]))}}};
    if(pitcher===S.last.situation.pitcher){mixPayload.pitch_mix=S.last.pitch_mix;}
    $('#pitchArsenal').innerHTML=mixCard(mixPayload);bindMixSwitch();
    $('#detailStatus').textContent=`目前查看 ${batter} 對 ${pitcher}`;
    const cell = (k) => d.cells.find((c) => c.cell === k);
    const tile = (k) => {
      const c = cell(k);
      const wd = c.whiff_dev * 100;
      return `<div class="c" title="打者在此格的樣本 ${Math.round(c.n)} 球">
        <div class="u" style="height:${Math.min(100, c.usage * 100)}%"></div>
        <div class="k num">${c.usage>0&&c.usage<.01?"<1%":(c.usage*100).toFixed(0)+"%"}</div>
        <div class="w num ${wd > 0.5 ? "neg" : wd < -0.5 ? "pos" : "mut"}">揮空 ${wd >= 0 ? "+" : "−"}${Math.abs(wd).toFixed(1)}</div></div>`;
    };
    box.innerHTML = `<div class="card" style="margin-top:16px"><div class="card-h"><h2>${esc(d.batter)} vs ${esc(d.pitcher)}</h2>
      <span class="hint">${d.bhand === "L" ? "左" : "右"}打 vs ${d.phand === "L" ? "左" : "右"}投</span></div><div class="card-b">
      <div class="heat"><div></div><div class="hh">中高區</div><div class="hh">低球</div>
        ${GROUPS.map((g) => `<div class="rl">${g}</div>${tile(g + "高中")}${tile(g + "低")}`).join("")}</div>
      <p class="mut" style="font-size:12px;margin:10px 0 0">配球：比例；揮空差值：百分點（相對自身平均）。</p>
      <p class="detail-unit">能力拆解 · 分／打席</p><div class="breakdown">
        <div><small>本身能力</small><b class="num ${cls(d.skill, 0.002)}">${sign(d.skill, 3)}</b></div>
        <div><small>球路適性</small><b class="num ${cls(d.fit, 0.002)}">${sign(d.fit, 3)}</b></div>
        <div><small>左右投打</small><b class="num ${cls(d.platoon, 0.002)}">${sign(d.platoon, 3)}</b></div>
      </div></div></div>`;
  } catch (e) {
    if (token !== detailGeneration || box !== $("#detail")) return;
    $('#pitchArsenal').innerHTML=`<section class="card"><div class="card-h"><h2>${esc(pitcher)} 的球路</h2></div><p class="card-b">此對決資料未提供，請重新選取。</p></section>`;
    box.innerHTML = `<div class="err-box" style="margin-top:16px">此對決明細未提供或載入失敗，請重新選取。</div>`;
  }
}

init().catch((e) => {
  $("#emptyState").innerHTML = `<div class="err-box" role="alert">資料尚未載入，請確認連線後重試。<button class="retry">重新載入頁面</button></div>`;
  $("#emptyState .retry").onclick = () => location.reload();
});
