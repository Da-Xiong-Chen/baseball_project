"""時間序回測：每月初用「當時以前」的資料重新建模，預測該月每個打席 / 每顆球。

A. 打席得分值：比較
   B0 聯盟平均（常數）
   B1 打者原始平均（不池化）
   B2 打者 + 投手整體（部分池化，不含球路適性）
   B3 完整模型（B2 + 投手球路分布 × 打者球路適性 + 左右投打）
B. 揮空預測（直接檢驗「球路適性」）：每顆球的揮空機率
   W0 聯盟（左右 × 球路格）  W1 + 打者整體揮空傾向  W2 + 打者 × 球路格（部分池化）
"""
import numpy as np
import pandas as pd

from engine import bat_hand
from load import load
from model import PITCHES_PER_PA, _mom_k, fit

MONTHS = ["2025-06-01", "2025-07-01", "2025-08-01", "2025-09-01", "2025-10-01"]


def whiff_model(p_train):
    r = p_train["whiff"] - p_train.groupby(["platoon", "cell"])["whiff"].transform("mean")
    lg = p_train.groupby(["platoon", "cell"])["whiff"].mean()
    s2 = float((r ** 2).mean())
    b = r.groupby(p_train["batter"]).agg(["sum", "count"])
    kb = _mom_k(b["sum"].to_numpy(), b["count"].to_numpy(), s2)
    be = b["sum"] / (b["count"] + kb)
    r2 = r - be.reindex(p_train["batter"]).to_numpy()
    c = r2.groupby([p_train["batter"], p_train["cell"]]).agg(["sum", "count"])
    kc = _mom_k(c["sum"].to_numpy(), c["count"].to_numpy(), s2)
    ce = c["sum"] / (c["count"] + kc)
    return lg, be, ce


def logloss(y, q):
    q = np.clip(q, 1e-4, 1 - 1e-4)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


def main():
    pa, p, _ = load()
    p = p[p["cell"].notna()]
    resA, resB = [], []
    for start, end in zip(MONTHS[:-1], MONTHS[1:]):
        m = fit(start)
        test = pa[(pa["date"] >= start) & (pa["date"] < end)].dropna(subset=["RE24"])
        train_pa = pa[pa["date"] < start]
        raw = train_pa.groupby("batter")["RE24"].mean()
        lg_mean = train_pa["RE24"].mean()
        for _, r in test.iterrows():
            mu = m.matchup(r["batter"], r["bhand"], r["pitcher"])
            resA.append(dict(game=r["game"], y=r["RE24"], B0=lg_mean,
                             B1=raw.get(r["batter"], lg_mean),
                             B2=lg_mean + (mu["skill_pa"] - mu["fit_pa"]) + mu["pitcher_q"],
                             B3=lg_mean + mu["platoon_pa"] + mu["skill_pa"] + mu["pitcher_q"]))
        # 揮空
        tr = p[p["date"] < start]
        te = p[(p["date"] >= start) & (p["date"] < end)]
        lg, be, ce = whiff_model(tr)
        w0 = lg.reindex(pd.MultiIndex.from_frame(te[["platoon", "cell"]])).to_numpy()
        w1 = w0 + be.reindex(te["batter"]).fillna(0).to_numpy()
        w2 = w1 + ce.reindex(pd.MultiIndex.from_frame(te[["batter", "cell"]])).fillna(0).to_numpy()
        resB.append(pd.DataFrame(dict(game=te["game"].to_numpy(), y=te["whiff"].to_numpy(), W0=w0, W1=w1, W2=w2)))
        print(f"{start} 完成：{len(test)} 打席、{len(te)} 球")

    A = pd.DataFrame(resA)
    B = pd.concat(resB)
    print("\n=== A. 打席得分值（2025/6–9 每月滾動，越低越好）===")
    mse0 = ((A["y"] - A["B0"]) ** 2).mean()
    for k, lab in [("B0", "聯盟平均"), ("B1", "打者原始平均（不池化）"), ("B2", "打者+投手（部分池化）"), ("B3", "完整模型（+球路適性+左右）")]:
        mse = ((A["y"] - A[k]) ** 2).mean()
        print(f"  {lab:<22} MSE={mse:.5f}  相對聯盟平均改善 {100 * (1 - mse / mse0):+.3f}%")
    # 以比賽為群集的 bootstrap：B3 相對 B0
    games = A["game"].unique()
    rng = np.random.default_rng(0)
    g = A.assign(d0=(A["y"] - A["B0"]) ** 2, d3=(A["y"] - A["B3"]) ** 2, d2=(A["y"] - A["B2"]) ** 2).groupby("game")[["d0", "d2", "d3"]].sum()
    boots = []
    for _ in range(2000):
        s = g.loc[rng.choice(games, len(games))].sum()
        boots.append((100 * (1 - s["d3"] / s["d0"]), 100 * (1 - s["d3"] / s["d2"])))
    boots = np.array(boots)
    print(f"  完整模型 vs 聯盟平均 改善 95% 區間：{np.percentile(boots[:, 0], 2.5):+.3f}% ~ {np.percentile(boots[:, 0], 97.5):+.3f}%")
    print(f"  完整模型 vs B2       改善 95% 區間：{np.percentile(boots[:, 1], 2.5):+.3f}% ~ {np.percentile(boots[:, 1], 97.5):+.3f}%")
    print(f"  預測與實際的相關係數：B2 {A['y'].corr(A['B2']):.4f}  B3 {A['y'].corr(A['B3']):.4f}")

    print("\n=== B. 每顆球揮空機率（Log Loss，越低越好）===")
    for k, lab in [("W0", "聯盟（左右×球路）"), ("W1", "+ 打者整體揮空傾向"), ("W2", "+ 打者×球路適性")]:
        print(f"  {lab:<20} {logloss(B['y'].to_numpy(), B[k].to_numpy()):.5f}")
    gb = B.assign(l1=-(B["y"] * np.log(B["W1"].clip(1e-4)) + (1 - B["y"]) * np.log((1 - B["W1"]).clip(1e-4))),
                  l2=-(B["y"] * np.log(B["W2"].clip(1e-4)) + (1 - B["y"]) * np.log((1 - B["W2"]).clip(1e-4)))).groupby("game")[["l1", "l2"]].sum()
    gs = gb.index.to_numpy()
    imp = []
    for _ in range(2000):
        s = gb.loc[rng.choice(gs, len(gs))].sum()
        imp.append(100 * (1 - s["l2"] / s["l1"]))
    print(f"  球路適性帶來的改善：{100 * (1 - gb['l2'].sum() / gb['l1'].sum()):+.3f}%（95% 區間 {np.percentile(imp, 2.5):+.3f}% ~ {np.percentile(imp, 97.5):+.3f}%）")
    A.to_csv("../output/backtest_pa.csv", index=False)


if __name__ == "__main__":
    main()
