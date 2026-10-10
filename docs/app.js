"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const POS = { C: "捕手", "1B": "一壘", "2B": "二壘", "3B": "三壘", SS: "游擊", LF: "左外野", CF: "中外野", RF: "右外野", DH: "指定打擊" };
const GROUPS = ["速球", "滑卡", "曲球", "低落"];
const GROUP_COLOR = { 速球: "#d9534f", 滑卡: "#e0a03a", 曲球: "#4a7fd0", 低落: "#3f9a6b" };
let officialPlayers = {};
let playerNumbers2025 = {};
function matchesPlayerSearch(name,team,query) {
  const q=String(query||'').normalize('NFKC').trim();
  if(!q)return true;
  const number=q.replace(/^#/, '').replace(/號$/, '').trim();
  if(/^\d+$/.test(number))return playerNumbers2025[team]?.[name]===number;
  return String(name).normalize('NFKC').includes(q);
}
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
  mode: "custom", view: "offense", starter: false, inning: 1, half: "away", outs: 0, bases: 0,
  teams: [], roster: {}, games: [], game: null, pa: null, last: null, selected: null,
  bench: new Set(), ready: false,
};
let resultInputKey = null, loadedTeams = {my:'',opp:''}, groupControl = null;
const benchOpen = new Map(), benchSearchOpen = new Map(), fieldErrors = new Map();
const comparisonSelections = new WeakMap();
const comparisonNotices = new WeakMap();
function evaluationKey() {
  const value=id=>$(id)?.value || '';
  return JSON.stringify([S.view,S.inning,S.half,S.outs,S.bases,value('#myTeam'),value('#oppTeam'),value('#myScore'),value('#oppScore'),
    S.view==='offense'?[value('#dueBatter'),value('#duePos'),value('#oppPitcher'),[...S.bench].filter(n=>n!==value('#dueBatter')).sort()]:
    [value('#myPitcher'),value('#pitchCount'),S.starter,...['#nb1','#nb2','#nb3'].map(value),$$('#penList input:checked').map(i=>i.value).filter(n=>n!==value('#myPitcher')).sort(),streakMarks()]],
    [value('#recentWeight'),value('#fatigueD2'),value('#fatigueD3')]);
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
  const enteringExtras=S.inning<10&&next>=10;
  S.inning=next;if(S.mode==='custom'&&enteringExtras)S.bases=2;renderState();
}
let rosterGeneration = 0, gamesGeneration = 0, gameGeneration = 0, runGeneration = 0;
/* 滑動效果（docs/motion.js）；沒有載入時所有切換照常運作，只是沒有動畫。 */
const motion = () => typeof Motion !== 'undefined' ? Motion : null;
function slideIn(el, dir) { motion()?.slideIn(el, dir); }

function clearResult() {
  if (motion()?.drawerOpen()) motion().closeDrawer();
  ++runGeneration;
  ++detailGeneration;
  S.last = null;
  resultInputKey = null;
  $("#resultBody").innerHTML = "";
  $("#resultBody").classList.add("hidden");
  $("#emptyState").classList.remove("hidden");
  $('.mobile-jump a[href="#result"]').hidden = true;
  $("#evalBtn").disabled = !S.ready;
  $("#evalBtn").innerHTML = uiIcon("compare") + "評估";
}
function invalidateCustom(event) {
  clearValidErrors();
  if (S.mode !== 'custom' || ['benchFilter','penFilter'].includes(event?.target?.id) || event?.target?.closest?.('#pitcherGroups')) return;
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

/* ---------------- 偏好設定與我的預設情境（存在瀏覽器） ---------------- */
const PREF_KEY = 'bb.prefs.v1';
function readPrefs() { try { return JSON.parse(localStorage.getItem(PREF_KEY)) || {}; } catch { return {}; } }
function writePrefs(p) { try { localStorage.setItem(PREF_KEY, JSON.stringify(p)); return true; } catch { return false; } }
const clampNum = (v, hi) => { const n = Number(v); return Number.isFinite(n) ? Math.min(hi, Math.max(0, n)) : 0; };
function prefSettings() {
  return { recent_weight: clampNum($('#recentWeight').value, 100) / 100,
    fatigue_d2: clampNum($('#fatigueD2').value, 0.5), fatigue_d3: clampNum($('#fatigueD3').value, 0.5) };
}
function renderPrefOutputs() { $('#recentWeightOut').textContent = $('#recentWeight').value + '%'; }
function savePrefSettings() {
  const p = readPrefs();
  p.recentWeight = +$('#recentWeight').value; p.fatigueD2 = prefSettings().fatigue_d2; p.fatigueD3 = prefSettings().fatigue_d3;
  writePrefs(p); renderPrefOutputs();
}
function loadPrefSettings() {
  const p = readPrefs();
  if (p.recentWeight != null) $('#recentWeight').value = clampNum(p.recentWeight, 100);
  if (p.fatigueD2 != null) $('#fatigueD2').value = clampNum(p.fatigueD2, 0.5);
  if (p.fatigueD3 != null) $('#fatigueD3').value = clampNum(p.fatigueD3, 0.5);
  renderPrefOutputs();
}
function presetStatus(t) { $('#presetStatus').textContent = t; }
function saveSituation() {
  const p = readPrefs();
  p.situation = { view: S.view, myTeam: $('#myTeam').value, oppTeam: $('#oppTeam').value, inning: S.inning, half: S.half,
    outs: S.outs, bases: S.bases, myScore: +$('#myScore').value || 0, oppScore: +$('#oppScore').value || 0 };
  presetStatus(writePrefs(p) ? '已存為你的預設情境，下次開啟會自動帶入。' : '瀏覽器不允許儲存（例如無痕模式）。');
}
async function applySituation(sit, quiet = false) {
  if (!sit) { if (!quiet) presetStatus('還沒有存過預設情境。'); return; }
  const valid = t => S.teams.includes(t);
  if ((valid(sit.myTeam) && sit.myTeam !== $('#myTeam').value) || (valid(sit.oppTeam) && sit.oppTeam !== $('#oppTeam').value)) {
    if (valid(sit.myTeam)) $('#myTeam').value = sit.myTeam;
    if (valid(sit.oppTeam) && sit.oppTeam !== $('#myTeam').value) $('#oppTeam').value = sit.oppTeam;
    syncTeamChoices('myTeam'); await refreshCustom();
  }
  S.inning = Math.min(12, Math.max(1, +sit.inning || 1)); S.half = sit.half === 'home' ? 'home' : 'away';
  S.outs = Math.min(2, Math.max(0, +sit.outs || 0)); S.bases = Math.min(7, Math.max(0, +sit.bases || 0));
  $('#myScore').value = Math.max(0, +sit.myScore || 0); $('#oppScore').value = Math.max(0, +sit.oppScore || 0);
  if (sit.view === 'defense' || sit.view === 'offense') setView(sit.view);
  renderState(); syncScoreControls(); invalidateCustom();
  if (!quiet) presetStatus('已套用你的預設情境。');
}
function clearSituation() {
  S.inning = 1; S.half = 'away'; S.outs = 0; S.bases = 0;
  $('#myScore').value = 0; $('#oppScore').value = 0;
  renderState(); syncScoreControls(); invalidateCustom(); presetStatus('已清空局面（1 局上、0 出局、無人、0:0）。');
}
/* 連投標記：今天之前連續登板天數（0／1／2 以上），只用在自訂情境的換投評估 */
function streakMarks() {
  const out = {};
  const cur = $('#myPitcher')?.value, v = +($('#myStreak')?.value || 0);
  if (cur && v) out[cur] = v;
  $$('#penList select.streak').forEach(s => { if (+s.value) out[s.dataset.streak] = +s.value; });
  return out;
}
const STREAK_SELECT = name => `<select class="streak" data-streak="${esc(name)}" aria-label="${esc(name)} 今天之前連續登板天數"><option value="0">未連投</option><option value="1">連投第 2 天</option><option value="2">連投第 3 天+</option></select>`;

/* ---------------- 評估原因：每位球員 1–2 項簡單說明 ---------------- */
const HZ = h => (h === 'L' ? '左' : h === 'R' ? '右' : '兩');
function mainPitch(R, bh) {
  const mix = R.pitch_mix && R.pitch_mix[bh === 'L' ? 'L' : 'R'];
  if (!mix) return '';
  const totals = {};
  for (const [cell, v] of Object.entries(mix.cells)) { const g = cell.replace(/(高中|低)$/, ''); totals[g] = (totals[g] || 0) + v; }
  const [g, v] = Object.entries(totals).sort((a, b) => b[1] - a[1])[0] || [];
  return g ? `${g}（${Math.round(v * 100)}%）` : '';
}
function pickReasons(items) {
  items.sort((a, b) => b.s - a.s);
  const top = items.slice(0, 2);
  return top.length ? top : [{ good: null, text: '各項都接近聯盟平均，沒有明顯優劣' }];
}
function batterReasons(x, R) {
  const items = [], p = R.situation.pitcher, ph = R.situation.phand;
  const add = (v, th, good, bad) => { if (v != null && Math.abs(v) >= th) items.push({ s: Math.abs(v) / th, good: v > 0, text: v > 0 ? good : bad }); };
  add(x['本身能力'], 0.008, '整體打擊能力高於聯盟平均', '整體打擊能力低於聯盟平均');
  add(x['左右優勢'], 0.004, `${HZ(x['打擊'])}打對${HZ(ph)}投，左右對戰有利`, `${HZ(x['打擊'])}打對${HZ(ph)}投，同側對決較吃虧`);
  const main = mainPitch(R, x['打擊']);
  add(x['球路適性'], 0.0015, `較能應付${p}的主要球路${main ? ' ' + main : ''}`, `對${p}的主要球路${main ? ' ' + main : ''}容易揮空`);
  if (x['近況權重']) add(x['近況'], 0.004, '近 30 天狀況回溫', '近 30 天狀況下滑');
  return pickReasons(items);
}
function handOf(name) {
  for (const r of Object.values(S.roster)) { const h = r?.hitters?.find(x => x.name === name); if (h) return h.hand; }
  return STATIC && Engine.model()?.bhand ? Engine.model().bhand[name] : null;
}
function pitcherReasons(x, R) {
  const rows = R.bullpen.rows, cur = rows.find(r => r['角色'] === '場上'), items = [];
  const det = x['對決明細'] || [], cdet = (cur && cur['對決明細']) || [];
  if (x !== cur && det.length && cdet.length === det.length) {
    const adv = det.map((d, i) => ({ b: d.batter, v: cdet[i].runs + (cdet[i].fatigue || 0) - d.runs - (d.fatigue || 0) }));
    const best = adv.reduce((a, b) => (b.v > a.v ? b : a)), worst = adv.reduce((a, b) => (b.v < a.v ? b : a));
    if (best.v >= 0.01) items.push({ good: true, s: best.v / 0.01, text: `對 ${best.b} 的對決明顯優於場上投手` });
    if (worst.v <= -0.01) items.push({ good: false, s: -worst.v / 0.01, text: `對 ${worst.b} 的對決不如場上投手` });
  }
  const hands = R.bullpen.next.map(handOf).filter(Boolean), same = hands.filter(h => h === x['投']).length;
  if (hands.length === R.bullpen.next.length) {
    if (same >= 2) items.push({ good: true, s: 1.5, text: `接下來 ${hands.length} 棒有 ${same} 位同側打者，左右對戰有利` });
    else if (same === 0) items.push({ good: false, s: 1.5, text: `接下來 ${hands.length} 棒都是異側打者，左右對戰不利` });
  }
  if (x['價值分數'] != null && x['價值分數'] >= 75) items.push({ good: true, s: 1.2, text: '對這幾棒的預估失分在主力後援中屬前段' });
  else if (x['價值分數'] != null && x['價值分數'] <= 25) items.push({ good: false, s: 1.2, text: '對這幾棒的預估失分在主力後援中屬後段' });
  if (x['近況權重'] && x['近況'] != null && Math.abs(x['近況']) >= 0.004) items.push({ good: x['近況'] < 0, s: Math.abs(x['近況']) / 0.004, text: x['近況'] < 0 ? '近 30 天狀況回溫' : '近 30 天狀況下滑' });
  if (x['疲勞調整'] > 0.0005) items.push({ good: false, s: 9, text: `已加計疲勞 +${x['疲勞調整'].toFixed(3)} 分${x['連投天數'] >= 1 ? `（連投第 ${Math.min(3, x['連投天數'] + 1)} 天${x['連投天數'] >= 2 ? '+' : ''}）` : '（用球數）'}` });
  return pickReasons(items);
}
function reasonsHtml(items) {
  return `<ul class="reasons">${items.map(i => `<li class="${i.good === true ? 'pos' : i.good === false ? 'neg' : 'mut'}"><span class="mark" aria-hidden="true">${i.good === true ? '＋' : i.good === false ? '－' : '・'}</span><span>${esc(i.text)}</span></li>`).join('')}</ul>`;
}
const reasonText = items => items.filter(i => i.good !== null).map(i => i.text).join('、');

/* ---------------- 初始化 ---------------- */
async function init() {
  try { const numbers=await json('data/player-numbers-2025.json'); if(numbers.season===2025&&numbers.teams)playerNumbers2025=numbers.teams; } catch { /* Name search remains usable without number aliases. */ }
  try { officialPlayers = (await json('data/cpbl-players.json')).players || {}; } catch { /* Search remains available when the mapping cannot load. */ }
  try { const d=await json('data/default-lineups-2025.json'); if(d.season===2025&&typeof LineupBoard!=='undefined')LineupBoard.setDefaults(d.teams); } catch { /* Lineup page starts empty without defaults. */ }
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
  loadPrefSettings();
  renderState();
  await refreshCustom();
  await applySituation(readPrefs().situation, true);
  $('#reviewTeam').innerHTML = opts; $('#reviewTeam').value = $('#myTeam').value;
  $('#reviewTeam').onchange = renderReview;
  LineupBoard.mount({element:$('#lineupPage'),teams:S.teams,team,matches:matchesPlayerSearch,pitchCount:()=>$('#pitchCount').value,role:()=>S.starter,applied:applyOwnLineup});
  $$('[data-page]').forEach(b=>b.onclick=()=>showFeaturePage(b.dataset.page));
  bindMotion();
}

let dueFromLineup = false;  // 「輪到的打者」選項目前是否來自場上名單
function ownLineup() { if(typeof LineupBoard==='undefined')return null;const name=$('#myTeam').value,c=LineupBoard.current(name),r=S.roster[name];return c&&r&&LineupBoard.validate(c,r).length===0?c:null; }
function benchEligible(name) { const c=ownLineup();return name!==c?.pitcher&&!c?.slots.some(s=>s.name===name); }
/* 功能頁依選單順序排列；滑入方向與手勢都依這個順序 */
const PAGES = ["evaluation", "lineup", "review"];
const PAGE_EL = {evaluation:"#evaluationPage", lineup:"#lineupPage", review:"#reviewPage"};
const PAGE_SKIP = {evaluation:["#workspace","跳到情境設定"], lineup:["#lineupTitle","跳到場上名單"], review:["#reviewTitle","跳到賽季回顧"]};
function currentPage() { return PAGES.find(p => !$(PAGE_EL[p]).hidden) || "evaluation"; }
async function showFeaturePage(page) {
  if(typeof LineupBoard!=='undefined')LineupBoard.cancelSwap();
  if(motion()?.drawerOpen())motion().closeDrawer();
  const from=currentPage(),evaluation=page==='evaluation';
  PAGES.forEach(p=>{$(PAGE_EL[p]).hidden=p!==page;});
  if(from!==page)slideIn($(PAGE_EL[page]),PAGES.indexOf(page)>PAGES.indexOf(from)?1:-1);
  $('.matchday-intro').hidden=!evaluation;$('.mobile-jump').hidden=!evaluation;$('#modeSeg').hidden=!evaluation;$('#modeCaption').hidden=!evaluation;
  $('.skip-link').href=PAGE_SKIP[page][0];$('.skip-link').textContent=PAGE_SKIP[page][1];
  $$('.feature-nav [data-page]').forEach(b=>{if(b.dataset.page===page)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  if(page==='lineup')await LineupBoard.selectTeam($('#myTeam').value);
  if(page==='review'){if(!$('#reviewTeam').value)$('#reviewTeam').value=$('#myTeam').value;await loadTiming();renderReview();}
  window.scrollTo({top:0,behavior:'auto'});
}
function syncOwnLineup() {
  const c=ownLineup(),my=S.roster[$('#myTeam').value];if(!my)return;
  const selected=$('#dueBatter').value;
  if(c) {
    const fromLineup=dueFromLineup;
    $('#dueBatter').innerHTML=c.slots.map((s,i)=>`<option value="${esc(s.name)}">第 ${i+1} 棒 · ${esc(s.name)}</option>`).join('');
    dueFromLineup=true;
    // 預設情境是比賽開始（1 局上、0 出局），輪到第 1 棒；使用者已在名單選項中選過時保留
    $('#dueBatter').value=fromLineup&&c.slots.some(s=>s.name===selected)?selected:c.slots[0].name;
    // 換了場上投手時一併更新先發／後援與預設球數，畫面與送出的評估條件才會一致。
    if($('#myPitcher').value!==c.pitcher){$('#myPitcher').value=c.pitcher;syncRole();}
    $('#duePos').value=c.slots.find(s=>s.name===$('#dueBatter').value).pos;
  }
  $('#duePos').disabled=!!c;$('#myPitcher').disabled=!!c;
  $('#lineupSummary').innerHTML=`<span>${c?'已設定九棒 · 場上投手 '+esc(c.pitcher):'場上名單未設定；仍可直接評估。'}</span><button type="button" data-page="lineup">${c?'編輯配置':'設定名單'}</button>`;
  $('#lineupSummary button').onclick=()=>showFeaturePage('lineup');
  S.bench.forEach(n=>{if(!benchEligible(n))S.bench.delete(n);});
  groupControl?.refresh();
}
async function applyOwnLineup(name,change={}) {
  if($('#myTeam').value!==name){$('#myTeam').value=name;syncTeamChoices('myTeam');await refreshCustom();}
  else {
    const c=ownLineup();
    if(!c){$('#dueBatter').innerHTML=S.roster[name].hitters.map(h=>`<option value="${esc(h.name)}">${esc(h.name)}</option>`).join('');dueFromLineup=false;}
    syncOwnLineup();autoPos();renderBench();
  }
  if(change.pitcherSelected)S.starter=S.roster[name].pitchers.find(p=>p.name===$('#myPitcher').value)?.role==='先發';
  if(change.resetPitchCount)$('#pitchCount').value=0;
  renderRole();invalidateCustom();clearResult();renderBench();renderPenVisibility();
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
  $("#penFilter").oninput = () => renderPenVisibility(true);
  $("#penToggleAll").onclick = () => {$("#penList").hidden=!$("#penList").hidden;renderPenVisibility();};
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
  $("#benchAll").onclick = () => { S.bench = new Set(S.roster[$("#myTeam").value].hitters.filter(h => h.name !== $("#dueBatter").value&&benchEligible(h.name)).map(h => h.name)); renderBench(); };
  $("#benchNone").onclick = () => { S.bench.clear(); renderBench(); };
  $("#penAll").onclick = () => { $$("#penList input").forEach((i) => i.checked = true); invalidateCustom();groupControl?.refresh(); };
  $("#penNone").onclick = () => { $$("#penList input").forEach((i) => i.checked = false); invalidateCustom();groupControl?.refresh(); };
  $("#evalBtn").onclick = evaluateCustom;
  ['#recentWeight', '#fatigueD2', '#fatigueD3'].forEach(id => $(id).oninput = savePrefSettings);
  $('#presetSave').onclick = saveSituation;
  $('#presetLoad').onclick = () => applySituation(readPrefs().situation);
  $('#presetClear').onclick = clearSituation;
  $("#myPitcher").onchange = syncRole;
  $$("#roleSeg button").forEach((b) => b.onclick = () => { S.starter = b.dataset.r === "1"; renderRole(); });
  $("#pitchCount").oninput = renderRole;
  $("#rpTeam").onchange = loadGames;
  $("#onlyPhGames").onchange = renderGames;
  $("#lateOnly").onchange = renderPAs;
  $("#showSuggest").onchange = renderPAs;
  $("#onlyChanges").onchange = renderPAs;
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
  slideIn(m === "replay" ? $("#replayPanel") : $("#customPanel"), m === "replay" ? 1 : -1);
  if (m === "replay" && !S.games.length) loadGames();
  if (m === "replay") loadTiming().then(renderPAs);
}
function setView(v) {
  if(v===S.view)return;
  clearResult();
  S.view = v;
  $$("#viewSeg button").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  syncPressed();
  $("#offenseFields").classList.toggle("hidden", v !== "offense");
  $("#defenseFields").classList.toggle("hidden", v !== "defense");
  slideIn(v === "defense" ? $("#defenseFields") : $("#offenseFields"), v === "defense" ? 1 : -1);
}
function renderState() {
  $("#innVal").textContent = S.inning;
  $("#outsValue").textContent = S.outs + ' 出局';
  $$("#baseControls button").forEach(b => b.setAttribute("aria-pressed", String((S.bases & +b.dataset.b) > 0)));
  $$("#halfSeg button").forEach((b) => b.classList.toggle("on", b.dataset.half === S.half));
  $$("#outs button").forEach((b) => b.classList.toggle("on", +b.dataset.o <= S.outs));
  $$("#diamond .base").forEach((b) => b.classList.toggle("on", (S.bases & +b.dataset.b) > 0));
  $('#extraInningHint').classList.toggle('hidden',S.inning<10);
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
    // 對手接下來三棒預設取對手預設名單的第 1–3 棒；沒有預設名單時才用打席數排序。
    const top=(typeof LineupBoard!=='undefined'&&LineupBoard.defaultFor(oppName)?.slots.map(s=>s.name).filter(n=>opp.hitters.some(h=>h.name===n)))||[];
    ['#nb1','#nb2','#nb3'].forEach((id,i)=>{$(id).innerHTML=hOpt(opp.hitters);if(top.length>=3)$(id).value=top[i];else $(id).selectedIndex=i;});syncNextBatters();
  }
  if(myChanged) {
    $('#myPitcher').innerHTML=pOpt(my.pitchers);$('#dueBatter').innerHTML=hOpt(my.hitters);dueFromLineup=false;
    $('#dueBatter').selectedIndex=Math.min(8,my.hitters.length-1);autoPos();$('#benchFilter').value='';renderBench(true);syncRole();
    $('#penFilter').value='';$('#penList').hidden=true;
    $('#penList').innerHTML=my.pitchers.map(p=>`<label><input type="checkbox" value="${esc(p.name)}" ${p.role==='後援'?'checked':''}>${esc(p.name)}${STREAK_SELECT(p.name)}<span class="meta">${handChip(p.hand)}<span class="chip">${p.role}</span></span></label>`).join('');
    $('#myStreak').value='0';
    if(typeof PitcherGroups!=='undefined')groupControl=PitcherGroups.mount({element:$('#pitcherGroups'),list:$('#penList'),availability:$('#penAvailability'),team:myName,pitchers:my.pitchers,current:()=>$('#myPitcher').value,changed:()=>invalidateCustom()});
  }
  syncOwnLineup();autoPos();renderBench();renderPenVisibility();
  loadedTeams={my:myName,opp:oppName};S.ready=true;$('#evalBtn').disabled=false;

}
function renderPenVisibility(searching=false) {
  const query=$('#penFilter').value.trim(),list=$('#penList');
  let count=0;
  $$('#penList label').forEach(label=>{const name=label.querySelector('input').value;label.hidden=!!query&&!matchesPlayerSearch(name,$('#myTeam').value,query);if(!label.hidden)count++;});
  if(searching&&query)list.hidden=false;
  const button=$('#penToggleAll');button.innerHTML=uiIcon(list.hidden?'expand':'collapse')+(list.hidden?'全部展開':'全部收起');button.setAttribute('aria-expanded',String(!list.hidden));
  button.disabled=!!query&&!count;
  $('#penSearchStatus').textContent=query&&!count?'沒有符合的投手；搜尋不會清除已選名單。':'';
  $('#penSearchStatus').classList.toggle('hidden',!query||!!count);
}
function autoPos() {
  const my = S.roster[$("#myTeam").value];
  const h = my.hitters.find((x) => x.name === $("#dueBatter").value);
  const top = ownLineup()?.slots.find(s=>s.name===h?.name)?.pos || (h && Object.keys(h.positions || {})[0]);
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
  control.innerHTML=uiIcon(all?'collapse':'expand')+(q?(all?'收起搜尋結果':'展開搜尋結果'):(all?'全部收起':'全部展開'));
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
function availabilityNames(names, action, open=false) {
  const chips=items=>items.map(name=>`<span class="chip">${esc(name)}</span>`).join('');
  if(!names.length)return `<span>未勾選候選，僅比較${action}</span>`;
  return chips(names.slice(0,4))+(names.length>4?`<details class="availability-more" ${open?'open':''}><summary>另 ${names.length-4} 人</summary><div class="availability-extra">${chips(names.slice(4))}</div></details>`:'');
}
function mobileRowDetails(x, pen) {
  return `<details class="mobile-row-details"><summary>樣本與數據</summary><p>${Math.round(x['樣本球數'])} 球${!pen?' · '+esc(x['可信度'])+'樣本':''}</p>${!pen&&Number.isFinite(x['預估勝率'])?`<p>相對聯盟平均 ${sign(x['預估勝率'])} 百分點</p>`:''}${pen?`<p>失分價值 ${x['預估失分'].toFixed(3)} 分${x['疲勞調整']>.0005?'（含疲勞 +'+x['疲勞調整'].toFixed(3)+'）':''}</p>`:''}</details>`;
}
function renderBench(reset) {
  const my = S.roster[$("#myTeam").value];
  const due = $("#dueBatter").value;
  const duePos = $("#duePos").value;
  const q = $("#benchFilter").value.trim();
  const list = my.hitters.filter((h) => h.name !== due && benchEligible(h.name));
  // 預設勾選：出賽較少的球員（較可能在板凳）
  const regulars = new Set(my.hitters.slice(0, 9).map((h) => h.name));
  if (reset === true) S.bench = new Set(list.filter(h => !regulars.has(h.name)).map(h => h.name));
  S.bench.delete(due);
  const pickedToday=list.filter(h=>S.bench.has(h.name));
  $('#benchAvailability').innerHTML=`<div class="today-availability-head"><strong>今日勾選 ${pickedToday.length} 人</strong><span>名單需確認；排除未登錄與已退場者</span></div><div class="today-availability-names">${availabilityNames(pickedToday.map(h=>h.name),'續打',$('#benchAvailability').querySelector?.('.availability-more')?.open)}</div>`;
  const shown = list.filter((h) => matchesPlayerSearch(h.name,$('#myTeam').value,q));
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
    return `<section class="bench-group"><div class="bench-group-h"><button type="button" class="bench-expand" data-expand="${g.index}" aria-expanded="${!!(open.has(g.index))}" aria-controls="bench-group-${g.index}" ${!g.all.length?'disabled':''}><span class="bench-group-name">${g.label}</span><span class="mut bench-group-count">${picked}/${g.all.length}${q?' · 符合 '+g.players.length+' 人':''}</span><span aria-hidden="true" class="chevron">⌄</span></button><button type="button" class="link" data-group="${names}" aria-label="${esc(g.label)}：${allPicked?'清除選取':'全選'}${q?'符合者':''}" ${!g.players.length?'disabled':''}>${q?(allPicked?'取消符合者':'選取符合者'):(allPicked?'清除選取':'全選')}</button></div><div id="bench-group-${g.index}" ${open.has(g.index)?'':'hidden'}>${rows}</div></section>`;
  }).join('');
  $('#benchAll').innerHTML=uiIcon('check')+'全選';$('#benchNone').innerHTML=uiIcon('clear')+'清除選取';

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
      showFieldError(id,id==='pitchCount'?'工具接受 0–160 球的整數；160 並非規則上限。':(id==='myScore'?'我方':'對手')+'得分須為非負整數。');return;
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
    const bench = [...S.bench].filter(n => n !== $("#dueBatter").value && benchEligible(n));
    body = { inning: S.inning, half: S.half, outs: S.outs, bases: S.bases, bat_score: myScore, fld_score: oppScore,
      pitcher: $("#oppPitcher").value, due: $("#dueBatter").value, due_pos: $("#duePos").value, bench,
      bat_team: my, fld_team: opp, recent_weight: prefSettings().recent_weight };
  } else {
    const nb = ["#nb1", "#nb2", "#nb3"].map((s) => $(s).value);
    if(new Set(nb).size!==3){const duplicated=nb.find(n=>nb.filter(x=>x===n).length>1);['nb1','nb2','nb3'].filter((id,i)=>nb[i]===duplicated).reverse().forEach(id=>showFieldError(id,'接下來三棒須為不同打者。'));return;}
    body = { inning: S.inning, half: S.half, outs: S.outs, bases: S.bases, bat_score: oppScore, fld_score: myScore,
      pitcher: $("#myPitcher").value, due: nb[0], due_pos: "DH", bench: [], bat_team: opp, fld_team: my,
      next_batters: nb, pen: $$("#penList input:checked").map((i) => i.value).filter(name=>name!==$("#myPitcher").value),
      pitch_count: +$("#pitchCount").value || 0, starter: S.starter, ...prefSettings(), streaks: streakMarks() };
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
    $('.mobile-jump a[href="#result"]').hidden = false;
    if (motion()?.openDrawer()) { /* 窄螢幕：結果抽屜 */ }
    else if (window.matchMedia("(max-width: 1000px)").matches) $("#result").scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
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

/* ---------------- 換人時機比對（src/timing_backtest.py 離線模擬產生） ---------------- */
let timingData = null;
async function loadTiming() {
  if (timingData === null) {
    try { const d = await json('data/timing-2025.json'); timingData = d.season === 2025 && d.games ? d : false; }
    catch { timingData = false; }  // 沒有時機資料時，回放照常使用
  }
  return timingData;
}
function timingFor(paId) {
  const t = timingData && paId && timingData.games[paId.split('-').slice(0, 2).join('-')]?.[paId];
  if (!t) return null;
  const T = timingData.threshold;
  return {penGain:t[0], penBest:t[1], inc:t[2], phGain:t[3], phBest:t[4], due:t[5], phHasBench:!!t[6],
    penSug:t[0] != null && t[0] >= T, phSug:t[3] != null && t[3] >= T};
}
/* 白話結論：x 為全聯盟 summary；higherIsWorse：換投看失分（越高越差）、代打看得分（越低越差） */
function timingVerdict(x, higherIsWorse) {
  if (!x.stay_diff_ci) return {ok:false, text:'樣本不足，還無法判斷。'};
  const [lo, hi] = x.stay_diff_ci, ok = higherIsWorse ? lo > 0 : hi < 0, opposite = higherIsWorse ? hi < 0 : lo > 0;
  if (ok) return {ok:true, text:higherIsWorse ? '系統建議換投、但教練讓投手續投時，這些打席確實比較容易失分，系統挑出的換投時機有參考價值。' : '系統建議代打、但原打者上場時，這些打席確實比較難得分，系統挑出的代打時機有參考價值。'};
  if (opposite) return {ok:false, text:'結果與系統判斷相反，這類建議請謹慎參考。'};
  return {ok:false, text:higherIsWorse ? '系統建議換投與否，續投投手的表現沒有明顯差別，換投時機建議僅供參考。' : '系統建議代打與否，原打者的表現沒有明顯差別，代打時機建議僅供參考。'};
}
const HALF_ZH = h => h === "away" ? "上" : "下";
function divergentList(items, kind) {
  if (!items?.length) return '<p class="mut">沒有系統建議換人、但實際沒換的打席。</p>';
  return `<ol class="divergent-list">${items.map(x => {
    const score = kind === "pen" ? `${x.fld_score}:${x.bat_score}` : `${x.bat_score}:${x.fld_score}`;
    return `<li><button type="button" data-review-pa="${esc(x.pa)}" data-review-kind="${kind}">
      <span class="dv-when num">${esc(x.date.slice(5))}・${x.inning} 局${HALF_ZH(x.half)}</span>
      <span class="dv-who">${kind === "pen" ? `<b>${esc(x.who)}</b> 續投 → 建議換上 <b>${esc(x.best)}</b>` : `<b>${esc(x.who)}</b> 打擊 → 建議 <b>${esc(x.best)}</b> 代打`}</span>
      <span class="dv-ctx mut">對 ${esc(x.opp)}・${x.outs} 出局${x.bases ? `・${BASES[x.bases]}` : ""}・我方 ${score}・結果 ${esc(resultLabel(x.result))}</span>
      <span class="dv-gain num pos">${sign(x.gain)} 百分點</span><span class="dv-go" aria-hidden="true">→</span></button></li>`;
  }).join("")}</ol>`;
}
function renderReview() {
  const box = $('#reviewBody'), team = $('#reviewTeam').value, d = timingData && timingData.by_team[team];
  if (timingData === false) { box.innerHTML = '<p class="mut">換人時機資料無法載入。</p>'; return; }
  if (!d) { box.innerHTML = '<p class="mut">載入中…</p>'; return; }
  const T = timingData.threshold, key = Object.keys(timingData.summary).find(k => +k === T), all = timingData.summary[key];
  const pen = d.pen, ph = d.ph, pt = d.pen_timing, vp = timingVerdict(all.pen, true), vh = timingVerdict(all.ph, false);
  const stat = (v, label) => `<div class="review-stat"><strong class="num">${v}</strong><span>${label}</span></div>`;
  const re = x => `系統建議但沒換時，平均得分期望變化（RE24）${sign(x.stay_re24_suggested)}（${x.stay_n_suggested} 個打席）；系統不建議時 ${sign(x.stay_re24_not)}（${x.stay_n_not} 個打席）。差 ${sign(x.stay_diff)}，95% 區間 ${sign(x.stay_diff_ci[0])} ～ ${sign(x.stay_diff_ci[1])}。`;
  box.innerHTML = `
    <section class="card review-card" aria-labelledby="reviewPenTitle"><div class="card-h"><h3 id="reviewPenTitle">換投（${esc(team)} 防守）</h3></div><div class="card-b">
      <div class="review-stats">${stat(pen.actual, "實際換投")}${stat(pen.suggested, "系統建議")}${stat(pen.both, "同一打席都換")}${stat(pt.earlier_median != null ? `${pt.earlier_median} 個打席` : "—", "系統建議的中位數提早")}</div>
      <p class="review-note">實際換投 ${pt.changes} 次中，系統在同一打席就建議 ${pt.same} 次、更早建議 ${pt.earlier} 次，整段登板都沒建議 ${pt.system_never} 次。</p>
      <p class="review-verdict ${vp.ok ? "ok" : ""}">${vp.ok ? "✓" : "＝"} ${vp.text}</p>
      <h4>分歧最大的打席：系統建議換投、教練讓投手續投</h4>${STATIC ? '<p class="mut">線上版只收錄有代打的打席完整評估；點選後可看到該場打席列表，完整換投評估請用本機版。</p>' : ''}${divergentList(d.divergent?.pen, "pen")}
    </div></section>
    <section class="card review-card" aria-labelledby="reviewPhTitle"><div class="card-h"><h3 id="reviewPhTitle">代打（${esc(team)} 進攻）</h3></div><div class="card-b">
      <div class="review-stats">${stat(ph.actual, "實際代打")}${stat(ph.suggested, "系統建議")}${stat(ph.both, "同一打席都換")}</div>
      <p class="review-verdict ${vh.ok ? "ok" : ""}">${vh.ok ? "✓" : "＝"} ${vh.text}</p>
      <h4>分歧最大的打席：系統建議代打、教練讓原打者上場</h4>${divergentList(d.divergent?.ph, "ph")}
    </div></section>
    <details class="card review-method"><summary>方法與數據</summary><div class="card-b">
      <p>每個打席開始前，用比賽當天以前的資料，以與「歷史回放」相同的模型比較「換人」與「不換」；最佳候選好 ${T} 百分點以上視為系統建議。換下後板凳無人能接守的代打不列入。</p>
      <p>換投驗證（全聯盟）：${all.pen.stay_diff_ci ? re(all.pen) : "樣本不足。"}</p>
      <p>代打驗證（全聯盟）：${all.ph.stay_diff_ci ? re(all.ph) : "樣本不足。"}</p>
      <p class="mut">${esc(timingData.limits)}</p>
    </div></details>`;
  box.querySelectorAll("[data-review-pa]").forEach(b => b.onclick = () => openReplayPA(b.dataset.reviewPa, b.dataset.reviewKind));
}
/* 從賽季回顧跳到歷史回放的那個打席 */
async function openReplayPA(pa, kind) {
  const gid = pa.split("-").slice(0, 2).join("-");
  const item = Object.values(timingData.by_team).flatMap(t => [...(t.divergent?.pen || []), ...(t.divergent?.ph || [])]).find(x => x.pa === pa);
  await showFeaturePage("evaluation");
  setMode("replay");
  $("#rpTeam").value = $("#reviewTeam").value;
  await loadGames();
  if (!S.games.find(g => g.game === gid)?.ph && $("#onlyPhGames").checked) { $("#onlyPhGames").checked = false; renderGames(); }
  await loadGame(gid);
  const note = $("#replayNote");
  if (!S.pas) { note.textContent = "線上版沒有收錄這場比賽的打席資料；請用本機版查看。"; note.hidden = false; return; }
  if (item && item.inning < 7) $("#lateOnly").checked = false;
  $("#onlyChanges").checked = false; $("#showSuggest").checked = true;
  S.tab = kind === "pen" ? "pen" : "ph";
  renderPAs();
  const btn = $(`#paList [data-p="${pa}"]`);
  if (!btn) return;
  btn.scrollIntoView({block: "center"});
  if (btn.disabled) { note.textContent = "線上版只收錄有代打的打席完整評估；這個打席請用本機版查看。"; note.hidden = false; btn.classList.add("on"); return; }
  note.hidden = true;
  btn.click();
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
  $("#replayNote").hidden = true;
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
  if (motion()?.narrow()) $("#paList").closest(".card").scrollIntoView({behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start"});
}
function renderPAs() {
  if (!S.pas) return;
  const late = $("#lateOnly").checked, showSuggest = $("#showSuggest").checked, onlyChanges = $("#onlyChanges").checked;
  let html = "", lastKey = "";
  // 實際換投：與同一防守隊上一打席的投手不同（第一個打席除外）
  const lastPitcher = {}, penChanged = new Set();
  for (const p of S.pas) {
    if (lastPitcher[p.fld_team] && lastPitcher[p.fld_team] !== p.pitcher) penChanged.add(p.pa_id);
    lastPitcher[p.fld_team] = p.pitcher;
  }
  const visible = p => {
    if (late && p.inning < 7) return false;
    if (!onlyChanges) return true;
    const tm = timingFor(p.pa_id);
    return p.is_ph || penChanged.has(p.pa_id) || (showSuggest && (tm?.penSug || tm?.phSug));
  };
  for (const p of S.pas.filter(visible)) {
    const tm = showSuggest ? timingFor(p.pa_id) : null;
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
      ${penChanged.has(p.pa_id) ? `<span class="chip tag-ph">換投</span>` : ""}
      ${tm?.penSug ? `<span class="chip tag-sys" title="系統建議換上 ${esc(tm.penBest)}（${sign(tm.penGain)} 百分點）">系統：換投</span>` : ""}
      ${tm?.phSug ? `<span class="chip tag-sys" title="系統建議 ${esc(tm.phBest)} 代打（${sign(tm.phGain)} 百分點）">系統：代打</span>` : ""}
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
function activeResultTab() { return S.tab || (S.last?.view === "defense" ? "pen" : "ph"); }
function switchTab(t) {
  if (activeResultTab() === t) return;
  S.tab = t;
  renderResult(true);
  slideIn($("#evaluationSection"), t === "pen" ? 1 : -1);
}
/* 手機左右滑動：結果抽屜中切換代打／換投分頁或向右滑關閉；其餘切換評估與名單頁。 */
function handleSwipe(dir, target) {
  const M = motion();
  if (!M) return;
  if (M.drawerOpen()) {
    if (target.closest("#evaluationSection") && $$(".tabs button").length) {
      const want = dir === "left" ? "pen" : "ph";
      if (want !== activeResultTab()) { switchTab(want); return; }
    }
    if (dir === "right") M.closeDrawer();
    return;
  }
  if ($("#lineupPicker")?.open) return;
  // 左滑到下一個功能頁、右滑回上一個（評估 → 名單 → 賽季回顧）
  const i = PAGES.indexOf(currentPage()), next = PAGES[i + (dir === "left" ? 1 : -1)];
  if (next) showFeaturePage(next);
}
function bindMotion() {
  const M = motion();
  if (!M) return;
  M.setupDrawer({element: $("#result"), onClose: () => {
    const back = S.mode === "replay" && S.pa ? $(`#paList [data-p="${S.pa}"]`) : $("#evalBtn");
    back?.focus({preventScroll: true});
  }});
  M.onSwipe(handleSwipe);
  // 「查看結果」：有結果時開抽屜；「返回情境設定」：抽屜開著時關閉
  $('.mobile-jump a[href="#result"]').addEventListener("click", e => { if (S.last && M.openDrawer()) e.preventDefault(); });
  $(".result-return").addEventListener("click", e => { if (M.drawerOpen()) { e.preventDefault(); M.closeDrawer(); } });
}
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
  if(names.has(name)===checked)return true;
  let removed=null;
  if(checked&&names.size>=COMPARISON_LIMIT){removed=names.values().next().value;names.delete(removed);}
  checked?names.add(name):names.delete(name);
  let notices=comparisonNotices.get(R);if(!notices){notices=new Map();comparisonNotices.set(R,notices);}
  notices.set(tab,{target:name,message:removed?`已加入 ${name}，移除最早選取的 ${removed}。`:checked?`已加入 ${name}。`:`已移除 ${name}。`});return true;
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
  const notice=comparisonNotices.get(R)?.get(tab);
  $$('[data-table-compare]').forEach(i=>{
    i.checked=comparisonNames(R,tab).has(i.value);
    const cell=i.closest('td');cell?.querySelector('.comparison-row-notice')?.remove();
    if(notice?.target===i.value)cell?.insertAdjacentHTML('beforeend',`<span class="comparison-row-notice" role="status">${esc(notice.message)}</span>`);
  });
}
function bindTableComparison(R,tab) {
  $$('[data-table-compare]').forEach(input=>input.onchange=()=>{
    setComparisonName(R,tab,input.value,input.checked);
    $('#candidateCompare').innerHTML=comparisonPanel(R,null,tab);bindComparison(R,tab);syncComparisonChoices(R,tab);
    if(input.checked){const tr=input.closest('tr');showDetail(tab==='pen'?R.bullpen.next[0]:input.value,tab==='pen'?input.value:R.situation.pitcher,tr);}
  });
}
function valueComparisonChart(data, sharedScale, title, higherBetter, note) {
  const compared=data.map(d=>({...d,delta:Number.isFinite(d.value)&&Number.isFinite(d.base)?(higherBetter?d.value-d.base:d.base-d.value):null}));
  const scale=Math.max(.001,sharedScale||0,...compared.map(d=>d.delta).filter(Number.isFinite).map(Math.abs));
  return `<div class="next-matchup-chart benefit-chart"><p class="mut">${title}</p><div class="comparison-direction"><span class="neg">← 較不利</span><span>現任 0</span><span class="pos">較有利 →</span></div>${compared.map(d=>{
    if(d.delta===null)return `<div class="next-matchup-row"><span>${esc(d.name)}</span><span class="component-missing mut">${Number.isFinite(d.value)?'現任資料不足':'資料不足'}</span></div>`;
    const width=Number((Math.abs(d.delta)/scale*48).toFixed(6)),tone=d.delta>0?'favorable':d.delta<0?'unfavorable':'neutral';
    const label=d.delta===0?'相同':Math.abs(d.delta)<.0005?'差距極小':d.delta>0?'較有利':'較不利';
    return `<div class="next-matchup-row"><span>${esc(d.name)}</span><div class="next-matchup-track" aria-hidden="true"><i class="${tone}" style="left:${d.delta>=0?50:50-width}%;width:${width}%"></i></div><span class="num"><strong class="${tone}">${sign(d.delta,3)}</strong><small>${label}</small></span></div>`;
  }).join('')}<small class="mut">候選共用尺度。${note}</small><details class="chart-raw"><summary>原始數值</summary>${data.map(d=>`<p class="num">${esc(d.name)}：候選 ${Number.isFinite(d.value)?sign(d.value,3):'未提供'}／現任 ${Number.isFinite(d.base)?sign(d.base,3):'未提供'}</p>`).join('')}</details></div>`;
}
function pitcherMatchupChart(details, sharedScale, currentDetails = []) {
  const baseline=new Map();
  for(const d of currentDetails||[]) {
    const value=d.runs+d.fatigue;
    if(Number.isFinite(value))baseline.set(d.batter,baseline.has(d.batter)?null:value);
  }
  const data=(details||[]).map(d=>({name:d.batter,value:d.runs+d.fatigue,base:baseline.get(d.batter)})).filter(d=>Number.isFinite(d.value));
  if(!data.length)return '';
  return valueComparisonChart(data,Math.max(.01,sharedScale||0),'相對現任減少失分 · 分',false,'含疲勞，非實際失分。');
}
function hitterComponentChart(candidate, current, rows) {
  const fields=[['本身能力','本身能力'],['球路適性','球路適性'],['左右投打','左右優勢']];
  const scale=Math.max(.001,...rows.flatMap(r=>fields.map(([,key])=>Number.isFinite(r[key])&&Number.isFinite(current[key])?r[key]-current[key]:null)).filter(Number.isFinite).map(Math.abs));
  const data=fields.map(([name,key])=>({name,value:candidate[key],base:current[key]}));
  return `<div class="compare-values"><div class="hitter-component-chart">${valueComparisonChart(data,scale,'相對現任得分優勢 · 分／打席',true,'僅拆解階層式估計。')}</div></div>`;
}
function compactFielding(text) {
  return String(text||'').replace(/^需由 (.+?) 接守(.+?)（再消耗 1 名板凳）/,'接守：$1 · $2（另需 1 人）').replace(/^換下後板凳無人可守/,'無人接守').replace(/^.+? 可直接接守/,'可接守');
}
function fieldingMessage(x, current=false) {
  const text=x['守備說明']||'守位資料待確認';
  if(current)return esc(text);
  const dh=text.includes('接任指定打擊');
  const label=dh?'承接原 DH 棒次':x['守備']==='bad'?'無人接守':text.startsWith('需由 ')?'另需接守人選':text.includes('可直接接守')?'推估可接守':'守位待確認';
  return `<strong class="fielding-label">${label}</strong><span>${esc(compactFielding(text))}</span>${dh?'<span class="mut">改守備或涉及投手打擊時，請確認 DH 存續。</span>':''}`;
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
    const status = low ? '資料有限' : disagreement ? '模型分歧' : Math.abs(delta) < 0.005 ? '難以區分' : '';
    const reason = pen
      ? (x['疲勞'] && x['疲勞'] !== '-' ? `<p class="compare-warning">${esc(x['疲勞'])}</p>` : '')
      : `<p class="${x['守備']==='bad'||x['守備']==='warn'?'compare-warning':'mut'}">${fieldingMessage(x)}</p>`;
    const decomposition=pen?'':hitterComponentChart(x,current,rows);
    const matchupScale=Math.max(.01,...rows.flatMap(r=>(r['對決明細']||[]).map(d=>{const bases=(current['對決明細']||[]).filter(b=>b.batter===d.batter);return bases.length===1?Math.abs((d.runs+d.fatigue)-(bases[0].runs+bases[0].fatigue)):NaN;})).filter(Number.isFinite));
    const matchupChart = pen ? pitcherMatchupChart(x['對決明細'],matchupScale,current['對決明細']) : '';
    return `<article class="compare-card"><h3>${esc(x[nameKey])}${status?`<span class="chip">${status}</span>`:''}</h3>
      <p class="compare-delta num ${cls(delta,.005)}">相對現任 ${sign(delta)} 百分點</p>${reason}
      <details><summary>查看差距拆解</summary>${matchupChart}${decomposition}
      <p class="comparison-samples mut">樣本：候選 ${Math.round(x['樣本球數'])}／現任 ${Math.round(current['樣本球數'])} 球</p>
      ${x['資料警示']||current['資料警示']?`<p class="compare-warning">${esc([x['資料警示'],current['資料警示']].filter(Boolean).join('；'))}</p>`:''}</details></article>`;
  };
  return `<div class="card comparison"><div class="card-h"><h2>現任與候選比較</h2><span class="hint">基準：${esc(current[nameKey])}</span><a class="comparison-back" href="#evaluationSection">返回選人 ↑</a></div><div class="card-b">
    <p class="mut">${pen ? `對上接下來 ${R.bullpen.next.length} 棒。` : '同一投手、同一局勢。'}</p>
    <p class="compare-limit mut" role="status">已選 ${choices.length}/${COMPARISON_LIMIT}${comparisonNotices.get(R)?.get(tab)?.message?` · ${esc(comparisonNotices.get(R).get(tab).message)}`:''}</p>
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
  if (diff <= 0) { const why = reasonText(batterReasons(cur, S.last)); return { kind: "neutral", title: `目前估計以 ${cur["球員"]} 續打較佳`, text: `${why ? `${cur["球員"]}：${why}。` : ''}可用候選沒有更高的估計值；這不是續打必然較好的保證。` }; }
  const def = best["守備"] === "warn" ? `　${best["守備說明"]}` : "";
  const disagree = best["機器學習"] != null && cur["機器學習"] != null &&
    (best["階層式"] - cur["階層式"]) * (best["機器學習"] - cur["機器學習"]) <= 0;
  const low = best["樣本球數"] < 500 || cur["樣本球數"] < 500 || !!best['資料警示'] || !!cur['資料警示'];
  const why = reasonText(batterReasons(best, S.last));
  return {kind:best["守備"] === "warn" ? "warn" : "neutral", best:best["球員"],
    title:disagree ? "兩模型分歧" : low ? "候選資料有限，需審慎判斷" : `估計較佳人選：${best["球員"]}`,
    text:`${why ? `主要原因：${why}。` : ''}比 ${cur["球員"]} ${sign(diff)} 百分點。${disagree ? "估計有分歧，請審慎判斷。" : "差值僅供參考，仍須確認上場狀況。"}${def}`};
}

function assessmentNotes(R) {
  const cutoff=R.model_cutoff||'未記錄';
  const ml=R.ml_cutoff||(R.method==='階層式'?'未使用':'未記錄');
  const dates=cutoff!=='未記錄'&&ml===cutoff?`資料截止：${esc(cutoff)}`:`能力資料截止：${esc(cutoff)}；逐球資料截止：${esc(ml)}`;
  return `<p>分數是相對排名，不是成功機率。換人前請確認今日名單與守備安排。</p>
    <details class="assessment-notes"><summary>資料與評估依據</summary><ul>
    <li><b>評估方式：</b>依投打能力、球路適性與左右投打比較；換投另考慮用球數疲勞。</li>
    <li><b>資料範圍：</b>2024–2025 球季；${dates}（不含截止日）。來源：Rebas、ldkrsi／CPBL 守位統計。</li>
    <li><b>圖表限制：</b>優勢來源僅拆解部分模型；細線不是完整預測區間，失分價值不是實際失分。</li>
    <li><b>使用限制：</b>${R.view==='replay'?'歷史名單與守位可能為推估；':'今日名單需人工確認；'}未追蹤完整登錄、退場與 DH 狀態，請核對正式攻守名單。</li>
    </ul></details>`;
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
        <p>${reasonText(pitcherReasons(best, R)) ? `主要原因：${esc(reasonText(pitcherReasons(best, R)))}。` : ''}對上接下來 ${R.bullpen.next.length} 棒，相對場上投手的守方勝率換算差值 ${sign(best["守方勝率增減"])} 百分點。請確認今日可用狀態。${fat}${best["疲勞"] !== "-" ? `　警示 ${esc(best["投手"])}：${esc(best["疲勞"])}` : ""}</p></div></div>`;
    } else {
      html += `<div class="reco neutral" style="border-top:1px solid var(--line)"><div class="ic">=</div><div><h3>${best ? `目前估計以 ${esc(s.pitcher)} 續投較佳` : "沒有勾選可用牛棚"}</h3><p>${curP && reasonText(pitcherReasons(curP, R)) ? `${esc(s.pitcher)}：${esc(reasonText(pitcherReasons(curP, R)))}。` : ''}${best ? "候選沒有較低的估計失分；不代表已證明續投最佳。" : "目前只能顯示場上投手；請確認是否有可用後援。"}${fat}</p></div></div>`;
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
    const tm = timingFor(S.pa);
    if (tm) {
      const changed = tm.inc !== s.pitcher;
      html += `<div class="actual timing-note"><span class="mut">時機比對：</span>
        ${tm.penGain != null ? `<span>換投（${esc(tm.inc)} 續投 vs 牛棚）系統${tm.penSug ? `建議換上 <b>${esc(tm.penBest)}</b>（${sign(tm.penGain)} 百分點）` : '未建議'}・實際${changed ? `換上 <b>${esc(s.pitcher)}</b>` : '續投'}</span>` : ''}
        ${tm.phGain != null ? `<span>代打 系統${tm.phSug ? `建議 <b>${esc(tm.phBest)}</b>（${sign(tm.phGain)} 百分點）` : '未建議'}・實際${a.is_ph ? '代打' : '未代打'}</span>`
          : tm.phHasBench ? `<span>代打 系統未建議（板凳換下後守備排不出來）・實際${a.is_ph ? '代打' : '未代打'}</span>` : ''}</div>`;
    }
  }
  html += `</div>`;


  // 主表 + 側欄

  const showTabs = view === "replay";
  const tab = S.tab || (view === "defense" ? "pen" : "ph");
  html += `<div class="card evaluation-card" id="evaluationSection" tabindex="-1">`;
  if (showTabs) html += `<div class="tabs"><button data-t="ph" class="${tab === "ph" ? "on" : ""}">代打評估（進攻方）</button><button data-t="pen" class="${tab === "pen" ? "on" : ""}">換投評估（防守方）</button></div>`;
  else html += `<div class="card-h"><h2>${view === "defense" ? "換投評估" : "代打評估"}</h2><span class="hint">${view === "defense" ? "" : ""}</span></div>`;
  html += `<p class="eligibility-note">${R.view==='replay'?'名單與守位為歷史推估':'勾選名單尚需確認登錄與退場狀態'}；評估結果不代表換人資格已驗證。</p>`;
  html += `<nav class="evaluation-nav" aria-label="評估結果導航"><a class="link" href="#candidateCompare">${uiIcon("compare")}比較已選球員 ↓</a><span class="mut">最多 4 人</span></nav><div class="tbl-wrap" tabindex="0" role="region" aria-label="球員評估表，可左右捲動">${(showTabs ? tab : view === "defense" ? "pen" : "ph") === "pen" ? penTable(R) : phTable(R)}</div></div>`;
  html += `<div id="candidateCompare" tabindex="-1">${comparisonPanel(R,null,activeTab)}</div><div id="pitchArsenal">${mixCard(R)}</div>`;
  html += `<div class="detail-grid"><div id="pitchChange"></div><div id="detail"></div></div>`;
  html += `<div id="detailStatus" class="sr-only" role="status"></div><div class="foot">${assessmentNotes(R)}<details class="rules-note"><summary>換人規則提醒</summary><ul><li>已退場球員不可再上場；名單須排除已退場與未登錄者。</li><li>代打承接原棒次；替換指定打擊時須確認 DH 資格。</li><li>新任投手、換局時已上丘投手須符合最低投球義務及例外規定；接下來三棒是評估範圍，不是換投規則。</li><li>2024–2025 一軍例行賽延長局最多 12 局；突破僵局的二壘預設可按實際局面修改。</li></ul><p>本站未追蹤完整換人紀錄、DH 存續及登錄資格，不能取代裁判或正式攻守名單。</p><a href="https://www.cpbl.com.tw/files/file_pool/1/0p065549820043528193/2025%E6%A3%92%E7%90%83%E8%A6%8F%E5%89%87%28%E5%AE%98%E7%B6%B2%E7%94%A8%29.pdf" target="_blank" rel="noopener noreferrer">CPBL 官方棒球規則（2025）</a></details></div>`;
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
    b.onclick = () => switchTab(b.dataset.t);
  });
  $$("tr[data-batter]").forEach((tr) => tr.onclick = e => {if(e.target.closest('a,input,label,details'))return;showDetail(tr.dataset.batter, R.situation.pitcher, tr);});
  $$('tr[data-pitcher]').forEach(tr=>{
    const radio=tr.querySelector('[name="viewPitcher"]');
    const select=()=>showDetail(R.bullpen.next[0],tr.dataset.pitcher,tr);
    if(radio)radio.onchange=select;tr.onclick=e=>{if(e.target.closest('a,input,label,details'))return;select();};
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
function scoreLegend(cur, key) {
  const now = cur && cur["價值分數"] != null ? `<span class="score-baseline">現任 ${esc(cur[key])} ${cur["價值分數"]} 分；是否比現任好，請看「勝率變化」</span>` : "";
  return SCORE_LEGEND.replace("</div>", now + "</div>");
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
  const scale = Math.max(0.3, ...c.map((x) => Math.abs(x["相對現任"]||0)));
  const rows = c.map((x) => {
    const cur = x["角色"] === "現任", best = x["球員"] === S.bestName;
    const d = x["守備"];
    return `<tr data-batter="${esc(x["球員"])}" class="${cur ? "cur" : ""} ${best ? "best-row" : ""}">
      <td class="ncell"><span class="role">${cur ? "現任" : "代打"}</span>${cur?`<button type="button" class="baseline-detail" aria-label="查看 ${esc(x["球員"])} 對決">基準</button>`:comparisonCircle(R,"ph",x["球員"])}${officialPlayerLink(x["球員"])} ${handChip(x["打擊"])}${best ? `<span class="best">估計較佳</span>` : ""}
        <div class="parts">${(x["可守"] || "-").split(",").map((p) => POS[p] || p).join("・")}</div>${reasonsHtml(batterReasons(x, R))}${mobileRowDetails(x,false)}</td>
      <td class="evaluation-score">${scoreBadge(x["價值分數"], `面對 ${R.situation.pitcher} 的比较池百分位；截止日之前達門檻的打者，早季回退前一季`)}</td>
      <td class="evaluation-value"><span class="mobile-value-label">相對現任</span><div class="vcell"><span class="vnum num ${cls(cur?0:x['相對現任'],.02)}">${cur?'基準':sign(x['相對現任'])+' 百分點'}</span>${dbar(cur?0:x['相對現任'],0,scale)}</div></td>
      <td class="evaluation-warning"><div class="def"><span class="d ${d}">${d === "ok" ? "✓" : d === "warn" ? "!" : "✕"}</span><span>${fieldingMessage(x,cur)}</span></div></td>
    </tr>`;
  }).join("");
  return `<div class="card-b" style="padding-bottom:0">${scoreLegend(c.find(x => x["角色"] === "現任"), "球員")}</div><table class="t evaluation-table"><thead><tr><th>球員</th><th title="比較池百分位；不是成功機率">價值分數</th><th>勝率變化（相對現任）</th><th>守備檢查</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function penTable(R) {
  const rows = R.bullpen.rows;
  const scale = Math.max(0.5, ...rows.map((x) => Math.abs(x["守方勝率增減"])));
  const body = rows.map((x, i) => {
    const cur = x["角色"] === "場上";
    const best = !cur && i === 1 && x["守方勝率增減"] > 0;
    return `<tr data-pitcher="${esc(x["投手"])}" class="${cur ? "cur" : ""}">
      <td class="ncell" title="樣本 ${x["樣本球數"]} 球"><span class="role">${cur ? "場上" : "牛棚"}</span>${cur?`<button type="button" class="baseline-detail" aria-label="查看 ${esc(x["投手"])} 配球與對決">基準</button>`:comparisonCircle(R,"pen",x["投手"])}${officialPlayerLink(x["投手"])} ${handChip(x["投"] || "R")}${best ? `<span class="best">估計較佳</span>` : ""}
        <div class="parts">${cur ? `本場已投 ${x["用球數"] ?? "—"} 球` : "未登板"}</div>${reasonsHtml(pitcherReasons(x, R))}${mobileRowDetails(x,true)}</td>
      <td class="evaluation-score">${scoreBadge(x["價值分數"], '對上後續打者的比較池百分位；截止日之前達門檻的後援，早季回退前一季')}</td>
      <td class="evaluation-value"><span class="mobile-value-label">${cur?'現任基準 · 0 百分點':'相對現任'}</span><div class="vcell"><span class="vnum num ${cls(x["守方勝率增減"], 0.02)}">${cur ? "基準" : sign(x["守方勝率增減"]) + " 百分點"}</span>${dbar(x["守方勝率增減"], 0, scale)}</div></td>
      <td class="evaluation-warning">${x["疲勞"] === "-" ? `<span class="mut">—</span>` : `<span class="chip c-中">${esc(x["疲勞"])}</span>`}</td></tr>`;
  }).join("");
  return `<div class="card-b mut" style="font-size:12px;padding-bottom:0">比較接下來 ${R.bullpen.next.length} 棒 · 未模擬換局與後續調度<br>打者：${R.bullpen.next.map(esc).join("、")}<div style="margin-top:6px">${scoreLegend(R.bullpen.rows.find(x => x["角色"] === "場上"), "投手")}</div></div>
    <table class="t evaluation-table"><caption class="sr-only">固定三打席比較，未模擬換局與後續調度。</caption><thead><tr><th>投手</th><th title="比較池百分位；不是成功機率">價值分數</th><th>勝率變化（相對現任）</th><th>疲勞／警示</th></tr></thead><tbody>${body}</tbody></table>`;
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
      <p class="detail-caption mut">配球：比例；揮空差值：百分點（相對自身平均）。</p>
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
