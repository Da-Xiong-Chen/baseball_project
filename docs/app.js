"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const POS = { C: "捕手", "1B": "一壘", "2B": "二壘", "3B": "三壘", SS: "游擊", LF: "左外野", CF: "中外野", RF: "右外野", DH: "指定打擊" };
const GROUPS = ["速球", "滑卡", "曲球", "低落"];
const GROUP_COLOR = { 速球: "#d9534f", 滑卡: "#e0a03a", 曲球: "#4a7fd0", 低落: "#3f9a6b" };
const BASES = { 0: "無人", 1: "一壘", 2: "二壘", 3: "一二壘", 4: "三壘", 5: "一三壘", 6: "二三壘", 7: "滿壘" };

const S = {
  mode: "custom", view: "offense", starter: false, inning: 7, half: "home", outs: 1, bases: 3,
  teams: [], roster: {}, games: [], game: null, pa: null, last: null, selected: null,
  bench: new Set(), ready: false,
};
let rosterGeneration = 0, gamesGeneration = 0, gameGeneration = 0, runGeneration = 0;
function clearResult() {
  ++runGeneration;
  ++detailGeneration;
  S.last = null;
  $("#resultBody").innerHTML = "";
  $("#resultBody").classList.add("hidden");
  $("#emptyState").classList.remove("hidden");
  $("#evalBtn").disabled = !S.ready;
  $("#evalBtn").textContent = "評估";
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
async function json(url) {
  if (!cache[url]) cache[url] = fetch(url, timeoutOptions(30000)).then((r) => { if (!r.ok) throw new Error(`${r.status} ${url}`); return r.json(); }).catch(e => { delete cache[url]; throw e; });
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
  const res = await fetch(path, {...timeoutOptions(120000), ...(body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {})});
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
  try {
    const r = await fetch("api/meta", timeoutOptions(30000));
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
  $$("#modeSeg button").forEach((b) => b.onclick = () => setMode(b.dataset.mode));
  $$("#viewSeg button").forEach((b) => b.onclick = () => setView(b.dataset.view));
  $$("#halfSeg button").forEach((b) => b.onclick = () => { S.half = b.dataset.half; renderState(); });
  $("#innUp").onclick = () => { S.inning = Math.min(12, S.inning + 1); renderState(); };
  $("#innDown").onclick = () => { S.inning = Math.max(1, S.inning - 1); renderState(); };
  $$("#outs button").forEach((b) => b.onclick = () => { const o = +b.dataset.o; S.outs = S.outs === o ? o - 1 : o; renderState(); });
  $$("#diamond .base").forEach((b) => b.onclick = () => { S.bases ^= +b.dataset.b; renderState(); });
  $$("#baseControls button").forEach(b => b.onclick = () => { S.bases ^= +b.dataset.b; renderState(); });
  $("#myTeam").onchange = refreshCustom;
  $("#oppTeam").onchange = refreshCustom;
  $("#dueBatter").onchange = () => { autoPos(); renderBench(); };
  $("#benchFilter").oninput = () => renderBench();
  $("#benchList").onchange = e => { if (e.target.matches('input')) { if (e.target.checked) S.bench.add(e.target.value); else S.bench.delete(e.target.value); } };
  $("#benchAll").onclick = () => { S.bench = new Set(S.roster[$("#myTeam").value].hitters.filter(h => h.name !== $("#dueBatter").value).map(h => h.name)); renderBench(); };
  $("#benchNone").onclick = () => { S.bench.clear(); renderBench(); };
  $("#penAll").onclick = () => { $$("#penList input").forEach((i) => i.checked = true); };
  $("#penNone").onclick = () => { $$("#penList input").forEach((i) => i.checked = false); };
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
  $$("#roleSeg button").forEach((b) => b.classList.toggle("on", (b.dataset.r === "1") === S.starter));
  syncPressed();
  const pc = +$("#pitchCount").value || 0;
  $("#pcHint").textContent = S.starter
    ? (pc >= 85 ? "先發超過 85 球：依 2024–2025 資料加入疲勞調整（球數越多，預估失分越高）" : "先發 85 球以前，資料上看不出明顯疲勞")
    : (pc >= 30 ? "後援超過 30 球：資料太少，只顯示警示、不調整數值" : "後援投手 30 球以內不調整");
}

function setMode(m) {
  clearResult();
  S.mode = m;
  $$("#modeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.mode === m));
  syncPressed();
  $("#customPanel").classList.toggle("hidden", m !== "custom");
  $("#replayPanel").classList.toggle("hidden", m !== "replay");
  if (m === "replay" && !S.games.length) loadGames();
}
function setView(v) {
  clearResult();
  S.view = v;
  $$("#viewSeg button").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  syncPressed();
  $("#offenseFields").classList.toggle("hidden", v !== "offense");
  $("#defenseFields").classList.toggle("hidden", v !== "defense");
}
function renderState() {
  $("#innVal").textContent = S.inning;
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
async function refreshCustom() {
  const token = ++rosterGeneration;
  S.ready = false;
  clearResult();
  $("#formError").innerHTML = '<span role="status">正在載入名單…</span>';
  const myName = $("#myTeam").value, oppName = $("#oppTeam").value;
  let my, opp;
  try {
    [my, opp] = await Promise.all([team(myName), team(oppName)]);
  } catch (e) {
    if (token === rosterGeneration) listError('#formError', '名單載入失敗：' + e.message, refreshCustom);
    return;
  }
  if (token !== rosterGeneration) return;
  $("#formError").innerHTML = '';
  const pOpt = (ps) => {
    const g = (role) => ps.filter((p) => p.role === role).map((p) => `<option value="${esc(p.name)}">${esc(p.name)}（${p.hand === "L" ? "左" : "右"}投・${p.games}場）</option>`).join("");
    return `<optgroup label="後援">${g("後援")}</optgroup><optgroup label="先發">${g("先發")}</optgroup>`;
  };
  $("#oppPitcher").innerHTML = pOpt(opp.pitchers);
  $("#myPitcher").innerHTML = pOpt(my.pitchers);
  const hOpt = (hs) => hs.map((h) => `<option value="${esc(h.name)}">${esc(h.name)}（${h.hand === "L" ? "左" : h.hand === "R" ? "右" : "兩"}打）</option>`).join("");
  $("#dueBatter").innerHTML = hOpt(my.hitters);
  ["#nb1", "#nb2", "#nb3"].forEach((s, i) => { $(s).innerHTML = hOpt(opp.hitters); $(s).selectedIndex = i; });
  // 預設：輪到第 9 位常用打者（較可能被代打）
  $("#dueBatter").selectedIndex = Math.min(8, my.hitters.length - 1);
  autoPos();
  $("#benchFilter").value = '';
  renderBench(true);
  syncRole();
  $("#penList").innerHTML = my.pitchers.map((p) => `
    <label><input type="checkbox" value="${esc(p.name)}" ${p.role === "後援" ? "checked" : ""}>
      ${esc(p.name)} <span class="meta">${handChip(p.hand)}<span class="chip">${p.role}</span><span class="chip">${p.games} 場</span></span></label>`).join("");
  S.ready = true;
  $("#evalBtn").disabled = false;
}
function autoPos() {
  const my = S.roster[$("#myTeam").value];
  const h = my.hitters.find((x) => x.name === $("#dueBatter").value);
  const top = h && Object.keys(h.positions || {})[0];
  $("#duePos").value = top || "DH";
}
function renderBench(reset) {
  const my = S.roster[$("#myTeam").value];
  const due = $("#dueBatter").value;
  const q = $("#benchFilter").value.trim();
  const list = my.hitters.filter((h) => h.name !== due);
  // 預設勾選：出賽較少的球員（較可能在板凳）
  const regulars = new Set(my.hitters.slice(0, 9).map((h) => h.name));
  if (reset === true) S.bench = new Set(list.filter(h => !regulars.has(h.name)).map(h => h.name));
  S.bench.delete(due);
  $("#benchList").innerHTML = list.filter((h) => !q || h.name.includes(q)).map((h) => {
    const on = S.bench.has(h.name);
    return `<label><input type="checkbox" value="${esc(h.name)}" ${on ? "checked" : ""}>
      ${esc(h.name)} <span class="meta">${handChip(h.hand)}${posChips(h.positions)}<span class="chip">${h.pa} 打席</span></span></label>`;
  }).join("") || '<p role="status">沒有符合的球員；搜尋不會清除已選名單。</p>';
}

async function evaluateCustom() {
  if (!S.ready) return;
  $("#formError").innerHTML = '';
  for (const id of ['myScore','oppScore', ...(S.view === 'defense' ? ['pitchCount'] : [])]) {
    const input = $('#' + id);
    if (input.value === '' || !input.checkValidity() || !Number.isInteger(Number(input.value))) {
      input.setAttribute('aria-invalid','true');
      $("#formError").innerHTML = '<p role="alert">請填寫非負整數；本場球數須介於 0 至 160。</p>';
      input.focus(); return;
    }
    input.removeAttribute('aria-invalid');
  }
  const my = $("#myTeam").value, opp = $("#oppTeam").value;
  if (my === opp) { $("#formError").innerHTML = '<p role="alert">我方與對手須為不同球隊。</p>'; return; }
  const myScore = +$("#myScore").value || 0, oppScore = +$("#oppScore").value || 0;
  let body;
  if (S.view === "offense") {
    const bench = [...S.bench].filter(n => n !== $("#dueBatter").value);
    body = { inning: S.inning, half: S.half, outs: S.outs, bases: S.bases, bat_score: myScore, fld_score: oppScore,
      pitcher: $("#oppPitcher").value, due: $("#dueBatter").value, due_pos: $("#duePos").value, bench,
      bat_team: my, fld_team: opp };
  } else {
    const nb = ["#nb1", "#nb2", "#nb3"].map((s) => $(s).value);
    if (new Set(nb).size !== 3) { $("#formError").innerHTML = '<p role="alert">接下來三棒須為三位不同打者。</p>'; return; }
    body = { inning: S.inning, half: S.half, outs: S.outs, bases: S.bases, bat_score: oppScore, fld_score: myScore,
      pitcher: $("#myPitcher").value, due: nb[0], due_pos: "DH", bench: [], bat_team: opp, fld_team: my,
      next_batters: nb, pen: $$("#penList input:checked").map((i) => i.value),
      pitch_count: +$("#pitchCount").value || 0, starter: S.starter };
  }
  await run(() => api("api/evaluate", body), S.view);
}

async function run(fn, view) {
  const token = ++runGeneration;
  const btn = $("#evalBtn");
  btn.disabled = true; btn.innerHTML = `<span class="loading"></span> 計算中…`;
  $("#emptyState").classList.add("hidden");
  const box = $("#resultBody");
  box.classList.remove("hidden");
  if (!S.last) box.innerHTML = `<div class="card empty" role="status"><span class="loading"></span> 正在比較對決。首次載入歷史模型可能較久，請稍候。</div>`;
  try {
    const result = await fn();
    if (token !== runGeneration) return;
    S.last = result;
    S.last.view = view;
    S.selected = null;
    renderResult();
    if (window.matchMedia("(max-width: 1000px)").matches) $("#result").scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    else window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (e) {
    if (token !== runGeneration) return;
    S.last = null;
    box.innerHTML = `<div class="err-box" role="alert">發生錯誤：${esc(e.message)}<button class="retry">重新評估</button></div>`;
    box.querySelector('.retry').onclick = () => run(fn, view);
  } finally {
    if (token === runGeneration) { btn.disabled = !S.ready; btn.textContent = "評估"; }
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
  } catch (e) { if (token === gamesGeneration) listError('#gameList', e.message, loadGames); return; }
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
  } catch (e) { if (token === gameGeneration) listError('#paList', e.message, () => loadGame(gid)); return; }
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
      <span class="mut" style="margin-left:auto;font-size:12px">${esc(p.result || "")}</span></button>`;
  }
  $("#paList").innerHTML = (STATIC ? `<div class="inning-h" style="position:static">網頁版收錄 2025 年所有實際換代打的情境（標示「代打」者可點選）</div>` : "") + (html || `<div class="empty" style="padding:24px">沒有打席</div>`);
  $$("#paList .item:not(.off)").forEach((el) => el.onclick = () => {
    S.pa = el.dataset.p;
    renderPAs();
    $(`#paList [data-p="${S.pa}"]`)?.focus();
    run(() => api(`api/replay?pa=${el.dataset.p}`), "replay");
  });
}

/* ---------------- 結果呈現 ---------------- */
function recommendation(cands) {
  const cur = cands.find((c) => c["角色"] === "現任");
  const bench = cands.filter((c) => c["角色"] === "代打");
  const playable = bench.filter((c) => c["守備"] !== "bad");
  if (!playable.length) return { kind: "neutral", title: `建議讓 ${cur["球員"]} 續打`, text: "板凳沒有可用且守備排得出來的人選。" };
  const best = playable[0];
  const diff = best["預估勝率"] - cur["預估勝率"];
  const err = Math.sqrt(best["誤差"] ** 2 + cur["誤差"] ** 2);
  if (diff <= 0) return { kind: "neutral", title: `建議讓 ${cur["球員"]} 續打`, text: `現任價值分數 ${cur["價值分數"]}；板凳中最佳人選 ${best["球員"]}（${best["價值分數"]}）預估不會比較好。` };
  const def = best["守備"] === "warn" ? `　⚠ ${best["守備說明"]}` : "";
  const sc = `價值分數 ${best["價值分數"]} vs 現任 ${cur["價值分數"]}；`;
  if (diff > err) return { kind: best["守備"] === "warn" ? "warn" : "go", best: best["球員"], title: `建議換上 ${best["球員"]} 代打`, text: `${sc}預估勝率 ${sign(diff)}%，差距大於誤差範圍（±${err.toFixed(2)}%）。${def}` };
  return { kind: "neutral", best: best["球員"], title: `可考慮 ${best["球員"]}，但差距不明顯`, text: `${sc}預估勝率 ${sign(diff)}%，仍在誤差範圍內（±${err.toFixed(2)}%），續打也合理。${def}` };
}

function renderResult() {
  const R = S.last, s = R.situation;
  const view = R.view;
  const halfZh = s.half === "away" ? "上" : "下";
  const outs = [1, 2, 3].map((i) => `<i class="${i <= s.outs ? "on" : ""}"></i>`).join("");
  const levPct = Math.min(100, R.leverage / 30 * 100), avgPct = R.league_leverage / 30 * 100;
  const diff = s.bat_score - s.fld_score;
  const levTxt = R.leverage >= 15 ? "高張力" : R.leverage >= 10 ? "中高張力" : R.leverage >= 6 ? "一般" : "低張力";

  let html = `
  <div class="card">
    <div class="scoreboard">
      <div class="sb-inning num">${s.inning}<small>局${halfZh}</small></div>
      <div class="sb-score">
        <div class="sb-team"><div class="t">${esc(s.bat_team || "進攻方")}</div><div class="s num">${s.bat_score}</div></div>
        <div class="sb-vs">:</div>
        <div class="sb-team"><div class="t">${esc(s.fld_team || "防守方")}</div><div class="s num">${s.fld_score}</div></div>
      </div>
      <div class="sb-mini">${miniDiamond(s.bases)}<div><div class="outs-ro">${outs}</div><div class="mut" style="font-size:12px;margin-top:2px">${s.outs} 出局・${BASES[s.bases]}</div></div></div>
      <div class="sb-pitcher"><span class="mut">投手</span> <b>${esc(s.pitcher)}</b> ${handChip(s.phand)}
        ${s.pitch_count != null ? `<div class="mut num" style="font-size:12px">${s.starter ? "先發" : "後援"}・本場已投 <b class="${(s.starter && s.pitch_count >= 90) || (!s.starter && s.pitch_count >= 30) ? "neg" : ""}">${s.pitch_count}</b> 球</div>` : ""}</div>
      <div class="lev">
        <div class="lbl"><span>局勢張力：<b class="big">${levTxt}</b></span><span>1 分 ≈ <b class="num">${R.leverage.toFixed(1)}%</b> 勝率</span></div>
        <div class="bar"><div class="fill" style="width:${levPct}%"></div><div class="avg" style="left:${avgPct}%" title="聯盟平均 ${R.league_leverage.toFixed(1)}%"></div></div>
        <div class="lbl" style="margin-top:2px"><span>${diff === 0 ? "平手" : diff > 0 ? `進攻方領先 ${diff}` : `進攻方落後 ${-diff}`}</span><span>平均 ${R.league_leverage.toFixed(1)}%</span></div>
      </div>
    </div>`;

  if (view !== "defense") {
    const rec = recommendation(R.candidates);
    S.bestName = rec.best;
    html += `<div class="reco ${rec.kind === "go" ? "" : rec.kind}" style="border-top:1px solid var(--line)">
      <div class="ic">${rec.kind === "go" ? "↑" : rec.kind === "warn" ? "!" : "="}</div>
      <div><h3>${esc(rec.title)}</h3><p>${esc(rec.text)}</p></div></div>`;
  } else {
    const rows = R.bullpen.rows, best = rows.filter((r) => r["角色"] === "牛棚")[0];
    const curP = rows.find((r) => r["角色"] === "場上");
    const fat = curP && curP["疲勞調整"] > 0.0005 ? `已計入 ${esc(s.pitcher)} ${curP["用球數"]} 球的疲勞（3 打席 +${curP["疲勞調整"].toFixed(3)} 分）。` : "";
    S.bestName = null;
    if (best && best["守方勝率增減"] > 0) {
      html += `<div class="reco" style="border-top:1px solid var(--line)"><div class="ic">↻</div><div><h3>可考慮換上 ${esc(best["投手"])}</h3>
        <p>價值分數 ${best["價值分數"]} vs 場上 ${curP["價值分數"]}；對上接下來 3 棒，預估守方勝率 ${sign(best["守方勝率增減"])}%。${fat}${best["疲勞"] !== "-" ? `　⚠ ${esc(best["投手"])}：${esc(best["疲勞"])}` : ""}</p></div></div>`;
    } else {
      html += `<div class="reco neutral" style="border-top:1px solid var(--line)"><div class="ic">=</div><div><h3>建議 ${esc(s.pitcher)} 續投</h3><p>牛棚中沒有預估更好的選擇。${fat}</p></div></div>`;
    }
  }
  if (R.actual) {
    const a = R.actual;
    const bench = R.candidates.filter((c) => c["角色"] === "代打");
    const rank = bench.findIndex((c) => c["球員"] === a.batter) + 1;
    html += `<div class="actual"><span class="mut">實際發生：</span>
      <span>${a.is_ph ? `換上 <b>${esc(a.batter)}</b> 代打${rank ? `（系統排名第 ${rank} / ${bench.length}）` : ""}` : `<b>${esc(a.batter)}</b> 續打`}</span>
      <span>結果 <b>${esc(a.result)}</b></span><span>WPA <b class="${cls(a.WPA, 0)}">${sign(a.WPA, 3)}</b></span></div>`;
  }
  html += `</div>`;

  // 主表 + 側欄
  html += `<div id="pitchChange"></div>`;
  const showTabs = view === "replay";
  const tab = S.tab || (view === "defense" ? "pen" : "ph");
  html += `<div class="grid2"><div class="card">`;
  if (showTabs) html += `<div class="tabs"><button data-t="ph" class="${tab === "ph" ? "on" : ""}">代打評估（進攻方）</button><button data-t="pen" class="${tab === "pen" ? "on" : ""}">換投評估（防守方）</button></div>`;
  else html += `<div class="card-h"><h2>${view === "defense" ? "換投評估" : "代打評估"}</h2><span class="hint">${view === "defense" ? `對上 ${R.bullpen.next.map(esc).join("、")}` : "點選列可看球路明細"}</span></div>`;
  html += `<p class="table-help">點選球員姓名查看對決。小螢幕可左右滑動表格。</p><div class="tbl-wrap" tabindex="0" role="region" aria-label="球員評估表，可左右捲動">${(showTabs ? tab : view === "defense" ? "pen" : "ph") === "pen" ? penTable(R) : phTable(R)}</div></div>`;
  html += `<div>${mixCard(R)}<div id="detail"></div></div></div>`;
  html += `<div class="foot">評估方法：<b>${esc(R.method || "階層式")}</b>（完整實驗比較 11 種方法後選出；滑鼠移到預估勝率可看兩個模型各自的值）。<br>
    預估勝率＝相對「聯盟平均打者面對同一投手」的勝率增減，已依當下局勢換算；細線為誤差範圍。
    模型只使用 ${esc(R.model_cutoff)} 以前的資料。資料來源：Rebas Open Data（ODC-By）、ldkrsi/cpbl-opendata（MIT）、中華職棒官網守位統計。</div>`;
  $("#resultBody").innerHTML = html;
  mountPitchChange(R.situation.pitcher);

  $$(".tabs button").forEach((b) => b.onclick = () => { S.tab = b.dataset.t; renderResult(); });
  $$("tr[data-batter]").forEach((tr) => tr.onclick = () => showDetail(tr.dataset.batter, R.situation.pitcher, tr));
  $$("tr[data-pitcher]").forEach((tr) => tr.onclick = () => showDetail(R.bullpen.next[0], tr.dataset.pitcher, tr));
  const first = $("tr[data-batter].best-row") || $("tr[data-batter]");
  if (first && (showTabs ? tab : view === "defense" ? "pen" : "ph") === "ph") showDetail(first.dataset.batter, R.situation.pitcher, first);
}

const TIER = (v) => (v >= 80 ? ["s5", "極佳"] : v >= 60 ? ["s4", "佳"] : v >= 40 ? ["s3", "普通"] : v >= 20 ? ["s2", "不利"] : ["s1", "很不利"]);
function scoreBadge(v, tip) {
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
      <td class="ncell"><span class="role">${cur ? "現任" : "代打"}</span><button type="button" class="row-action" aria-label="查看 ${esc(x["球員"])} 對決">${esc(x["球員"])}</button> ${handChip(x["打擊"])}${best ? `<span class="best">建議</span>` : ""}
        <div class="parts">${(x["可守"] || "-").split(",").map((p) => POS[p] || p).join("・")}</div></td>
      <td>${scoreBadge(x["價值分數"], `面對 ${R.situation.pitcher}，勝過 ${x["價值分數"]}% 的主力打者（2025 年 100 打席以上）`)}</td>
      <td><div class="vcell" title="${x["機器學習"] != null ? `階層式 ${sign(x["階層式"], 3)}・梯度提升樹 ${sign(x["機器學習"], 3)}（每打席得分值，各占一半）` : ""}"><div class="vnum num"><span class="${cls(x["預估勝率"], 0.02)}">${sign(x["預估勝率"])}%</span>${cur ? "" : `<div class="parts ${cls(x["相對現任"], 0.02)}">比現任 ${sign(x["相對現任"])}</div>`}</div>${dbar(x["預估勝率"], x["誤差"], scale)}</div></td>
      <td style="white-space:nowrap"><span class="chip c-${x["可信度"]}">${x["可信度"]}</span><div class="mut num" style="font-size:11px">${Math.round(x["樣本球數"])} 球</div></td>
      <td><div class="def"><span class="d ${d}">${d === "ok" ? "✓" : d === "warn" ? "!" : "✕"}</span><span>${esc(x["守備說明"])}</span></div></td>
    </tr>`;
  }).join("");
  return `<div class="card-b" style="padding-bottom:0">${SCORE_LEGEND}</div><table class="t"><thead><tr><th>球員</th><th title="1–100：面對這位投手，勝過多少比例的主力打者">價值分數</th><th>預估勝率（相對聯盟平均）</th><th>可信度</th><th>守備檢查</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function penTable(R) {
  const rows = R.bullpen.rows;
  const scale = Math.max(0.5, ...rows.map((x) => Math.abs(x["守方勝率增減"])));
  const body = rows.map((x, i) => {
    const cur = x["角色"] === "場上";
    const best = !cur && i === 1 && x["守方勝率增減"] > 0;
    return `<tr data-pitcher="${esc(x["投手"])}" class="${cur ? "cur" : ""}">
      <td class="ncell" title="樣本 ${x["樣本球數"]} 球"><span class="role">${cur ? "場上" : "牛棚"}</span><button type="button" class="row-action" aria-label="查看 ${esc(x["投手"])} 配球與對決">${esc(x["投手"])}</button> ${handChip(x["投"] || "R")}${best ? `<span class="best">建議</span>` : ""}
        <div class="parts">${cur ? `本場已投 ${x["用球數"] ?? "—"} 球` : "未登板"}</div></td>
      <td>${scoreBadge(x["價值分數"], `對上接下來 3 棒，勝過 ${x["價值分數"]}% 的主力後援投手（2025 年 15 場以上）`)}</td>
      <td><div class="vcell"><span class="vnum num ${cls(x["守方勝率增減"], 0.02)}">${cur ? "基準" : sign(x["守方勝率增減"]) + "%"}</span>${dbar(x["守方勝率增減"], 0, scale)}</div></td>
      <td class="num">${x["預估失分"].toFixed(3)}${x["疲勞調整"] > 0.0005 ? `<div class="neg" style="font-size:11px">含疲勞 +${x["疲勞調整"].toFixed(3)}</div>` : ""}</td>
      <td>${x["疲勞"] === "-" ? `<span class="mut">—</span>` : `<span class="chip c-中">${esc(x["疲勞"])}</span>`}</td></tr>`;
  }).join("");
  return `<div class="card-b mut" style="font-size:12px;padding-bottom:0">對上接下來 3 棒：${R.bullpen.next.map(esc).join("、")}<div style="margin-top:6px">${SCORE_LEGEND}</div></div>
    <table class="t"><thead><tr><th>投手</th><th title="1–100：對上接下來 3 棒，勝過多少比例的主力後援投手">價值分數</th><th>守方勝率（相對場上投手）</th><th>預估失分值（3 打席）</th><th>疲勞／警示</th></tr></thead><tbody>${body}</tbody></table>`;
}

function mixCard(R) {
  const mix = R.pitch_mix;
  const bar = (h) => {
    const cells = mix[h].cells;
    return GROUPS.map((g) => {
      const hi = cells[g + "高中"] || 0, lo = cells[g + "低"] || 0;
      return `<div class="mix-row"><span>${g}</span>
        <div class="mix-bar"><span style="width:${hi * 100}%;background:${GROUP_COLOR[g]};opacity:.55" title="高中 ${(hi * 100).toFixed(0)}%"></span><span style="width:${lo * 100}%;background:${GROUP_COLOR[g]}" title="低球 ${(lo * 100).toFixed(0)}%"></span></div>
        <span class="num mut" style="text-align:right">${((hi + lo) * 100).toFixed(0)}%</span></div>`;
    }).join("");
  };
  return `<div class="card"><div class="card-h"><h2>${esc(R.situation.pitcher)} 的球路</h2></div><div class="card-b">
    <div class="mix-h"><span>對右打</span><span>${mix.R.n} 球</span></div>${bar("R")}
    <div class="mix-h"><span>對左打</span><span>${mix.L.n} 球</span></div>${bar("L")}
    <div class="legend"><span><i style="background:#888;opacity:.55"></i>高中位置</span><span><i style="background:#888"></i>低球（好球帶下緣附近以下）</span></div>
  </div></div>`;
}

let detailGeneration = 0;
function mountPitchChange(pitcher, hand = "ALL") {
  const cutoff = String(S.last.view === 'replay' ? S.last.situation.date : S.last.model_cutoff).slice(0, 10);
  const season = S.last.view === "replay" ? Number(cutoff.slice(0, 4)) : 2025;
  PitchChange.mount({element: $("#pitchChange"), pitcher, cutoff, season, hand,
    fetcher: STATIC ? PitchChange.staticResult : (o) => api(`api/pitch-change?${new URLSearchParams(o)}`)});
}
async function showDetail(batter, pitcher, tr) {
  const token = ++detailGeneration;
  $$("tr.sel").forEach((x) => x.classList.remove("sel"));
  tr?.classList.add("sel");
  mountPitchChange(pitcher); // Independent of a failing eight-cell detail request.
  const box = $("#detail");
  box.innerHTML = `<div class="card" style="margin-top:16px"><div class="card-b"><span class="loading"></span></div></div>`;
  try {
    const d = await api(`api/detail?batter=${encodeURIComponent(batter)}&pitcher=${encodeURIComponent(pitcher)}&date=${S.last.model_cutoff}`);
    if (token !== detailGeneration || box !== $("#detail")) return;
    mountPitchChange(pitcher, d.bhand);
    const cell = (k) => d.cells.find((c) => c.cell === k);
    const tile = (k) => {
      const c = cell(k);
      const wd = c.whiff_dev * 100;
      return `<div class="c" title="打者在此格的樣本 ${Math.round(c.n)} 球">
        <div class="u" style="height:${Math.min(100, c.usage * 250)}%"></div>
        <div class="k num">${(c.usage * 100).toFixed(0)}%</div>
        <div class="w num ${wd > 0.5 ? "neg" : wd < -0.5 ? "pos" : "mut"}">揮空 ${wd >= 0 ? "+" : "−"}${Math.abs(wd).toFixed(1)}pp</div></div>`;
    };
    box.innerHTML = `<div class="card" style="margin-top:16px"><div class="card-h"><h2>${esc(d.batter)} vs ${esc(d.pitcher)}</h2>
      <span class="hint">${d.bhand === "L" ? "左" : "右"}打 vs ${d.phand === "L" ? "左" : "右"}投</span></div><div class="card-b">
      <div class="heat"><div></div><div class="hh">高中位置</div><div class="hh">低球</div>
        ${GROUPS.map((g) => `<div class="rl">${g}</div>${tile(g + "高中")}${tile(g + "低")}`).join("")}</div>
      <p class="mut" style="font-size:11px;margin:10px 0 0">大字＝投手使用率（底色越深越常投）；揮空＝此打者在該格相對自身平均的揮空率偏離（紅＝較易揮空）。</p>
      <div class="breakdown">
        <div><small>本身能力</small><b class="num ${cls(d.skill, 0.002)}">${sign(d.skill, 3)}</b></div>
        <div><small>球路適性</small><b class="num ${cls(d.fit, 0.002)}">${sign(d.fit, 3)}</b></div>
        <div><small>左右投打</small><b class="num ${cls(d.platoon, 0.002)}">${sign(d.platoon, 3)}</b></div>
      </div><p class="mut" style="font-size:11px;margin:6px 0 0">單位：每打席得分值。打者總樣本 ${Math.round(d.n)} 球。</p></div></div>`;
  } catch (e) {
    if (token !== detailGeneration || box !== $("#detail")) return;
    box.innerHTML = `<div class="err-box" style="margin-top:16px">${esc(e.message)}</div>`;
  }
}

init().catch((e) => {
  $("#emptyState").innerHTML = `<div class="err-box" role="alert">資料載入失敗：${esc(e.message)}<br>請確認本機伺服器或靜態資料可用。<button class="retry">重新載入頁面</button></div>`;
  $("#emptyState .retry").onclick = () => location.reload();
});
