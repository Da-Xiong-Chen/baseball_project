"""機器學習演算法比較：預測每顆球的結果（6 類），並換算成每球得分值。

訓練：2024 全季 + 2025/7/1 以前；測試：2025/7/1 以後（時間切分，不偷看未來）。
打者／投手傾向特徵以部分池化估計；訓練列用 5 折（依比賽分折）的 out-of-fold 估計，避免標籤洩漏。

比較：球數基準、現行階層式模型（得分值）、邏輯斯迴歸、隨機森林、梯度提升樹（scikit-learn）、XGBoost、LightGBM、MLP、SVM（抽樣）。
用法：python ml_compare.py
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
from sklearn.svm import SVC

from load import ROOT, load
from model import _mom_k, fit

CUTOFF = "2025-07-01"
CLASSES = ["壞球", "好球（未揮）", "揮空", "界外", "弱擊球", "強勁擊球"]
PTYPES = ["FF", "SI", "FC", "SL", "CU", "CH", "FO"]
SWING = {"SW", "F", "FT", "FOUL_BUNT", "H"}
RNG = np.random.default_rng(0)
OUT = os.path.join(ROOT, "output", "ml_compare.txt")
_lines = []


def log(s=""):
    print(s)
    _lines.append(s)


# ---------------- 資料 ----------------
def prepare():
    _, p, _ = load()
    p = p[p["cell"].notna() & p["x"].notna() & p["y"].notna()].copy()
    code = p["code"]
    p["cls"] = np.select(
        [code == "B", code == "S", code == "SW", code.isin(["F", "FT", "FOUL_BUNT"]),
         (code == "H") & (p["hardness"] == "H"), code == "H"],
        [0, 1, 2, 3, 5, 4], -1)
    p = p[p["cls"] >= 0]                      # 排除觸擊
    p = p.dropna(subset=['batter_id', 'pitcher_id']).copy()
    p['batter_name'], p['pitcher_name'] = p['batter'], p['pitcher']
    p['batter'], p['pitcher'] = p['batter_id'], p['pitcher_id']
    p["swing"] = code.isin(SWING).astype(float)
    return p


def add_velocity(p):
    """逐球球速（load() 未保留，從原始欄位補）。"""
    import glob
    import json
    rows = []
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "rebas", "*", "*.json"))):
        with open(f, encoding="utf8") as source:
            g = json.load(source)
        gid = f"{int(g['date'][:4])}-{g['seq']:03d}"
        for side in ("away", "home"):
            for k, pa in enumerate(g[side + "PAList"]):
                j = 0
                for e in pa["events"]:
                    if e["type"] == "PITCH":
                        try:
                            v = float(e.get("velocity"))
                        except (TypeError, ValueError):   # 人工紀錄偶有 "12+" 之類的錯字
                            v = np.nan
                        if not 80 <= v <= 170:
                            v = np.nan
                        rows.append((f"{gid}-{side[0]}{k:03d}", j, v))
                        j += 1
    v = pd.DataFrame(rows, columns=["pa_id", "j", "velo"])
    return p.merge(v, on=["pa_id", "j"], how="left")


# ---------------- 傾向特徵（部分池化） ----------------
def fit_tendencies(train):
    """以 train 估計打者／投手傾向（部分池化），回傳查表用的 Series。"""
    tb = {}
    for comp in ("whiff", "hard", "swing", "rv"):
        lg = train.groupby(["platoon", "cell"])[comp].mean()
        r = train[comp] - lg.reindex(pd.MultiIndex.from_frame(train[["platoon", "cell"]])).to_numpy()
        s2 = float((r ** 2).mean())
        for who in ("batter", "pitcher"):
            g = r.groupby(train[who]).agg(["sum", "count"])
            k = _mom_k(g["sum"].to_numpy(), g["count"].to_numpy().astype(float), s2)
            eff = g["sum"] / (g["count"] + k)
            tb[f"{who[:3]}_{comp}"] = eff
            if who == "batter" and comp == "whiff":
                r2 = r - train["batter"].map(eff).to_numpy()
                c = r2.groupby([train["batter"], train["cell"]]).agg(["sum", "count"])
                kc = _mom_k(c["sum"].to_numpy(), c["count"].to_numpy().astype(float), s2)
                tb["bat_cell_whiff"] = c["sum"] / (c["count"] + kc)
    return tb


def apply_tendencies(tb, target):
    out = pd.DataFrame(index=target.index)
    for name, eff in tb.items():
        if name == "bat_cell_whiff":
            continue
        who = "batter" if name.startswith("bat") else "pitcher"
        out[name] = target[who].map(eff).fillna(0).to_numpy()
    out["bat_cell_whiff"] = tb["bat_cell_whiff"].reindex(pd.MultiIndex.from_frame(target[["batter", "cell"]])).fillna(0).to_numpy()
    return out


def tendencies(train, target):
    return apply_tendencies(fit_tendencies(train), target)


def oof_tendencies(train, k=5):
    fold = train["game"].map(lambda g: int(g.replace("-", "")) % k)
    parts = [tendencies(train[fold != i], train[fold == i]) for i in range(k)]
    return pd.concat(parts).loc[train.index]


def features(df, tend, velo_tbl, velo_type):
    X = pd.DataFrame(index=df.index)
    X["x"], X["y"] = df["x"], df["y"]
    X["x_rel"] = np.where(df["bhand"] == "L", -df["x"], df["x"])   # 依打者左右翻轉（內外角）
    X["x2"], X["y2"] = df["x"] ** 2, df["y"] ** 2
    X["dist"] = np.sqrt((df["x"] / 63) ** 2 + (df["y"] / 63) ** 2)
    X["in_zone"] = ((df["x"].abs() <= 63) & (df["y"].abs() <= 63)).astype(float)
    v = df["velo"]
    fill = velo_tbl.reindex(pd.MultiIndex.from_arrays([df["pitcher"], df["ptype"]])).to_numpy(dtype=float)
    fill = np.where(np.isnan(fill), df["ptype"].map(velo_type).to_numpy(dtype=float), fill)
    X["velo_missing"] = v.isna().astype(float)
    X["velo"] = np.where(v.isna(), fill, v)
    X["velo"] = X["velo"].fillna(X["velo"].mean())
    for t in PTYPES:
        X[f"pt_{t}"] = (df["ptype"] == t).astype(float)
    X["balls"], X["strikes"] = df["balls"], df["strikes"]
    X["same_side"] = (df["platoon"] == "同側").astype(float)
    X["bhand_L"] = (df["bhand"] == "L").astype(float)
    X["phand_L"] = (df["phand"] == "L").astype(float)
    X["outs"], X["runners"] = df["outs"], (df["bases"] > 0).astype(float)
    return pd.concat([X, tend], axis=1)


GROUPS = {
    "進壘位置": ["x", "y", "x_rel", "x2", "y2", "dist", "in_zone"],
    "球速": ["velo", "velo_missing"],
    "球種": [f"pt_{t}" for t in PTYPES],
    "球數": ["balls", "strikes"],
    "左右投打": ["same_side", "bhand_L", "phand_L"],
    "打者傾向": ["bat_whiff", "bat_hard", "bat_swing", "bat_rv"],
    "打者球路適性": ["bat_cell_whiff"],
    "投手傾向": ["pit_whiff", "pit_hard", "pit_swing", "pit_rv"],
    "局面": ["outs", "runners"],
}


# ---------------- XGBoost / LightGBM ----------------
class EarlyStopped:
    """XGBoost / LightGBM 包裝：與 scikit-learn 梯度提升樹相同，留 10% 訓練資料做 early stopping。"""

    def __init__(self, kind):
        self.kind = kind

    def fit(self, X, y):
        rng = np.random.default_rng(0)
        val = rng.random(len(X)) < 0.1
        Xt, yt, Xv, yv = X[~val], y[~val], X[val], y[val]
        if self.kind == "xgb":
            from xgboost import XGBClassifier
            self.m = XGBClassifier(n_estimators=600, learning_rate=0.05, max_depth=6, min_child_weight=20,
                                   reg_lambda=1.0, subsample=0.8, colsample_bytree=0.8, tree_method="hist",
                                   eval_metric="mlogloss", early_stopping_rounds=30, n_jobs=-1, random_state=0)
            self.m.fit(Xt, yt, eval_set=[(Xv, yv)], verbose=False)
        else:
            import lightgbm as lgb
            self.m = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.05, num_leaves=31, min_child_samples=20,
                                        reg_lambda=1.0, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                                        n_jobs=-1, random_state=0, verbose=-1)
            self.m.fit(Xt, yt, eval_set=[(Xv, yv)], callbacks=[lgb.early_stopping(30, verbose=False)])
        return self

    def predict_proba(self, X):
        return self.m.predict_proba(X)


# ---------------- 評估 ----------------
def logloss(y, P):
    return -np.log(np.clip(P[np.arange(len(y)), y], 1e-6, 1))


def boot_ci(per_row, games, n=1000):
    d = pd.Series(per_row).groupby(games.to_numpy()).agg(["sum", "count"])
    idx = np.arange(len(d))
    vals = [d["sum"].to_numpy()[s].sum() / d["count"].to_numpy()[s].sum() for s in (RNG.choice(idx, len(idx)) for _ in range(n))]
    return np.percentile(vals, [2.5, 97.5])


def main():
    t0 = time.time()
    p = add_velocity(prepare())
    train = p[p["date"] < CUTOFF].copy()
    test = p[p["date"] >= CUTOFF].copy()
    log(f"訓練 {len(train):,} 球（2024 + 2025/7/1 前），測試 {len(test):,} 球（2025/7/1 後）")

    velo_tbl = train.groupby(["pitcher", "ptype"])["velo"].mean()
    velo_type = train.groupby("ptype")["velo"].mean()
    Xtr = features(train, oof_tendencies(train), velo_tbl, velo_type)
    Xte = features(test, tendencies(train, test), velo_tbl, velo_type)
    ytr, yte = train["cls"].to_numpy(), test["cls"].to_numpy()
    log(f"特徵 {Xtr.shape[1]} 個；準備資料 {time.time() - t0:.0f} 秒\n")

    # 每類結果在各球數下的平均得分值（把類別機率換算成預期得分值）
    rv_tbl = train.groupby(["cls", "balls", "strikes"])["rv"].mean()
    rv_mat = np.stack([rv_tbl.reindex(pd.MultiIndex.from_arrays([np.full(len(test), c), test["balls"], test["strikes"]])).fillna(0).to_numpy()
                       for c in range(len(CLASSES))], axis=1)

    results, preds = {}, {}

    def record(name, P, secs):
        ll = logloss(yte, P)
        exp_rv = (P * rv_mat).sum(1)
        results[name] = dict(
            logloss=ll.mean(), acc=(P.argmax(1) == yte).mean(),
            whiff_ll=-np.mean(np.where(yte == 2, np.log(np.clip(P[:, 2], 1e-6, 1)), np.log(np.clip(1 - P[:, 2], 1e-6, 1)))),
            rv_mse=((test["rv"].to_numpy() - exp_rv) ** 2).mean(), secs=secs)
        preds[name] = ll
        log(f"  {name:<12} 完成（{secs:.0f} 秒）")

    # 基準：只看球數
    t = time.time()
    freq = pd.crosstab([train["balls"], train["strikes"]], train["cls"], normalize="index").reindex(columns=range(6), fill_value=0)
    P0 = freq.reindex(pd.MultiIndex.from_arrays([test["balls"], test["strikes"]])).to_numpy()
    record("球數基準", P0, time.time() - t)

    models = {
        "邏輯斯迴歸": make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=1.0)),
        "隨機森林": RandomForestClassifier(n_estimators=300, min_samples_leaf=40, max_features="sqrt", n_jobs=-1, random_state=0),
        "梯度提升樹": HistGradientBoostingClassifier(max_iter=600, learning_rate=0.05, max_leaf_nodes=31, l2_regularization=1.0,
                                                 early_stopping=True, validation_fraction=0.1, random_state=0),
        "XGBoost": EarlyStopped("xgb"),
        "LightGBM": EarlyStopped("lgbm"),
        "MLP 神經網路": make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(64, 32), alpha=1e-3, early_stopping=True,
                                                                  max_iter=200, random_state=0)),
    }
    fitted = {}
    for name, mdl in models.items():
        t = time.time()
        mdl.fit(Xtr, ytr)
        fitted[name] = mdl
        record(name, mdl.predict_proba(Xte), time.time() - t)

    # SVM：訓練量隨資料數平方成長，只能抽樣 10,000 球
    t = time.time()
    sub = RNG.choice(len(Xtr), 10000, replace=False)
    svm = make_pipeline(StandardScaler(), SVC(kernel="rbf", C=1.0, probability=True, random_state=0))
    svm.fit(Xtr.iloc[sub], ytr[sub])
    record("SVM（抽樣1萬）", svm.predict_proba(Xte), time.time() - t)

    # 現行階層式模型：只預測得分值（沒有類別機率）
    m = fit(CUTOFF)
    hier = (m.league.reindex(pd.MultiIndex.from_frame(test[["platoon", "cell"]])).fillna(0).to_numpy()
            + test["batter"].map(m.bat_all["effect"]).fillna(0).to_numpy()
            + m.bat_cell["effect"].reindex(pd.MultiIndex.from_frame(test[["batter", "cell"]])).fillna(0).to_numpy()
            + test["pitcher"].map(m.pit_all["effect"]).fillna(0).to_numpy())
    hier_mse = ((test["rv"].to_numpy() - hier) ** 2).mean()

    # ---------- 報表 ----------
    base = results["球數基準"]
    log("\n=== 每顆球結果預測（測試集；Log Loss、MSE 越低越好）===")
    log(f"{'模型':<14}{'6類LogLoss':>11}{'相對基準':>9}{'準確率':>8}{'揮空LogLoss':>12}{'得分值MSE':>11}{'訓練秒數':>9}")
    for name, r in results.items():
        log(f"{name:<14}{r['logloss']:>11.4f}{100 * (1 - r['logloss'] / base['logloss']):>+8.2f}%{r['acc']:>8.1%}"
            f"{r['whiff_ll']:>12.4f}{r['rv_mse']:>11.5f}{r['secs']:>9.0f}")
    log(f"{'現行階層式模型':<14}{'—':>11}{'':>9}{'—':>8}{'—':>12}{hier_mse:>11.5f}{'':>9}  （只預測得分值，不預測類別）")

    best = min((n for n in results if n != "球數基準"), key=lambda n: results[n]["logloss"])
    log(f"\n最佳：{best}")
    g = test["game"]
    for other in ("球數基準", "邏輯斯迴歸", "隨機森林", "梯度提升樹", "XGBoost", "LightGBM"):
        if other == best:
            continue
        lo, hi = boot_ci(preds[other] - preds[best], g)
        log(f"  {best} 比 {other} 每球 Log Loss 低 {np.mean(preds[other] - preds[best]):.4f}（95% 區間 {lo:.4f} ~ {hi:.4f}，依比賽 bootstrap）")
    exp_best = (fitted[best].predict_proba(Xte) * rv_mat).sum(1) if best in fitted else None
    if exp_best is not None:
        d = (test["rv"].to_numpy() - hier) ** 2 - (test["rv"].to_numpy() - exp_best) ** 2
        lo, hi = boot_ci(d, g)
        log(f"  得分值 MSE：{best} 比現行階層式模型改善 {100 * d.mean() / hier_mse:+.2f}%（95% 區間 {100 * lo / hier_mse:+.2f}% ~ {100 * hi / hier_mse:+.2f}%）")

    # 特徵重要性：分組打亂（permutation），看 Log Loss 增加多少
    if best in fitted:
        log(f"\n=== {best} 特徵重要性（打亂該組特徵後 Log Loss 增加，越大越重要）===")
        idx = RNG.choice(len(Xte), min(20000, len(Xte)), replace=False)
        Xs, ys = Xte.iloc[idx].copy(), yte[idx]
        base_ll = logloss(ys, fitted[best].predict_proba(Xs)).mean()
        imp = {}
        for gname, cols in GROUPS.items():
            vals = []
            for _ in range(3):
                Xp = Xs.copy()
                perm = RNG.permutation(len(Xp))
                Xp[cols] = Xp[cols].to_numpy()[perm]
                vals.append(logloss(ys, fitted[best].predict_proba(Xp)).mean() - base_ll)
            imp[gname] = np.mean(vals)
        top = max(imp.values())
        for gname, v in sorted(imp.items(), key=lambda kv: -kv[1]):
            log(f"  {gname:<8} {v:+.4f}  {'█' * int(round(30 * max(v, 0) / top))}")

    log(f"\n總耗時 {time.time() - t0:.0f} 秒")
    open(OUT, "w", encoding="utf8").write("\n".join(_lines))


if __name__ == "__main__":
    main()
