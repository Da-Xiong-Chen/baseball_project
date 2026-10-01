"""投手當場用球數的疲勞調整（由資料估計）。

先發投手：以「投手本身平均」為基準，看用球數越多時每球被得分值的變化。
2024–2025 資料顯示 90 球以前大致持平，之後明顯變差（且因倖存者偏差，實際影響可能更大）。
後援投手：30 球以後的樣本太少（約 2,700 球），不做數值調整，只給警示。
"""
from functools import lru_cache

import numpy as np
import pandas as pd

from load import load
from model import PITCHES_PER_PA

ONSET = 85            # 曲線起點（之前視為 0）
RELIEVER_WARN = 30    # 後援超過此球數只警示
CAP = 0.12            # 每打席最多加 0.12 分


@lru_cache(maxsize=1)
def starter_curve():
    """回傳 [(用球數, 每打席額外失分值)]，單調遞增。"""
    _, p, boxes = load()
    p = p.assign(pc=p.groupby(["game", "pitcher"]).cumcount())
    p = p[p["cell"].notna()]
    st = boxes[(boxes["role"] == "P") & (boxes["order"] == 1)][["game", "name"]].rename(columns={"name": "pitcher"})
    p = p.merge(st.assign(sp=True), on=["game", "pitcher"], how="left")
    p = p[p["sp"].eq(True)]
    r = p["rv"] - p.groupby(["platoon", "cell"])["rv"].transform("mean")
    r = r - r.groupby(p["pitcher"]).transform("mean")
    base = r[p["pc"] < 90].mean()
    pts = [(ONSET, 0.0)]
    for lo, hi in ((90, 100), (100, 110)):
        sel = (p["pc"] >= lo) & (p["pc"] < hi)
        if sel.sum() >= 500:
            pen = max(0.0, (r[sel].mean() - base) * PITCHES_PER_PA)
            pts.append(((lo + hi) / 2, max(pen, pts[-1][1])))
    return pts


def penalty(pitch_count, starter):
    """當前用球數下，接下來一個打席的額外失分值（每打席）。"""
    if not starter or pitch_count is None:
        return 0.0
    pts = starter_curve()
    xs, ys = np.array([x for x, _ in pts]), np.array([y for _, y in pts])
    if pitch_count <= xs[-1]:
        return float(np.interp(pitch_count, xs, ys))
    slope = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2]) if len(xs) > 1 else 0.0
    return float(min(CAP, ys[-1] + slope * (pitch_count - xs[-1])))


def outlook(pitch_count, starter, n_batters=3):
    """接下來 n 個打席累計的額外失分值，以及警示文字。"""
    pc = pitch_count or 0
    total = sum(penalty(pc + PITCHES_PER_PA * i, starter) for i in range(n_batters))
    warn = None
    if starter and pc >= 90:
        warn = f"先發 {pc} 球"
    elif not starter and pc >= RELIEVER_WARN:
        warn = f"後援 {pc} 球（資料不足未調整）"
    return total, warn


def pitch_count_before(pa_row):
    """歷史打席開始前，場上投手本場已投球數，以及是否為先發。"""
    pa, p, boxes = load()
    prior = pa[(pa["game"] == pa_row["game"]) & (pa["half"] == pa_row["half"]) & (pa["seq"] < pa_row["seq"])]
    n = int(p[p["pa_id"].isin(prior["pa_id"]) & (p["pitcher"] == pa_row["pitcher"])].shape[0])
    st = boxes[(boxes["game"] == pa_row["game"]) & (boxes["team"] == pa_row["fld_team"]) &
               (boxes["role"] == "P") & (boxes["order"] == 1)]["name"]
    return n, bool((st == pa_row["pitcher"]).any())
