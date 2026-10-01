"""決策引擎：給定一個比賽時點，評估「續打 vs 各代打人選」與「牛棚各投手」。"""
from functools import lru_cache

import pandas as pd

from fatigue import outlook, pitch_count_before
from load import load
from mlmodel import ENSEMBLE_W
from model import fit
import numpy as np

from roster import POS_ZH, active_roster, assign_positions, defense_check, hitter_pool, positions_of, reliever_pool


@lru_cache(maxsize=32)
def model_at(date_str):
    return fit(date_str)


@lru_cache(maxsize=1)
def _hands():
    pa, _, _ = load()
    b = pa.groupby("batter")["bhand"].agg(lambda s: "S" if s.nunique() > 1 and s.value_counts(normalize=True).min() > 0.1 else s.mode().iat[0])
    p = pa.groupby("pitcher")["phand"].agg(lambda s: s.mode().iat[0])
    return b, p


def bat_hand(batter, phand):
    b, _ = _hands()
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
    pos = assign_positions([lineup[k] for k in sorted(lineup)])

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
    beat = (pool < v) if higher_better else (pool > v)
    frac = (beat.sum() + 0.5 * (pool == v).sum()) / len(pool)
    return int(np.clip(round(1 + 99 * frac), 1, 100))


def ensemble_rel(m, ml, names, hands, pitcher):
    """每打席得分值（相對聯盟平均打者）：階層式與梯度提升樹集成。"""
    h = np.array([m.matchup(n, b, pitcher)["rel_pa"] for n, b in zip(names, hands)])
    if not ml:
        return h, h, None
    g = ml.rel_many([(n, b, pitcher) for n, b in zip(names, hands)])
    return (1 - ENSEMBLE_W) * h + ENSEMBLE_W * g, h, g


def ensemble_runs(m, ml, pitchers, batters):
    """每位投手對上 batters 的預期失分合計（集成）。"""
    _, phands = _hands()
    rows = [(b, bat_hand(b, phands.get(p, "R")), p) for p in pitchers for b in batters]
    h = np.array([m.matchup(b, bh, p)["per_pa"] for b, bh, p in rows]).reshape(len(pitchers), len(batters)).sum(1)
    if not ml:
        return h
    g = ml.abs_many(rows).reshape(len(pitchers), len(batters)).sum(1)
    return (1 - ENSEMBLE_W) * h + ENSEMBLE_W * g


_pool_cache = {}


def _cached(key, fn):
    if key not in _pool_cache:
        if len(_pool_cache) > 500:
            _pool_cache.clear()
        _pool_cache[key] = fn()
    return _pool_cache[key]


def hitter_pool_rels(m, ml, pitcher, phand):
    names = hitter_pool()
    return _cached((id(m), id(ml), "H", pitcher),
                   lambda: ensemble_rel(m, ml, names, [bat_hand(n, phand) for n in names], pitcher)[0])


def reliever_pool_runs(m, ml, batters):
    return _cached((id(m), id(ml), "P", tuple(batters)), lambda: ensemble_runs(m, ml, reliever_pool(), batters))


def evaluate_pinch_hit(sit, model=None, ml=None):
    """ml 為梯度提升樹模擬器（mlmodel.MLModel）；有提供時採用集成：階層式與梯度提升樹各半。"""
    row = sit["row"]
    m = model or model_at(str(row["date"].date()))
    phand = row["phand"]
    slope = m.run_to_win(row["inning"], row["half"], row["bat_score"], row["fld_score"], row["bases"], row["outs"])
    due = sit["due"]
    due_pos = sit["positions"].get(due, "DH")
    names = [due] + sit["bench"]
    hands = [bat_hand(n, phand) for n in names]
    rels, rel_h, rel_g = ensemble_rel(m, ml, names, hands, row["pitcher"])
    pool = hitter_pool_rels(m, ml, row["pitcher"], phand)

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
            樣本球數=r["n"], 可守=",".join(positions_of(name)) or "-",
        )
        if name != due:
            others = [b for b in sit["bench"] if b != name]
            st, msg = defense_check(due, due_pos, name, others)
            rec["守備"], rec["守備說明"] = st, msg
        else:
            rec["守備"], rec["守備說明"] = "ok", f"目前守{POS_ZH.get(due_pos, due_pos)}"
        rec["可信度"] = "高" if r["n"] >= 1500 else "中" if r["n"] >= 500 else "低"
        out.append(rec)
    df = pd.DataFrame(out)
    base = df.loc[df["角色"] == "現任", "預估勝率"].iat[0]
    df["相對現任"] = df["預估勝率"] - base
    df = pd.concat([df[df["角色"] == "現任"], df[df["角色"] == "代打"].sort_values("預估勝率", ascending=False)])
    return df.reset_index(drop=True), slope, m


def custom_situation(inning, half, bat_score, fld_score, bases, outs, pitcher, due, due_pos,
                     bench, lineup_positions=None, date="2025-12-31", bat_team=None, fld_team=None,
                     next_batters=None, pen=None, pitch_count=None, starter=None):
    """由使用者輸入建立情境（不依賴歷史打席）。"""
    if starter is None:
        starter = is_starter(pitcher)
    _, phands = _hands()
    row = dict(inning=int(inning), half=half, bat_score=int(bat_score), fld_score=int(fld_score),
               bases=int(bases), outs=int(outs), pitcher=pitcher, phand=phands.get(pitcher, "R"),
               date=pd.Timestamp(date), bat_team=bat_team, fld_team=fld_team, game=None, pa_order=1)
    positions = dict(lineup_positions or {})
    positions[due] = due_pos
    return dict(row=row, lineup={1: due}, due=due, bench=list(bench), positions=positions,
                used_pitchers={pitcher}, next_batters=next_batters or [due], pen=pen,
                pitch_count=None if pitch_count in (None, "") else int(pitch_count), starter=bool(starter))


def is_starter(pitcher):
    """本季先發比例 ≥ 50% 視為先發投手。"""
    boxes = load()[2]
    d = boxes[(boxes["role"] == "P") & (boxes["name"] == pitcher) & (boxes["date"].dt.year == 2025)]
    return bool(len(d)) and (d["order"] == 1).mean() >= 0.5


def matchup_detail(model, batter, pitcher):
    """單一對戰的球路格明細：投手使用率、打者揮空偏離、換算得分。"""
    _, phands = _hands()
    ph = phands.get(pitcher, "R")
    bh = bat_hand(batter, ph)
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


def evaluate_bullpen(sit, n_next=3, model=None, ml=None):
    """防守方換投：牛棚每位投手對上接下來 n_next 棒。"""
    row = sit["row"]
    m = model or model_at(str(row["date"].date()))
    _, phands = _hands()
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
    fat_runs, fat_warn = outlook(pc, starter, len(nxt))
    pitchers = [row["pitcher"]] + pen
    all_runs = ensemble_runs(m, ml, pitchers, nxt)
    pool = reliever_pool_runs(m, ml, nxt)
    for k, pit in enumerate(pitchers):
        ph = phands.get(pit, "R")
        runs = float(all_runs[k])
        cur = pit == row["pitcher"]
        extra = fat_runs if cur else 0.0
        h = hist[hist["name"] == pit]
        np3 = int(h.loc[h["date"] >= row["date"] - pd.Timedelta(days=3), "NP"].sum())
        streak = 0
        d = row["date"] - pd.Timedelta(days=1)
        days = set(h["date"])
        while d in days:
            streak += 1
            d -= pd.Timedelta(days=1)
        warn = [fat_warn] if cur and fat_warn else []
        if streak >= 2:
            warn.append(f"已連投 {streak} 天")
        if np3 >= 50:
            warn.append(f"前 3 天 {np3} 球")
        out.append(dict(角色="場上" if cur else "牛棚", 投手=pit, 投=ph,
                        價值分數=value_score(runs + extra, pool, higher_better=False),
                        預估失分=runs + extra, 疲勞調整=extra, 用球數=(pc if cur else 0),
                        樣本球數=int(m.pit_all["n"].get(pit, 0)),
                        疲勞="；".join(warn) or "-"))
    df = pd.DataFrame(out)
    cur = df.loc[df["角色"] == "場上", "預估失分"].iat[0]
    df["守方勝率增減"] = -(df["預估失分"] - cur) * slope * 100
    df = pd.concat([df[df["角色"] == "場上"], df[df["角色"] == "牛棚"].sort_values("預估失分")])
    return df.reset_index(drop=True), nxt
