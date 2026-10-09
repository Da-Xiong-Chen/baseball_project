"""匯出靜態網站（GitHub Pages）所需資料到 docs/data/。

- model.json：全資料模型（自訂情境用），由前端 engine.js 計算
- replay/games.json + replay/<game>.json：2025 年所有代打情境的預先計算結果（只用當天以前的資料）

用法：python export_static.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import _hands, matchup_detail, situation  # noqa: E402
from fatigue import CAP, RELIEVER_WARN, starter_curve  # noqa: E402
from load import CELLS, ROOT, load  # noqa: E402
import mlmodel  # noqa: E402
import recent  # noqa: E402
from model import PITCHES_PER_PA, fit  # noqa: E402
from roster import can_play, hitter_pool, positions_of, reliever_pool  # noqa: E402

sys.path.insert(0, ROOT)
import server  # noqa: E402

OUT = os.path.join(ROOT, "docs", "data")


def rnd(o, d=5):
    if isinstance(o, dict):
        return {str(k): rnd(v, d) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [rnd(v, d) for v in o]
    if hasattr(o, "item"):
        o = o.item()
    if isinstance(o, float):
        return None if (np.isnan(o) or np.isinf(o)) else float(f"{o:.{d + 1}g}")  # 有效位數，保留極小值精度
    return o


def dump(obj, *path):
    p = os.path.join(OUT, *path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf8") as f:
        json.dump(rnd(server.clean(obj)), f, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(p)


def export_model():
    m = fit(server.FULL, season=2025)
    bh, ph = _hands()
    rosters = server.rosters()
    players = sorted({h["name"] for r in rosters.values() for h in r["hitters"]} | set(m.bat_all.index))
    # 依出賽場數排序的可守位置（捕手另可由逐球捕手紀錄判定）
    eligible = {n: list(positions_of(n)) + (["C"] if can_play(n, "C") and "C" not in positions_of(n) else [])
                for n in players}
    eligible = {n: v for n, v in eligible.items() if v}
    # 名單只保留守位清單（不含原始出賽場數）
    for r in rosters.values():
        for h in r["hitters"]:
            h["positions"] = {p: 1 for p in h["positions"]}
    bc = {}
    for (b, c), r in m.bat_cell.iterrows():
        bc.setdefault(b, {})[c] = [r["effect"], r["var"], r["n"], r["whiff"]]
    mix = {}
    for (p, h), r in m.mix.iterrows():
        mix.setdefault(p, {})[h] = [r[c] for c in CELLS] + [float(m.mix_n.get((p, h), 0))]
    model = dict(
        cutoff=str(m.cutoff.date()), cells=CELLS, ppa=PITCHES_PER_PA, training_version=2,
        league={f"{a}|{c}": v for (a, c), v in m.league.items()},
        league_mix={f"{a}|{b}": [r[c] for c in CELLS] for (a, b), r in m.league_mix.iterrows()},
        bat_all={b: [r["effect"], r["var"], r["n"]] for b, r in m.bat_all.iterrows()},
        bat_cell=bc, pit_all={p: [r["effect"], r["n"]] for p, r in m.pit_all.iterrows()},
        mix=mix, k=dict(sigma2=m.k["sigma2"], bat=m.k["bat"]),
        slope_fine={"|".join(map(str, k)): v for k, v in m.slope_fine.items()},
        slope_coarse={"|".join(map(str, k)): v for k, v in m.slope_coarse.items()},
        slope_all=m.slope_all,
        bhand=bh.to_dict(), phand=ph.to_dict(), eligible=eligible,
        fatigue=dict(curve=starter_curve(), cap=CAP, reliever_warn=RELIEVER_WARN),
        rosters=rosters, teams=sorted(rosters),
    )
    # 梯度提升樹模擬：瀏覽器無法執行樹模型，預先算好所有「名單打者 × 名單投手」的每打席得分值
    ml = mlmodel.get(server.FULL)
    hitters = sorted({h["name"] for r in rosters.values() for h in r["hitters"]})
    pitchers = sorted({p["name"] for r in rosters.values() for p in r["pitchers"]})
    grid = {}
    for p in pitchers:
        ph_ = ph.get(p, "R")
        grid[p] = list(ml.abs_many([(h, bh.get(h, "R") if bh.get(h) != "S" else ("L" if ph_ == "R" else "R"), p) for h in hitters]))
    model["pools"] = dict(hitters=hitter_pool(), relievers=reliever_pool())
    model["ml"] = dict(w=mlmodel.ENSEMBLE_W, hitters=hitters, grid=grid, ref={p: ml.ref(p) for p in pitchers})
    # 近況偏離（每球得分值）：使用者可設定權重（預設 0），只匯出名單上的球員
    rb, rp = recent.for_model(m)
    model["recent"] = dict(half_life=recent.HALF_LIFE,
                           bat={n: float(v) for n, v in rb.items() if n in set(hitters)},
                           pit={n: float(v) for n, v in rp.items() if n in set(pitchers)})
    print("model.json", dump(model, "model.json") // 1024, "KB")


def export_replays():
    pa, _, _ = load()
    ph = pa[(pa["season"] == 2025) & pa["is_ph"]].sort_values("date")
    games = {}
    for date, day in ph.groupby("date"):
        m = server.model_for(str(date.date()))
        for _, r in day.iterrows():
            try:
                sit = situation(r["pa_id"])
                actual = dict(batter=r["batter"], is_ph=True, result=r["result"], WPA=r["WPA"])
                res = server.build_result(sit, m, mlmodel.for_date(str(date.date())), actual)
            except Exception as e:
                raise RuntimeError(f"歷史匯出失敗：{r['pa_id']}") from e
            names = [c["球員"] for c in res["candidates"]]
            res["details"] = {f"{n}|{sit['row']['pitcher']}": matchup_detail(m, n, sit["row"]["pitcher"]) for n in names}
            nxt = res["bullpen"]["next"][0]
            for p in [x["投手"] for x in res["bullpen"]["rows"]]:
                res["details"][f"{nxt}|{p}"] = matchup_detail(m, nxt, p)
            games.setdefault(r["game"], {})[r["pa_id"]] = res
        server._models.pop(str(date.date()), None)
        print(date.date(), len(day))

    index = []
    for gid, results in games.items():
        g = pa[pa["game"] == gid]
        g = g.assign(h=g["half"].map({"away": 0, "home": 1})).sort_values(["inning", "h", "seq"])
        cols = ["pa_id", "inning", "half", "outs", "bases", "bat_team", "fld_team", "bat_score", "fld_score",
                "batter", "pitcher", "is_ph", "result", "WPA"]
        dump(dict(pas=g[cols], results=results), "replay", f"{gid}.json")
        aw, hm = g[g["half"] == "away"], g[g["half"] == "home"]
        index.append(dict(game=gid, date=str(g["date"].iat[0].date()),
                          away=aw["bat_team"].iat[0] if len(aw) else hm["fld_team"].iat[0],
                          home=hm["bat_team"].iat[0] if len(hm) else aw["fld_team"].iat[0],
                          away_score=int((aw["bat_score"] + aw["runs"]).max()) if len(aw) else 0,
                          home_score=int((hm["bat_score"] + hm["runs"]).max()) if len(hm) else 0,
                          ph=len(results)))
    print("games.json", dump(sorted(index, key=lambda x: x["date"], reverse=True), "replay", "games.json"), "bytes;", len(index), "games")


if __name__ == "__main__":
    export_model()
    if "--model-only" not in sys.argv:
        export_replays()
