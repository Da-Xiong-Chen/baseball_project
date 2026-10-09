"""近期加權回測：資料權重隨時間衰減（半衰期），對預測下個月有沒有幫助？

每月初用「當時以前」的資料建模，預測該月（2024/6–9、2025/5–9）：
A. 投手：用 model.fit(pitcher_half_life=H) 的投手整體效果，預測該月每顆球的得分值偏離（相對聯盟同左右、同球路格）
B. 打者：同樣的部分池化估計，改成打者整體效果（模型目前不對打者加權，這裡說明原因）

分數為「相對預測 0（聯盟平均）每萬球降低的平方誤差」，越高越好；並以比賽為單位 bootstrap 檢查差異是否穩定。
用法：python recency_backtest.py
"""
import numpy as np
import pandas as pd

from load import load, pitches_before
from model import PRIOR_SEASON_WEIGHT, _age_days, _mom_k, fit

PERIODS = [("2024-06-01", "2024-07-01"), ("2024-07-01", "2024-08-01"), ("2024-08-01", "2024-09-01"), ("2024-09-01", "2024-10-01"),
           ("2025-05-01", "2025-06-01"), ("2025-06-01", "2025-07-01"), ("2025-07-01", "2025-08-01"), ("2025-08-01", "2025-09-01"),
           ("2025-09-01", "2025-10-01")]
HALF_LIVES = [None, 90, 180, 365]


def month_data(start, end):
    """測試月每顆球：相對訓練期聯盟基準的得分值偏離。"""
    tr = pitches_before(start)
    tr = tr[tr["cell"].notna() & tr["rv"].notna()]
    te = pitches_before(end)
    te = te[(te["date"] >= start) & te["cell"].notna() & te["rv"].notna()]
    w = np.where(tr["season"] < int(start[:4]), PRIOR_SEASON_WEIGHT, 1.0)
    lg = pd.Series(w * tr["rv"].to_numpy()).groupby(pd.MultiIndex.from_frame(tr[["platoon", "cell"]])).sum() / \
        pd.Series(w).groupby(pd.MultiIndex.from_frame(tr[["platoon", "cell"]])).sum()
    base = lg.reindex(pd.MultiIndex.from_frame(te[["platoon", "cell"]])).fillna(0).to_numpy()
    return tr, te.assign(r=te["rv"].to_numpy() - base), lg


def batter_effects(tr, lg, half_life, season):
    w = np.where(tr["season"] < season, PRIOR_SEASON_WEIGHT, 1.0)
    if half_life:
        w = w * 0.5 ** (_age_days(tr) / half_life)
    r = tr["rv"].to_numpy() - lg.reindex(pd.MultiIndex.from_frame(tr[["platoon", "cell"]])).to_numpy()
    s2 = float(np.average(r ** 2, weights=w))
    d = pd.DataFrame({"b": tr["batter"].to_numpy(), "wr": w * r, "w": w, "w2": w * w}).groupby("b").sum()
    k = _mom_k(d["wr"].to_numpy(), d["w"].to_numpy(), s2, d["w2"].to_numpy())
    return d["wr"] / (d["w"] + k)


def gain(te, who, eff):
    pred = eff.reindex(te[who]).fillna(0).to_numpy()
    return te.assign(g=te["r"] ** 2 - (te["r"] - pred) ** 2).groupby("game")["g"].sum()


def main():
    rows = {("投手", h): [] for h in HALF_LIVES} | {("打者", h): [] for h in HALF_LIVES}
    n = 0
    for start, end in PERIODS:
        tr, te, lg = month_data(start, end)
        n += len(te)
        for h in HALF_LIVES:
            m = fit(start, pitcher_half_life=h)
            rows[("投手", h)].append(gain(te, "pitcher", m.pit_all["effect"]))
            rows[("打者", h)].append(gain(te, "batter", batter_effects(tr, lg, h, int(start[:4]))))
        print(f"{start} 完成：{len(te)} 球")
    rng = np.random.default_rng(0)
    for who in ("投手", "打者"):
        print(f"\n=== {who}（每萬球降低的平方誤差，越高越好）===")
        g = {h: pd.concat(rows[(who, h)]) for h in HALF_LIVES}
        games = g[None].index.to_numpy()
        for h in HALF_LIVES:
            line = f"  半衰期 {str(h) + ' 天' if h else '不加權'}：{g[h].sum() / n * 1e4:.3f}"
            if h:
                diff = (g[h] - g[None]).reindex(games).fillna(0)
                boots = [diff.iloc[rng.integers(0, len(games), len(games))].sum() / n * 1e4 for _ in range(2000)]
                line += f"（相對不加權 {diff.sum() / n * 1e4:+.3f}，95% 區間 {np.percentile(boots, 2.5):+.3f} ~ {np.percentile(boots, 97.5):+.3f}）"
            print(line)


if __name__ == "__main__":
    main()
