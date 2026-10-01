"use strict";
/* 靜態版計算引擎（GitHub Pages 用）：與 src/model.py、src/engine.py、src/roster.py、src/fatigue.py 邏輯一致。
   模型參數來自 data/model.json（python src/export_static.py 匯出）。 */

const Engine = (() => {
  let M = null;
  const POS_ZH = { C: "捕手", "1B": "一壘", "2B": "二壘", "3B": "三壘", SS: "游擊", LF: "左外野", CF: "中外野", RF: "右外野", DH: "指定打擊" };

  async function load(base = "data/") {
    if (!M) M = await (await fetch(base + "model.json")).json();
    return M;
  }

  // ---------- 局勢 ----------
  function stateKey(inning, half, diff, bases, outs) {
    const inn = Math.min(Math.max(inning, 1), 9);
    const innB = inn <= 3 ? "1-3" : inn <= 6 ? "4-6" : String(inn);
    return [innB, half, Math.max(-4, Math.min(4, Math.trunc(diff))), bases, outs];
  }
  function runToWin(inning, half, batScore, fldScore, bases, outs) {
    const k = stateKey(inning, half, batScore - fldScore, bases, outs);
    const fine = M.slope_fine[k.join("|")];
    if (fine != null) return fine;
    const coarse = M.slope_coarse[k.slice(0, 3).join("|")];
    return coarse != null ? coarse : M.slope_all;
  }

  // ---------- 對戰 ----------
  const hand = (h) => (h === "L" || h === "R" ? h : "R");
  function batHand(batter, phand) {
    const h = M.bhand[batter] || "R";
    return h === "S" ? (phand === "R" ? "L" : "R") : h;
  }
  function pitchMix(pitcher, bhand) {
    bhand = hand(bhand);
    const row = M.mix[pitcher] && M.mix[pitcher][bhand];
    if (row) return { m: row.slice(0, M.cells.length), n: row[M.cells.length] };
    const ph = hand(M.phand[pitcher]);
    return { m: M.league_mix[`${ph}|${bhand}`], n: 0 };
  }
  function neutralBase(m) {
    return M.cells.reduce((s, c, i) => s + m[i] * ((M.league[`同側|${c}`] || 0) + (M.league[`異側|${c}`] || 0)) / 2, 0);
  }
  function matchup(batter, bhand, pitcher) {
    bhand = hand(bhand);
    const { m, n: mixN } = pitchMix(pitcher, bhand);
    const ph = hand(M.phand[pitcher]);
    const platoonKey = ph === bhand ? "同側" : "異側";
    const lgBase = M.cells.reduce((s, c, i) => s + m[i] * (M.league[`${platoonKey}|${c}`] || 0), 0);
    const a = M.bat_all[batter];
    const [aEff, aVar, n] = a ? a : [0, M.k.sigma2 / M.k.bat, 0];
    const bc = M.bat_cell[batter] || {};
    const cellEff = M.cells.map((c) => (bc[c] ? bc[c][0] : 0));
    const cellVar = M.cells.map((c) => (bc[c] ? bc[c][1] : 0));
    const q = M.pit_all[pitcher] ? M.pit_all[pitcher][0] : 0;
    const fit = M.cells.reduce((s, _, i) => s + m[i] * cellEff[i], 0);
    const skill = aEff + fit;
    const platoon = lgBase - neutralBase(m);
    const se = Math.sqrt(aVar + M.cells.reduce((s, _, i) => s + m[i] ** 2 * cellVar[i], 0));
    const f = M.ppa;
    return {
      per_pa: (lgBase + skill + q) * f, rel_pa: (skill + platoon) * f, skill_pa: skill * f, fit_pa: fit * f,
      platoon_pa: platoon * f, se_pa: se * f, n: Math.trunc(n), mix_n: mixN, mix: m, cell_eff: cellEff,
    };
  }

  // ---------- 守備 ----------
  const positionsOf = (name) => M.eligible[name] || [];
  const canPlay = (name, pos) => pos === "DH" || positionsOf(name).includes(pos);
  function defenseCheck(outName, outPos, inName, benchAfter) {
    if (outPos === "DH") return ["ok", `${inName} 接任指定打擊`];
    let msg, status;
    if (canPlay(inName, outPos)) {
      msg = `${inName} 可直接接守${POS_ZH[outPos]}`; status = "ok";
    } else {
      const cover = benchAfter.filter((b) => canPlay(b, outPos));
      if (!cover.length) return ["bad", `換下後板凳無人可守${POS_ZH[outPos]}`];
      msg = `需由 ${cover[0]} 接守${POS_ZH[outPos]}（再消耗 1 名板凳）`; status = "warn";
    }
    if (outPos === "C" && !benchAfter.filter((b) => canPlay(b, "C") && b !== inName).length) {
      msg += "；之後板凳已無備用捕手";
      if (status === "ok") status = "warn";
    }
    return [status, msg];
  }

  // ---------- 疲勞 ----------
  function penalty(pc, starter) {
    if (!starter || pc == null) return 0;
    const pts = M.fatigue.curve;
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const last = xs.length - 1;
    if (pc <= xs[last]) {
      if (pc <= xs[0]) return ys[0];
      for (let i = 1; i <= last; i++) if (pc <= xs[i]) return ys[i - 1] + (ys[i] - ys[i - 1]) * (pc - xs[i - 1]) / (xs[i] - xs[i - 1]);
    }
    const slope = last > 0 ? (ys[last] - ys[last - 1]) / (xs[last] - xs[last - 1]) : 0;
    return Math.min(M.fatigue.cap, ys[last] + slope * (pc - xs[last]));
  }
  function outlook(pc, starter, nBatters) {
    pc = pc || 0;
    let total = 0;
    for (let i = 0; i < nBatters; i++) total += penalty(pc + M.ppa * i, starter);
    let warn = null;
    if (starter && pc >= 90) warn = `先發 ${pc} 球`;
    else if (!starter && pc >= M.fatigue.reliever_warn) warn = `後援 ${pc} 球（資料不足未調整）`;
    return [total, warn];
  }
  function isStarter(pitcher) {
    for (const t of M.teams) {
      const p = M.rosters[t].pitchers.find((x) => x.name === pitcher);
      if (p) return p.role === "先發";
    }
    return false;
  }

  // ---------- 評估 ----------
  function evaluatePinchHit(row, due, duePos, bench) {
    const slope = runToWin(row.inning, row.half, row.bat_score, row.fld_score, row.bases, row.outs);
    const out = [due, ...bench].map((name) => {
      const bh = batHand(name, row.phand);
      const r = matchup(name, bh, row.pitcher);
      const rec = {
        角色: name === due ? "現任" : "代打", 球員: name, 打擊: bh,
        預估勝率: r.rel_pa * slope * 100, 誤差: r.se_pa * slope * 100, 每打席得分值: r.rel_pa,
        本身能力: r.skill_pa - r.fit_pa, 球路適性: r.fit_pa, 左右優勢: r.platoon_pa, 樣本球數: r.n,
        可守: positionsOf(name).join(",") || "-",
      };
      if (name !== due) [rec.守備, rec.守備說明] = defenseCheck(due, duePos, name, bench.filter((b) => b !== name));
      else [rec.守備, rec.守備說明] = ["ok", `目前守${POS_ZH[duePos] || duePos}`];
      rec.可信度 = r.n >= 1500 ? "高" : r.n >= 500 ? "中" : "低";
      return rec;
    });
    const base = out[0].預估勝率;
    out.forEach((r) => (r.相對現任 = r.預估勝率 - base));
    const rest = out.slice(1).sort((a, b) => b.預估勝率 - a.預估勝率);
    return { rows: [out[0], ...rest], slope };
  }
  function evaluateBullpen(row, nextBatters, pen, pc, starter) {
    const slope = runToWin(row.inning, row.half, row.bat_score, row.fld_score, row.bases, row.outs);
    const [fatRuns, fatWarn] = outlook(pc, starter, nextBatters.length);
    const rows = [row.pitcher, ...pen.filter((p) => p !== row.pitcher)].map((pit) => {
      const ph = hand(M.phand[pit]);
      const cur = pit === row.pitcher;
      const runs = nextBatters.reduce((s, b) => s + matchup(b, batHand(b, ph), pit).per_pa, 0);
      const extra = cur ? fatRuns : 0;
      return {
        角色: cur ? "場上" : "牛棚", 投手: pit, 投: ph, 預估失分: runs + extra, 疲勞調整: extra,
        用球數: cur ? pc : 0, 樣本球數: Math.trunc(M.pit_all[pit] ? M.pit_all[pit][1] : 0),
        疲勞: cur && fatWarn ? fatWarn : "-",
      };
    });
    const curRuns = rows[0].預估失分;
    rows.forEach((r) => (r.守方勝率增減 = -(r.預估失分 - curRuns) * slope * 100));
    return [rows[0], ...rows.slice(1).sort((a, b) => a.預估失分 - b.預估失分)];
  }
  function pitchMixPayload(pitcher) {
    const res = {};
    for (const h of ["R", "L"]) {
      const { m, n } = pitchMix(pitcher, h);
      res[h] = { n: Math.trunc(n), cells: Object.fromEntries(M.cells.map((c, i) => [c, m[i]])) };
    }
    return res;
  }

  /** 與 server.py /api/evaluate 相同的輸入輸出。 */
  function evaluate(b) {
    const row = {
      inning: +b.inning, half: b.half, bat_score: +b.bat_score, fld_score: +b.fld_score, bases: +b.bases, outs: +b.outs,
      pitcher: b.pitcher, phand: hand(M.phand[b.pitcher]), bat_team: b.bat_team, fld_team: b.fld_team, date: M.cutoff,
    };
    const ph = evaluatePinchHit(row, b.due, b.due_pos, b.bench);
    const next = b.next_batters && b.next_batters.length ? b.next_batters.slice(0, 3) : [b.due];
    const starter = b.starter != null ? !!b.starter : isStarter(b.pitcher);
    const pc = b.pitch_count == null || b.pitch_count === "" ? null : +b.pitch_count;
    const pen = b.pen || [];
    return {
      situation: { ...row, pitch_count: pc, starter, due: b.due, due_pos: b.due_pos, due_pos_zh: POS_ZH[b.due_pos] || b.due_pos },
      actual: null, leverage: ph.slope * 100, league_leverage: M.slope_all * 100,
      pitch_mix: pitchMixPayload(row.pitcher), candidates: ph.rows,
      bullpen: { next, rows: evaluateBullpen(row, next, pen, pc, starter) }, model_cutoff: M.cutoff,
    };
  }

  function detail(batter, pitcher) {
    const ph = hand(M.phand[pitcher]);
    const bh = batHand(batter, ph);
    const r = matchup(batter, bh, pitcher);
    const bc = M.bat_cell[batter] || {};
    return {
      batter, pitcher, bhand: bh, phand: ph, mix_n: r.mix_n, n: r.n,
      cells: M.cells.map((c, i) => ({ cell: c, usage: r.mix[i], effect: r.cell_eff[i], whiff_dev: bc[c] ? bc[c][3] : 0, n: bc[c] ? bc[c][2] : 0 })),
      skill: r.skill_pa - r.fit_pa, fit: r.fit_pa, platoon: r.platoon_pa,
    };
  }

  return { load, evaluate, detail, model: () => M };
})();
