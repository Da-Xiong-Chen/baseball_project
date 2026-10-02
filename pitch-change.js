/* Descriptive companion to matchup detail; never changes recommendation scores. */
"use strict";
window.PitchChange = (() => {
  const escape = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const pct = v => v == null ? "—" : `${(v * 100).toFixed(1)}%`;
  const pp = v => v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)} pp`;
  const requests = new Map();
  const timeoutOptions = ms => typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function" ? {signal:AbortSignal.timeout(ms)} : {};
  async function read(url) {
    if (!requests.has(url)) requests.set(url, fetch(url, timeoutOptions(30000)).then(r => {
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
    const window = (w, title, kind, coverage) => `<div class="pc-window ${kind}"><strong>${title}</strong><span>${range(w)}</span><b>${w.selected_games} 場 · ${w.valid_pitches} 球</b><span>有效出賽 ${w.effective_games} 場 · 共同條件涵蓋 ${pct(coverage)}</span><span>未知球種 ${w.unknown_type} 球（${pct(w.unknown_rate)}）</span></div>`;
    return `<div class="pc-status ${d.status === 'ready' ? '' : 'pc-insufficient'}" role="status">${d.status === "ready" ? "可比較：已校正球數與實際左右打組成" : "樣本不足：下列數字僅供描述，不能據此判定配球已改變"}</div>
      ${d.reasons.length ? `<ul class="pc-reasons">${d.reasons.map(v => `<li>${escape(v)}</li>`).join("")}</ul>` : ""}
      <div class="pc-windows">${window(b,"基準期 · 之前最多 10 場","baseline",d.coverage[0])}${window(r,"近期 · 最近 5 場","recent",d.coverage[1])}</div>
      <p>比較範圍：${d.season} 球季，僅使用 <b>${escape(d.cutoff)} 之前</b>的比賽。最後觀測 ${escape(d.last_observed || "無")}。</p>
      <p class="pc-help">pp＝百分點；例如 10% → 15% 是增加 5 pp。長條只比較兩期都足夠的共同條件，不代表所有投球。方向提示採未四捨五入的差異判斷（5 pp 門檻）。</p>
      <div class="pc-legend"><span class="pc-key baseline">基準期</span><span class="pc-key recent">近期</span><span>長條＝條件調整後比例</span></div>
      <div class="pc-rows">${d.rows.map(row => `<article class="pc-row"><div class="pc-row-title"><strong>${escape(row.group)}</strong><b>${pp(row.delta_pp)}</b><span>${escape(row.interpretation)}</span></div>
        <div class="pc-bars">${row.adjusted.map((v,i) => `<div class="pc-bar-line"><span>${i ? "近期" : "基準"}</span><div class="pc-track"><div class="pc-bar ${i ? "recent" : "baseline"}" style="width:${v == null ? 0 : v*100}%"></div></div><b>${pct(v)}</b></div>`).join("")}</div>
        <div class="pc-row-note">原始比例 ${pct(row.raw[0])} → ${pct(row.raw[1])}<br>95% 重抽樣區間：${row.interval ? `${pp(row.interval[0])} 至 ${pp(row.interval[1])}` : "無法可靠估計"}</div></article>`).join("")}</div>
      <details class="pc-method"><summary>查看比較條件與方法</summary><p>以基準期的球數 × 實際打者左右打組成作為固定權重；每個共同條件在兩期至少 ${d.settings.min_stratum} 球。區間以整場出賽為單位重抽樣 ${d.bootstrap.requested} 次，有效 ${d.bootstrap.valid} 次。少量出賽下的區間仍可能不穩定，屬探索性描述。</p>
      <div class="pc-table-wrap"><table><caption>共同條件與基準期權重</caption><thead><tr><th>打者 / 球數</th><th>基準球數</th><th>近期球數</th><th>納入 / 權重</th></tr></thead><tbody>${d.strata.map(s => `<tr><th>${s.hand === "L" ? "左" : "右"}打 · ${s.balls} 壞 ${s.strikes} 好</th><td>${s.baseline}</td><td>${s.recent}</td><td>${s.included ? pct(s.weight) : "未納入"}</td></tr>`).join("")}</tbody></table></div>
      <p>排除投球（所有左右打，未混入有效分母）：基準 ${escape(JSON.stringify(b.excluded))}；近期 ${escape(JSON.stringify(r.excluded))}。unknown_hand＝左右打不明；ambiguous_count＝球數無法可靠重建；pitcher_mismatch＝打席與逐球投手歸屬不一致。</p></details>
      <p class="pc-caveat">配球變化不等於效果變好，也不能直接當作下一球預測。未觀測某球種不等於其真實機率為零。尚未控制捕手、對手、球場與比分。「低落」是既有球種群名稱，不代表投球落點。本展示使用 2025 球季資料，不是 2026 即時資訊。來源：${escape(d.source)}。</p>`;
  }
  function mount({element, pitcher, cutoff, season=2025, hand="ALL", fetcher}) {
    if (!element || !pitcher) return;
    const wasOpen = element.querySelector('.pc-toggle')?.getAttribute('aria-expanded') === 'true';
    let generation = 0;
    let opened = false;
    element.innerHTML = `<section class="card pc-card"><div class="card-h"><div><h2>同條件近期配球變化</h2><p class="pc-subtitle">${escape(pitcher)} · 對決前的配球趨勢參考</p></div><button class="pc-toggle" type="button" aria-expanded="false">查看配球變化</button></div><div class="pc-body" hidden><div class="pc-controls"><label>實際打者左右打<select aria-label="配球比較的實際打者左右打"><option value="ALL">左右打合計</option><option value="L">面對左打</option><option value="R">面對右打</option></select></label><button class="pc-retry" type="button">重新載入</button></div><div class="pc-result" aria-live="polite"></div></div></section>`;
    const toggle = element.querySelector('.pc-toggle'), body = element.querySelector('.pc-body');
    const select = element.querySelector('select'), result = element.querySelector('.pc-result');
    select.value = ['ALL','L','R'].includes(hand) ? hand : 'ALL';
    async function update() {
      const token = ++generation;
      result.setAttribute('aria-busy','true');
      result.innerHTML = '<p role="status">正在整理兩期配球與樣本品質…</p>';
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
