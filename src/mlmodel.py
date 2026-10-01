"""機器學習部分：梯度提升樹逐球結果模型 + 投手歷史球模擬。

實驗（src/experiment.py）結果：「階層式模型 + 梯度提升樹模擬」各半的集成在打席預測與代打一致率都最佳，
因此系統採用集成。本檔負責訓練、存檔與載入梯度提升樹模型。

模型檔存在 models/：
  gbt_full.pkl        全部資料（自訂情境、線上版）
  gbt_YYYY-MM.pkl     月初截止（歷史回放用，只用該月以前的資料）
用法：python mlmodel.py            # 訓練全部模型
"""
import os
import pickle
import sys
import time
from functools import lru_cache

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from load import ROOT, load
from ml_compare import add_velocity, apply_tendencies, features, fit_tendencies, prepare
from model import PITCHES_PER_PA

MODEL_DIR = os.path.join(ROOT, "models")
FULL = "2026-01-01"
REPLAY_MONTHS = [f"2025-{m:02d}-01" for m in range(3, 11)]
SAMPLE = 150          # 每位投手（對該手打者）抽樣的歷史球數
MIN_OWN = 40          # 少於此數改用聯盟同投打組合的球
ENSEMBLE_W = 0.5      # 集成中梯度提升樹的權重
AVG = "__聯盟平均打者__"


def make_gbt():
    return HistGradientBoostingClassifier(max_iter=600, learning_rate=0.05, max_leaf_nodes=31, l2_regularization=1.0,
                                          early_stopping=True, validation_fraction=0.1, random_state=0)


def oof_tendencies(train, k=5):
    fold = train["game"].map(lambda g: int(g.replace("-", "")) % k)
    return pd.concat([apply_tendencies(fit_tendencies(train[fold != i]), train[fold == i]) for i in range(k)]).loc[train.index]


class Simulator:
    """用投手實際投過的歷史球，評估任一打者的預期每打席得分值。"""

    def __init__(self, train, models, tb, velo_tbl, velo_type):
        self.models, self.tb, self.velo_tbl, self.velo_type = models, tb, velo_tbl, velo_type
        rv = train.groupby(["cls", "balls", "strikes"])["rv"].mean()
        self.rv = np.zeros((6, 4, 3))
        for (c, b, s), v in rv.items():
            self.rv[c, b, s] = v
        cols = ["x", "y", "velo", "ptype", "cell", "balls", "strikes", "outs", "bases", "phand", "pitcher", "bhand"]
        self.own = {k: g[cols].sample(min(SAMPLE, len(g)), random_state=0)
                    for k, g in train.groupby(["pitcher", "bhand"]) if len(g) >= MIN_OWN}
        self.lg = {k: g[cols].sample(min(SAMPLE * 2, len(g)), random_state=0) for k, g in train.groupby(["phand", "bhand"])}
        self.phand = train.groupby("pitcher")["phand"].agg(lambda s: s.mode().iat[0])

    def values(self, queries):
        """queries: DataFrame[batter, bhand, pitcher] → {模型名: 每打席預期得分值 array}"""
        parts = []
        for i, (b, bh, p) in enumerate(queries[["batter", "bhand", "pitcher"]].itertuples(index=False)):
            bh = bh if bh in ("L", "R") else "R"
            ph = self.phand.get(p, "R")
            ph = ph if ph in ("L", "R") else "R"
            s = self.own.get((p, bh))
            if s is None:
                s = self.lg[(ph, bh)]
            s = s.copy()
            s["batter"], s["bhand"], s["pitcher"], s["phand"], s["q"] = b, bh, p, ph, i
            parts.append(s)
        sim = pd.concat(parts, ignore_index=True)
        sim["platoon"] = np.where(sim["phand"] == sim["bhand"], "同側", "異側")
        X = features(sim, apply_tendencies(self.tb, sim), self.velo_tbl, self.velo_type)
        rv_rows = self.rv[:, sim["balls"].clip(0, 3).to_numpy(), sim["strikes"].clip(0, 2).to_numpy()].T
        out = {}
        for name, mdl in self.models.items():
            ev = (mdl.predict_proba(X) * rv_rows).sum(1)
            out[name] = pd.Series(ev).groupby(sim["q"]).mean().reindex(range(len(queries))).to_numpy() * PITCHES_PER_PA
        return out


class MLModel:
    """單一截止日的梯度提升樹模擬器，提供「相對聯盟平均打者」與絕對的每打席得分值。"""

    def __init__(self, cutoff, sim, offset):
        self.cutoff, self.sim, self.offset = cutoff, sim, offset
        self._ref = {}

    def abs_many(self, rows):
        """rows: [(batter, bhand, pitcher)] → 每打席預期得分值（已平移到與階層式模型同一水準）。"""
        q = pd.DataFrame(rows, columns=["batter", "bhand", "pitcher"])
        return self.sim.values(q)["gbt"] - self.offset

    def ref(self, pitcher):
        """聯盟平均打者（左右打各半）面對此投手的值；加上校正量，使實際打席的相對值平均為 0。"""
        if pitcher not in self._ref:
            self._ref[pitcher] = float(self.abs_many([(AVG, "L", pitcher), (AVG, "R", pitcher)]).mean())
        return self._ref[pitcher] + getattr(self, "rel_bias", 0.0)

    def calibrate(self, rows):
        """以實際打席（截止日前）校正：「全部傾向為 0」的虛擬打者不完全等於真實打者的平均。"""
        self.rel_bias = 0.0
        vals = self.abs_many(rows)
        self.rel_bias = float(np.mean([v - self.ref(p) for v, (_, _, p) in zip(vals, rows)]))

    def rel_many(self, rows):
        vals = self.abs_many(rows)
        return np.array([v - self.ref(p) for v, (_, _, p) in zip(vals, rows)])


def train(cutoff):
    from model import fit
    t = time.time()
    P = _pitches()
    tr = P[P["date"] < cutoff]
    velo_tbl = tr.groupby(["pitcher", "ptype"])["velo"].mean()
    velo_type = tr.groupby("ptype")["velo"].mean()
    gbt = make_gbt().fit(features(tr, oof_tendencies(tr), velo_tbl, velo_type), tr["cls"].to_numpy())
    sim = Simulator(tr, {"gbt": gbt}, fit_tendencies(tr), velo_tbl, velo_type)
    # 平移量：讓梯度提升樹的整體水準與階層式模型一致（用截止日前最近 2000 個打席估計）
    pa, _, _ = load()
    ref = pa[pa["date"] < cutoff].tail(2000)
    rows = list(ref[["batter", "bhand", "pitcher"]].itertuples(index=False, name=None))
    g = sim.values(pd.DataFrame(rows, columns=["batter", "bhand", "pitcher"]))["gbt"]
    hm = fit(cutoff, season=2025 if cutoff == FULL else None)
    h = np.array([hm.matchup(b, bh, p)["per_pa"] for b, bh, p in rows])
    model = MLModel(cutoff, sim, float(g.mean() - h.mean()))
    model.calibrate(rows)
    print(f"訓練 {cutoff}：{len(tr):,} 球，{time.time() - t:.0f} 秒")
    return model


@lru_cache(maxsize=1)
def _pitches():
    return add_velocity(prepare())


def path_for(cutoff):
    name = "full" if cutoff == FULL else cutoff[:7]
    return os.path.join(MODEL_DIR, f"gbt_{name}.pkl")


class _Unpickler(pickle.Unpickler):
    """直接執行本檔時類別會被記成 __main__.X，載入時改對應到本模組。"""

    def find_class(self, module, name):
        return super().find_class("mlmodel" if module == "__main__" else module, name)


@lru_cache(maxsize=16)
def get(cutoff):
    """載入（不存在則訓練並存檔）指定截止日的模型。"""
    p = path_for(cutoff)
    if os.path.exists(p):
        with open(p, "rb") as f:
            m = _Unpickler(f).load()
        if not hasattr(m, "rel_bias"):  # 舊版存檔：補做校正並重新存檔
            pa, _, _ = load()
            ref = pa[pa["date"] < m.cutoff].tail(2000)
            m.calibrate(list(ref[["batter", "bhand", "pitcher"]].itertuples(index=False, name=None)))
            with open(p, "wb") as f:
                pickle.dump(m, f)
        return m
    m = train(cutoff)
    os.makedirs(MODEL_DIR, exist_ok=True)
    with open(p, "wb") as f:
        pickle.dump(m, f)
    return m


def for_date(date_str):
    """歷史回放：用該日期所屬月份月初截止的模型（時間安全）。"""
    if date_str == FULL:
        return get(FULL)
    month = date_str[:7] + "-01"
    return get(max(REPLAY_MONTHS[0], month))


if __name__ == "__main__":
    import mlmodel  # 以模組身分執行，存檔時類別才會記成 mlmodel.MLModel
    targets = sys.argv[1:] or [FULL] + REPLAY_MONTHS
    for c in targets:
        mlmodel.get(c)
