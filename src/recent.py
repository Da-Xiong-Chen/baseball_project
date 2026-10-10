"""近況：球員近期表現相對其整體能力的偏離（供使用者自行決定權重）。

做法：以時間衰減權重（半衰期 HALF_LIFE 天，不含休季）重新估計打者／投手的每球得分值偏離，
縮減強度沿用模型的 k（近期樣本少時自然縮向 0），再減去不加權的整體估計，得到「近況偏離」。

回測（src/recency_backtest.py）顯示把近期加權直接放進模型，預測下個月並沒有變準，
因此預設權重為 0；使用者可依判斷調高，讓評估更貼近近期狀況。
"""
from functools import lru_cache

import numpy as np
import pandas as pd

from load import pitches_before
from model import PRIOR_SEASON_WEIGHT, _age_days

HALF_LIFE = 30


@lru_cache(maxsize=16)
def deltas(cutoff, k_bat, k_pit):
    """回傳 (打者近況偏離, 投手近況偏離)，單位為每球得分值；正值＝打者近期較好／投手近期較差。"""
    p = pitches_before(cutoff)
    p = p[p["cell"].notna() & p["rv"].notna()]
    season = pd.Timestamp(cutoff).year
    w = np.where(p["season"] < season, PRIOR_SEASON_WEIGHT, 1.0)
    lg = (pd.Series(w * p["rv"].to_numpy()).groupby(pd.MultiIndex.from_frame(p[["platoon", "cell"]])).sum()
          / pd.Series(w).groupby(pd.MultiIndex.from_frame(p[["platoon", "cell"]])).sum())
    r = p["rv"].to_numpy() - lg.reindex(pd.MultiIndex.from_frame(p[["platoon", "cell"]])).to_numpy()
    decay = 0.5 ** (_age_days(p) / HALF_LIFE)
    out = []
    for who, k in (("batter", k_bat), ("pitcher", k_pit)):
        df = pd.DataFrame({"who": p[who].to_numpy(), "r": r, "w": w, "wd": w * decay})
        g = df.assign(wr=df["w"] * df["r"], wdr=df["wd"] * df["r"]).groupby("who")[["wr", "w", "wdr", "wd"]].sum()
        # 近期加權後權重總和較小，用同一個 k 會縮得更多：近期樣本少時保守地接近整體估計
        full = g["wr"] / (g["w"] + k)
        recent = g["wdr"] / (g["wd"] + k)
        out.append((recent - full).rename(None))
    return out[0], out[1]


def for_model(m):
    """以已建立的階層式模型（同一截止日、同一縮減強度）計算近況偏離。"""
    cutoff = str(m.cutoff.date())
    return deltas(cutoff, float(m.k["bat"]), float(m.k["pit"]))
