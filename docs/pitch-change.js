/* Descriptive companion to matchup detail; never changes recommendation scores. */
"use strict";
window.PitchChange = (() => {
  const escape = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const pct = v => v == null ? "—" : `${(v * 100).toFixed(1)}%`;
  const pp = v => v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)} 百分點`;
  const requests = new Map();
  const timeoutOptions = ms => typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function" ? {signal:AbortSignal.timeout(ms)} : {};
  async function fetchData(url) {
    if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') return fetch(url, timeoutOptions(30000));
    if (typeof AbortController === 'undefined') return fetch(url);
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 30000);
    try { return await fetch(url, {signal:controller.signal}); } finally { clearTimeout(timer); }
  }
  async function read(url) {
    if (!requests.has(url)) requests.set(url, fetchData(url).then(r => {
      if (!r.ok) throw new Error("近期配球資料尚未匯出或無法取得");
      return r.json();
    }).catch(e => { requests.delete(url); throw e; }));
    return requests.get(url);
  }
  async function staticResult({pitcher, season, cutoff, hand}) {
    if (!['ALL','L','R'].includes(hand)) throw new Error('左右打參數無效');
    if (!/^\d{4}-\d{2}-\d{2}$/.test(cutoff) || Number.isNaN(Date.parse(cutoff)) || new Date(cutoff).toISOString().slice(0,10) !== cutoff) throw new Error('截止日期無效');
    const root = `data/pitch-change/${season}/`;
    const index = await read(root + "index.json");
    if (index.schema_version !== 1) throw new Error("配球資料版本不相容");
    const key = index.pitchers[pitcher];
    if (!key) throw new Error("此投手在所選球季沒有配球資料");
    const file = await read(root + key);
    if (file.schema_version !== 1) throw new Error("配球資料版本不相容");
    const eligible = file.snapshots.filter(s => s.effective_from <= cutoff);
    const snap = eligible[eligible.length - 1];
    if (!snap) throw new Error("截止日早於所選球季");
    if (!snap.hands[hand]) throw new Error('左右打資料缺漏，請重新匯出');
    return {...snap.hands[hand], cutoff};
  }
  function render(d) {
    const b = d.windows.baseline, r = d.windows.recent;
    const range = w => w.games.length ? `${w.games[0].date} 至 ${w.games.at(-1).date}` : "沒有符合日期的出賽";
    const window = (w, title, kind) => `<div class="pc-window ${kind}"><strong>${title}</strong><span>${range(w)}</span><b>${w.selected_games} 場 · ${w.valid_pitches} 球</b></div>`;
    const hasValues=d.rows.some(row=>row.delta_pp!=null||row.adjusted.some(v=>v!=null));
    return `<div class="pc-status ${d.status === 'ready' ? '' : 'pc-insufficient'}" role="status">${d.status === "ready" ? "同條件配球比較" : "樣本不足，暫不判定"}</div>
      <div class="pc-windows">${window(b,"之前最多 10 場","baseline")}${window(r,"最近 5 場","recent")}</div>
      <div class="pc-legend"><span class="pc-key baseline">基準期</span><span class="pc-key recent">近期</span><span>差值：百分點</span></div>
      <div class="pc-rows">${(hasValues?d.rows:[]).map(row => `<article class="pc-row"><div class="pc-row-title"><strong>${escape(row.group)}</strong><b>${pp(row.delta_pp)}</b><span>${escape(d.status==='ready'?row.interpretation:'')}</span></div>
        <div class="pc-bars">${row.adjusted.map((v,i) => `<div class="pc-bar-line"><span>${i ? "近期" : "基準"}</span><div class="pc-track"><div class="pc-bar ${i ? "recent" : "baseline"}" style="width:${v == null ? 0 : v*100}%"></div></div><b>${pct(v)}</b></div>`).join("")}</div>
        </article>`).join("")}</div>
      <details class="pc-method"><summary>樣本與比較依據</summary><p>${d.season} 球季 · ${escape(d.cutoff)} 之前；最後紀錄 ${escape(d.last_observed || '無')}。歷史資料，非即時配球。</p>${d.reasons.length ? `<ul>${d.reasons.map(v=>`<li>${escape(v)}</li>`).join('')}</ul>` : ''}<p>依球數與左右打調整；共同條件涵蓋基準 ${pct(d.coverage[0])}／近期 ${pct(d.coverage[1])}。未控制捕手、對手、球場與比分；少量出賽的區間可能不穩定。</p><ul>${d.rows.map(row=>`<li>${escape(row.group)}：95% 重抽樣區間 ${row.interval ? `${pp(row.interval[0])} 至 ${pp(row.interval[1])}` : '無法可靠估計'}</li>`).join('')}</ul><p>「低落」為球種群名稱。來源：${escape(d.source)}。</p></details>
      <p class="pc-caveat">配球改變不代表效果變好，也不是下一球預測。</p>`;
  }
  function mount({element, pitcher, cutoff, season=2025, hand="ALL", fetcher}) {
    if (!element || !pitcher) return;
    const wasOpen = element.querySelector('.pc-toggle')?.getAttribute('aria-expanded') !== 'false';
    let generation = 0;
    let opened = false;
    element.innerHTML = `<section class="card pc-card"><div class="card-h"><div><h2>同條件近期配球變化</h2><p class="pc-subtitle">${escape(pitcher)}</p></div><button class="pc-toggle" type="button" aria-expanded="false">查看配球變化</button></div><div class="pc-body" hidden><div class="pc-controls"><label>面對打者<select aria-label="配球比較的實際打者左右打"><option value="ALL">左右打合計</option><option value="L">面對左打</option><option value="R">面對右打</option></select></label><button class="pc-retry" type="button">重新載入</button></div><div class="pc-result" aria-live="polite"></div></div></section>`;
    const toggle = element.querySelector('.pc-toggle'), body = element.querySelector('.pc-body');
    const select = element.querySelector('select'), result = element.querySelector('.pc-result');
    select.value = ['ALL','L','R'].includes(hand) ? hand : 'ALL';
    async function update() {
      const token = ++generation;
      result.setAttribute('aria-busy','true');
      result.innerHTML = '<p role="status">載入配球比較…</p>';
      try {
        const options = {pitcher, cutoff, season, hand:select.value};
        const d = await fetcher(options);
        if (token !== generation || !element.contains(result)) return;
        result.innerHTML = render(d);
      } catch (e) {
        if (token !== generation || !element.contains(result)) return;
        result.innerHTML = `<p role="alert">${escape(e.message)}。可按「重新載入」重試。</p>`;
      } finally { if (token === generation) result.setAttribute('aria-busy','false'); }
    }
    toggle.onclick = () => {
      const visible = body.hidden;
      body.hidden = !visible;
      toggle.setAttribute('aria-expanded',String(visible));
      toggle.textContent = visible ? '收合配球變化' : '查看配球變化';
      if (visible && !opened) { opened = true; update(); }
    };
    select.onchange = update;
    element.querySelector('.pc-retry').onclick = update;
    if (wasOpen) toggle.onclick();
  }
  return {mount, staticResult};
})();
