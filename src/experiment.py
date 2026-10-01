"""完整實驗：比較「打席開始前」評估打者 vs 投手的方法，選出最佳方法放進系統。

方法：
  聯盟平均            不看球員（基準）
  階層式（現行）      部分池化：投手 8 格球路分布 × 打者適性 + 打者/投手能力 + 左右投打
  XX 模擬            逐球結果模型（邏輯斯迴歸／隨機森林／梯度提升樹／MLP）：
                      取投手實際投過的球（位置、球種、球速、球數），換上候選打者預測每球結果，平均成預期得分
  集成               階層式 + 梯度提升樹模擬 各半

評估（2025/5–10，每月月初用「當時以前」的資料重新訓練，預測該月）：
  A. 每個打席的實際得分值（RE24）預測誤差
  B. 2025 年實際代打情境：教練實際選的人在各方法排名第幾

用法：python experiment.py
"""
import os
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from engine import bat_hand, situation
from load import ROOT, load
from ml_compare import add_velocity, features, fit_tendencies, prepare
from mlmodel import Simulator, oof_tendencies as oof
from model import fit

MONTHS = ["2025-05-01", "2025-06-01", "2025-07-01", "2025-08-01", "2025-09-01", "2025-10-01", "2025-11-01"]
RNG = np.random.default_rng(0)
OUT = os.path.join(ROOT, "output", "experiment.txt")
_lines = []


def log(s=""):
    print(s, flush=True)
    _lines.append(s)


def make_models():
    return {
        "邏輯斯迴歸模擬": make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)),
        "隨機森林模擬": RandomForestClassifier(n_estimators=150, min_samples_leaf=40, max_features="sqrt", n_jobs=-1, random_state=0),
        "梯度提升樹模擬": HistGradientBoostingClassifier(max_iter=600, learning_rate=0.05, max_leaf_nodes=31, l2_regularization=1.0,
                                                    early_stopping=True, validation_fraction=0.1, random_state=0),
        "MLP模擬": make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(64, 32), alpha=1e-3, early_stopping=True,
                                                            max_iter=200, random_state=0)),
    }


def main():
    t0 = time.time()
    pa, _, _ = load()
    P = add_velocity(prepare())
    log(f"逐球資料 {len(P):,} 球；準備 {time.time() - t0:.0f} 秒")

    # 2025 年所有代打情境（打席開始前的候選名單）
    ph_rows = []
    for _, r in pa[(pa["season"] == 2025) & pa["is_ph"] & (pa["date"] >= MONTHS[0])].iterrows():
        sit = situation(r["pa_id"])
        if sit["due"] == r["batter"] or r["batter"] not in sit["bench"]:
            continue
        ph_rows.append(dict(pa_id=r["pa_id"], date=r["date"], game=r["game"], pitcher=r["pitcher"], phand=r["phand"],
                            due=sit["due"], bench=sit["bench"], actual=r["batter"]))
    log(f"代打情境 {len(ph_rows)} 個\n")

    A, B = [], []
    for start, end in zip(MONTHS[:-1], MONTHS[1:]):
        tm = time.time()
        train = P[P["date"] < start]
        velo_tbl = train.groupby(["pitcher", "ptype"])["velo"].mean()
        velo_type = train.groupby("ptype")["velo"].mean()
        Xtr = features(train, oof(train), velo_tbl, velo_type)
        models = make_models()
        for mdl in models.values():
            mdl.fit(Xtr, train["cls"].to_numpy())
        sim = Simulator(train, models, fit_tendencies(train), velo_tbl, velo_type)
        hm = fit(start)

        # A. 該月每個打席
        test = pa[(pa["date"] >= start) & (pa["date"] < end)].dropna(subset=["RE24"]).reset_index(drop=True)
        q = test[["batter", "bhand", "pitcher"]]
        vals = sim.values(q)
        vals["階層式（現行）"] = np.array([hm.matchup(b, h, p)["per_pa"] for b, h, p in q.itertuples(index=False)])
        for i, r in test.iterrows():
            A.append(dict(month=start, game=r["game"], y=r["RE24"], **{k: v[i] for k, v in vals.items()}))

        # B. 該月的代打情境
        phs = [x for x in ph_rows if start <= str(x["date"].date()) < end]
        qs, owner = [], []
        for j, x in enumerate(phs):
            for c in [x["due"]] + x["bench"]:
                qs.append(dict(batter=c, bhand=bat_hand(c, x["phand"]), pitcher=x["pitcher"]))
                owner.append((j, c))
        if qs:
            qdf = pd.DataFrame(qs)
            v2 = sim.values(qdf)
            v2["階層式（現行）"] = np.array([hm.matchup(b, h, p)["per_pa"] for b, h, p in qdf.itertuples(index=False)])
            for j, x in enumerate(phs):
                idx = [k for k, (o, _) in enumerate(owner) if o == j]
                names = [owner[k][1] for k in idx]
                B.append(dict(month=start, game=x["game"], n_bench=len(x["bench"]), actual=x["actual"], names=names,
                              **{m: [v2[m][k] for k in idx] for m in v2}))
        log(f"{start}：{len(test)} 打席、{len(phs)} 個代打情境（{time.time() - tm:.0f} 秒）")

    A = pd.DataFrame(A)
    methods = ["階層式（現行）", "邏輯斯迴歸模擬", "隨機森林模擬", "梯度提升樹模擬", "MLP模擬"]
    # 集成：各方法先在月內置中，避免整體水準差異
    for m in methods:
        A[m + "_c"] = A[m] - A.groupby("month")[m].transform("mean")
    A["集成（階層式＋梯度提升樹）_c"] = (A["階層式（現行）_c"] + A["梯度提升樹模擬_c"]) / 2
    methods.append("集成（階層式＋梯度提升樹）")
    A["y_c"] = A["y"] - A.groupby("month")["y"].transform("mean")

    log("\n=== A. 打席得分值預測（2025/5–10，共 {:,} 打席；預測與實際皆在月內置中）===".format(len(A)))
    mse0 = (A["y_c"] ** 2).mean()
    g = A["game"].to_numpy()
    games = np.unique(g)
    gi = {x: i for i, x in enumerate(games)}
    gidx = np.array([gi[x] for x in g])

    def boot(diff, n=1000):
        s = np.bincount(gidx, weights=diff, minlength=len(games))
        c = np.bincount(gidx, minlength=len(games))
        v = [s[k].sum() / c[k].sum() for k in (RNG.integers(0, len(games), len(games)) for _ in range(n))]
        return np.percentile(v, [2.5, 97.5])

    se0 = A["y_c"] ** 2
    hier_se = (A["y_c"] - A["階層式（現行）_c"]) ** 2
    log(f"{'方法':<22}{'相對聯盟平均改善':>14}{'95% 區間':>22}{'相關係數':>10}{'相對現行模型':>14}")
    log(f"{'聯盟平均':<22}{'+0.000%':>14}")
    summaryA = {}
    for m in methods:
        se = (A["y_c"] - A[m + "_c"]) ** 2
        lo, hi = boot((se0 - se).to_numpy())
        lo2, hi2 = boot((hier_se - se).to_numpy())
        imp = 100 * (se0 - se).mean() / mse0
        rel = "—" if m == "階層式（現行）" else f"{100 * (hier_se - se).mean() / mse0:+.3f}%"
        summaryA[m] = dict(imp=imp, ci=(100 * lo / mse0, 100 * hi / mse0), rel_ci=(100 * lo2 / mse0, 100 * hi2 / mse0))
        log(f"{m:<22}{imp:>+13.3f}%{f'{100 * lo / mse0:+.3f}% ~ {100 * hi / mse0:+.3f}%':>22}"
            f"{np.corrcoef(A['y_c'], A[m + '_c'])[0, 1]:>10.4f}{rel:>14}"
            + ("" if m == "階層式（現行）" else f"  ({100 * lo2 / mse0:+.3f}% ~ {100 * hi2 / mse0:+.3f}%)"))

    log(f"\n=== B. 與教練實際代打選擇比較（{len(B)} 個情境）===")
    rand1 = np.mean([1 / x["n_bench"] for x in B])
    rand3 = np.mean([min(3, x["n_bench"]) / x["n_bench"] for x in B])
    log(f"{'方法':<22}{'第1名一致':>10}{'前3名':>10}{'建議換代打比例':>16}")
    log(f"{'隨機挑選':<22}{rand1:>10.1%}{rand3:>10.1%}")
    summaryB = {}
    for m in methods:
        top1 = top3 = recommend = 0
        for x in B:
            if m.startswith("集成"):
                h = np.array(x["階層式（現行）"]); gb = np.array(x["梯度提升樹模擬"])
                v = (h - h.mean()) + (gb - gb.mean())
            else:
                v = np.array(x[m])
            names = x["names"]
            due_v, bench = v[0], v[1:]
            order = [names[1:][k] for k in np.argsort(-bench)]
            rank = order.index(x["actual"]) + 1
            top1 += rank == 1
            top3 += rank <= 3
            recommend += bench.max() > due_v
        summaryB[m] = (top1 / len(B), top3 / len(B))
        log(f"{m:<22}{top1 / len(B):>10.1%}{top3 / len(B):>10.1%}{recommend / len(B):>16.1%}")

    # 綜合判斷：A 的改善（主要）＋ B 的一致率
    best = max(methods, key=lambda m: (summaryA[m]["imp"], summaryB[m][1]))
    log(f"\n綜合最佳：{best}")
    log(f"總耗時 {time.time() - t0:.0f} 秒")
    open(OUT, "w", encoding="utf8").write("\n".join(_lines))
    A.to_csv(os.path.join(ROOT, "output", "experiment_pa.csv"), index=False)


if __name__ == "__main__":
    main()
