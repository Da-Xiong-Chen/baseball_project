"""決策引擎：給定一個比賽時點，評估「續打 vs 各代打人選」與「牛棚各投手」。"""
from functools import lru_cache

import pandas as pd

from fatigue import outlook, pitch_count_before
from load import load
from mlmodel import ENSEMBLE_W
from model import PITCHES_PER_PA, fit
import numpy as np
import recent

from roster import POS_ZH, active_roster, assign_positions, defense_check, hitter_pool, positions_of, reliever_pool


@lru_cache(maxsize=32)
def model_at(date_str):
    return fit(date_str)


@lru_cache(maxsize=64)
def _hands(cutoff=None):
    pa, _, _ = load()
    if cutoff:
        pa = pa[pa["date"] < pd.Timestamp(cutoff)]
    b = pa.groupby("batter")["bhand"].agg(lambda s: "S" if s.nunique() > 1 and s.value_counts(normalize=True).min() > 0.1 else s.mode().iat[0])
    p = pa.groupby("pitcher")["phand"].agg(lambda s: s.mode().iat[0])
    return b, p


def bat_hand(batter, phand, cutoff=None):
    b, _ = _hands(cutoff)
    h = b.get(batter, "R")
    if h == "S":
        return "L" if phand == "R" else "R"
    return h


def situation(pa_id):
    """由歷史打席重建「該打席開始前」的決策情境。"""
    pa, _, boxes = load()
    row = pa.loc[pa["pa_id"] == pa_id].iloc[0]
    game_pa = pa[(pa["game"] == row["game"]) & (pa["half"] == row["half"])]
    before = game_pa[game_pa["seq"] < row["seq"]]

    box = boxes[(boxes["game"] == row["game"]) & (boxes["team"] == row["bat_team"]) & (boxes["role"] == "B")]
    lineup = box.groupby("order")["name"].first().to_dict()  # 先發
    for _, r in before.iterrows():
        lineup[r["pa_order"]] = r["batter"]
    due = lineup.get(row["pa_order"], row["batter"])        # 決策當下輪到的人（若實際換了代打，這裡是原打者）
    used = set(box.groupby("order")["name"].first()) | set(before["batter"])

    hitters, _ = active_roster(row["bat_team"], row["date"], row["game"])
    bench = [h for h in hitters if h not in used and h not in lineup.values()]
    pos = assign_positions([lineup[k] for k in sorted(lineup)], str(row["date"].date()))

    # 防守方：已用過的投手
    fld_before = pa[(pa["game"] == row["game"]) & (pa["fld_team"] == row["fld_team"]) & (pa["date"] == row["date"])]
    fld_before = fld_before[(fld_before["inning"] < row["inning"]) | ((fld_before["inning"] == row["inning"]) & (fld_before["seq"] < row["seq"]))]
    pc, starter = pitch_count_before(row)
    return dict(row=row, lineup=lineup, due=due, bench=bench, positions=pos,
                used_pitchers=set(fld_before["pitcher"]) | {row["pitcher"]},
                pitch_count=pc, starter=starter)


def value_score(v, pool, higher_better=True):
    """價值分數 1–100：v 在比較基準中的百分位（50 ≈ 聯盟平均）。"""
    pool = np.asarray(pool)
    if len(pool) == 0:
        return None
    beat = (pool < v) if higher_better else (pool > v)
    frac = (beat.sum() + 0.5 * (pool == v).sum()) / len(pool)
    return int(np.clip(round(1 + 99 * frac), 1, 100))


def recent_form(m, names, who="batter"):
    """近況偏離（每打席得分值；打者正值＝近期較好，投手正值＝近期較差）。"""
    b, p = recent.for_model(m)
    s = b if who == "batter" else p
    return np.array([float(s.get(n, 0.0)) * PITCHES_PER_PA for n in names])


def ensemble_rel(m, ml, names, hands, pitcher, recent_w=0.0):
    """每打席得分值（相對聯盟平均打者）：階層式與梯度提升樹集成；recent_w > 0 時加入使用者設定的近況權重。"""
    h = np.array([m.matchup(n, b, pitcher)["rel_pa"] for n, b in zip(names, hands)])
    adj = recent_w * recent_form(m, names) if recent_w else 0.0
    if not ml:
        return h + adj, h, None
    g = ml.rel_many([(n, b, pitcher) for n, b in zip(names, hands)])
    return (1 - ENSEMBLE_W) * h + ENSEMBLE_W * g + adj, h, g


def runs_matrix(m, ml, pitchers, batters):
    """每位投手對上每位打者的預期每打席得分值：(階層式, 梯度提升樹或 None)，形狀為 投手數 × 打者數。"""
    cutoff = str(m.cutoff.date())
    _, phands = _hands(cutoff)
    rows = [(b, bat_hand(b, phands.get(p, "R"), cutoff), p) for p in pitchers for b in batters]
    h = np.array([m.matchup(b, bh, p)["per_pa"] for b, bh, p in rows]).reshape(len(pitchers), len(batters))
    g = ml.abs_many(rows).reshape(len(pitchers), len(batters)) if ml else None
    return h, g


def ensemble_runs(m, ml, pitchers, batters, matrix=None, recent_w=0.0):
    """每位投手對上 batters 的預期失分合計（集成）。matrix 為已算好的 runs_matrix 結果。"""
    h, g = matrix or runs_matrix(m, ml, pitchers, batters)
    adj = recent_w * recent_form(m, pitchers, "pitcher") * len(batters) if recent_w else 0.0
    if g is None:
        return h.sum(1) + adj
    return (1 - ENSEMBLE_W) * h.sum(1) + ENSEMBLE_W * g.sum(1) + adj


def streak_penalty(streak, sit):
    """連續登板疲勞（每打席額外失分值）：使用者設定；資料上估不出顯著影響，預設 0。"""
    if streak >= 2:
        return float(sit.get("fatigue_d3") or 0.0)
    if streak == 1:
        return float(sit.get("fatigue_d2") or 0.0)
    return 0.0


_pool_cache = {}


def _cached(key, fn):
    if key not in _pool_cache:
        if len(_pool_cache) > 500:
            _pool_cache.clear()
        _pool_cache[key] = fn()
    return _pool_cache[key]


def hitter_pool_rels(m, ml, pitcher, phand, recent_w=0.0):
    cutoff = str(m.cutoff.date())
    names = hitter_pool(cutoff)
    if not names:
        return np.array([])
    return _cached((id(m), id(ml), "H", pitcher, recent_w),
                   lambda: ensemble_rel(m, ml, names, [bat_hand(n, phand, cutoff) for n in names], pitcher, recent_w)[0])


def reliever_pool_runs(m, ml, batters, recent_w=0.0):
    names = reliever_pool(str(m.cutoff.date()))
    if not names:
        return np.array([])
    return _cached((id(m), id(ml), "P", tuple(batters), recent_w),
                   lambda: ensemble_runs(m, ml, names, batters, recent_w=recent_w))


def evaluate_pinch_hit(sit, model=None, ml=None, scores=True):
    """ml 為梯度提升樹模擬器（mlmodel.MLModel）；有提供時採用集成：階層式與梯度提升樹各半。

    scores=False 時不計算價值分數（省去全聯盟比較池，供大量回測使用），勝率估計不受影響。
    """
    row = sit["row"]
    m = model or model_at(str(row["date"].date()))
    phand = row["phand"]
    slope = m.run_to_win(row["inning"], row["half"], row["bat_score"], row["fld_score"], row["bases"], row["outs"])
    due = sit["due"]
    due_pos = sit["positions"].get(due, "DH")
    names = [due] + sit["bench"]
    cutoff = str(m.cutoff.date())
    hands = [bat_hand(n, phand, cutoff) for n in names]
    recent_w = float(sit.get("recent_weight") or 0.0)
    rels, rel_h, rel_g = ensemble_rel(m, ml, names, hands, row["pitcher"], recent_w)
    form = recent_form(m, names) if recent_w else np.zeros(len(names))
    pool = hitter_pool_rels(m, ml, row["pitcher"], phand, recent_w) if scores else np.array([])

    out = []
    for i, (name, bh) in enumerate(zip(names, hands)):
        r = m.matchup(name, bh, row["pitcher"])
        rel = float(rels[i])
        rec = dict(
            角色="現任" if name == due else "代打", 球員=name, 打擊=bh,
            價值分數=value_score(rel, pool),
            預估勝率=rel * slope * 100, 誤差=r["se_pa"] * slope * 100,
            每打席得分值=rel, 階層式=r["rel_pa"], 機器學習=(float(rel_g[i]) if ml else None),
            本身能力=r["skill_pa"] - r["fit_pa"], 球路適性=r["fit_pa"], 左右優勢=r["platoon_pa"],
            近況=(float(form[i]) if recent_w else None), 近況權重=recent_w,
            樣本球數=r["n"], 投手對此側樣本=r["mix_n"], 比較池人數=len(pool),
            可守=",".join(positions_of(name, cutoff)) or "-",
        )
        if name != due:
            others = [b for b in sit["bench"] if b != name]
            st, msg = defense_check(due, due_pos, name, others, cutoff)
            rec["守備"], rec["守備說明"] = st, msg
        else:
            rec["守備"], rec["守備說明"] = "ok", f"目前守{POS_ZH.get(due_pos, due_pos)}"
        rec["可信度"] = "高" if r["n"] >= 1500 else "中" if r["n"] >= 500 else "低"
        bhist, phist = _hands(cutoff)
        rec["資料警示"] = "；".join((["打者慣用手缺資料，暫以右打估計"] if name not in bhist.index else []) +
                             (["投手慣用手缺資料，球路基準暫以右投估計"] if row["pitcher"] not in phist.index else []) +
                             (["投手對此侧球路採聯盟回退"] if not r["mix_n"] else []))
        out.append(rec)
    df = pd.DataFrame(out)
    base = df.loc[df["角色"] == "現任", "預估勝率"].iat[0]
    df["相對現任"] = df["預估勝率"] - base
    df = pd.concat([df[df["角色"] == "現任"], df[df["角色"] == "代打"].sort_values("預估勝率", ascending=False)])
    return df.reset_index(drop=True), slope, m


def custom_situation(inning, half, bat_score, fld_score, bases, outs, pitcher, due, due_pos,
                     bench, lineup_positions=None, date="2025-12-31", bat_team=None, fld_team=None,
                     next_batters=None, pen=None, pitch_count=None, starter=None,
                     streaks=None, fatigue_d2=0.0, fatigue_d3=0.0, recent_weight=0.0):
    """由使用者輸入建立情境（不依賴歷史打席）。

    streaks：{投手: 今天之前連續登板天數}；fatigue_d2／fatigue_d3：連投第 2 天／第 3 天以上每打席額外失分值；
    recent_weight：近況權重 0–1。三者皆為使用者設定，預設不影響評估。
    """
    if starter is None:
        starter = is_starter(pitcher, date)
    _, phands = _hands(date)
    row = dict(inning=int(inning), half=half, bat_score=int(bat_score), fld_score=int(fld_score),
               bases=int(bases), outs=int(outs), pitcher=pitcher, phand=phands.get(pitcher, "R"),
               date=pd.Timestamp(date), bat_team=bat_team, fld_team=fld_team, game=None, pa_order=1)
    positions = dict(lineup_positions or {})
    positions[due] = due_pos
    return dict(row=row, lineup={1: due}, due=due, bench=list(bench), positions=positions,
                used_pitchers={pitcher}, next_batters=next_batters or [due], pen=pen,
                pitch_count=None if pitch_count in (None, "") else int(pitch_count), starter=bool(starter),
                streaks=dict(streaks or {}), fatigue_d2=float(fatigue_d2 or 0), fatigue_d3=float(fatigue_d3 or 0),
                recent_weight=min(1.0, max(0.0, float(recent_weight or 0))))


def is_starter(pitcher, cutoff=None):
    """本季先發比例 ≥ 50% 視為先發投手。"""
    boxes = load()[2]
    if cutoff:
        boxes = boxes[boxes["date"] < pd.Timestamp(cutoff)]
    d = boxes[(boxes["role"] == "P") & (boxes["name"] == pitcher) & (boxes["date"].dt.year == 2025)]
    return bool(len(d)) and (d["order"] == 1).mean() >= 0.5


def matchup_detail(model, batter, pitcher):
    """單一對戰的球路格明細：投手使用率、打者揮空偏離、換算得分。"""
    cutoff = str(model.cutoff.date())
    _, phands = _hands(cutoff)
    ph = phands.get(pitcher, "R")
    bh = bat_hand(batter, ph, cutoff)
    r = model.matchup(batter, bh, pitcher)
    cells = []
    for c in r["mix"].index:
        key = (batter, c)
        bc = model.bat_cell.loc[key] if key in model.bat_cell.index else None
        cells.append(dict(cell=c, usage=float(r["mix"][c]), effect=float(r["cell_eff"][c]),
                          whiff_dev=float(bc["whiff"]) if bc is not None else 0.0,
                          n=float(bc["n"]) if bc is not None else 0.0))
    return dict(batter=batter, pitcher=pitcher, bhand=bh, phand=ph, mix_n=r["mix_n"], cells=cells,
                skill=r["skill_pa"] - r["fit_pa"], fit=r["fit_pa"], platoon=r["platoon_pa"], n=r["n"])


def evaluate_bullpen(sit, n_next=3, model=None, ml=None, scores=True):
    """防守方換投：牛棚每位投手對上接下來 n_next 棒。scores=False 時不計算價值分數。"""
    row = sit["row"]
    m = model or model_at(str(row["date"].date()))
    cutoff = str(m.cutoff.date())
    _, phands = _hands(cutoff)
    boxes = load()[2]
    if sit.get("pen") is not None:
        pen = [p for p in sit["pen"] if p != row["pitcher"]]
    else:
        _, pitchers = active_roster(row["fld_team"], row["date"], row["game"])
        pen = [p for p in pitchers if p not in sit["used_pitchers"]]
    if sit.get("next_batters"):
        nxt = list(sit["next_batters"])[:n_next]
    else:
        order = sorted(sit["lineup"])
        start = order.index(row["pa_order"]) if row["pa_order"] in order else 0
        nxt = [sit["lineup"][order[(start + i) % len(order)]] for i in range(n_next)]
        nxt[0] = sit["due"]
    slope = m.run_to_win(row["inning"], row["half"], row["bat_score"], row["fld_score"], row["bases"], row["outs"])

    # 疲勞：前 3 天用球數、連續登板天數
    hist = boxes[(boxes["role"] == "P") & (boxes["date"] < row["date"])]
    out = []
    pc, starter = sit.get("pitch_count"), sit.get("starter", False)
    fat_runs, fat_warn = outlook(pc, starter, len(nxt), cutoff)
    pitchers = [row["pitcher"]] + pen
    matrix = runs_matrix(m, ml, pitchers, nxt)
    recent_w = float(sit.get("recent_weight") or 0.0)
    all_runs = ensemble_runs(m, ml, pitchers, nxt, matrix=matrix, recent_w=recent_w)
    form = recent_form(m, pitchers, "pitcher") if recent_w else np.zeros(len(pitchers))
    pool = reliever_pool_runs(m, ml, nxt, recent_w) if scores else np.array([])
    for k, pit in enumerate(pitchers):
        ph = phands.get(pit, "R")
        runs = float(all_runs[k])
        cur = pit == row["pitcher"]
        h = hist[hist["name"] == pit]
        np3 = int(h.loc[h["date"] >= row["date"] - pd.Timedelta(days=3), "NP"].sum())
        if "streaks" in sit:          # 自訂情境：使用者標記今天之前的連續登板天數
            streak = int(sit["streaks"].get(pit, 0) or 0)
        else:                          # 歷史回放：由出賽紀錄計算
            streak = 0
            d = row["date"] - pd.Timedelta(days=1)
            days = set(h["date"])
            while d in days:
                streak += 1
                d -= pd.Timedelta(days=1)
        pen_pa = streak_penalty(streak, sit)
        extra = (fat_runs if cur else 0.0) + pen_pa * len(nxt)
        h_runs = list(matrix[0][k])
        g_runs = list(matrix[1][k]) if ml else None
        details = [dict(batter=b, runs=((1 - ENSEMBLE_W) * hr + ENSEMBLE_W * float(g_runs[i]) if ml else hr) + recent_w * float(form[k]),
                        fatigue=((outlook(pc, starter, i + 1, cutoff)[0] - outlook(pc, starter, i, cutoff)[0]) if cur else 0.0) + pen_pa)
                   for i, (b, hr) in enumerate(zip(nxt, h_runs))]
        warn = [fat_warn] if cur and fat_warn else []
        if streak >= 2:
            warn.append(f"已連投 {streak} 天")
        if np3 >= 50:
            warn.append(f"前 3 天 {np3} 球")
        out.append(dict(角色="場上" if cur else "牛棚", 投手=pit, 投=ph,
                        價值分數=value_score(runs + extra, pool, higher_better=False),
                        預估失分=runs + extra, 疲勞調整=extra, 用球數=(pc if cur else 0),
                        連投天數=streak, 近況=(float(form[k]) if recent_w else None),
                        樣本球數=int(m.pit_all["n"].get(pit, 0)),
                        階層式=float(sum(h_runs)), 機器學習=float(sum(g_runs)) if ml else None,
                        對決明細=details, 比較池人數=len(pool),
                        資料警示="；".join((["投手慣用手缺資料，暫以右投估計"] if pit not in phands.index else []) +
                                              [f"{b}慣用手缺資料，暫以右打估計" for b in nxt if b not in _hands(cutoff)[0].index]),
                        疲勞="；".join(warn) or "-"))
    df = pd.DataFrame(out)
    cur = df.loc[df["角色"] == "場上", "預估失分"].iat[0]
    df["守方勝率增減"] = -(df["預估失分"] - cur) * slope * 100
    df = pd.concat([df[df["角色"] == "場上"], df[df["角色"] == "牛棚"].sort_values("預估失分")])
    return df.reset_index(drop=True), nxt
