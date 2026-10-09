"""對戰模型：投手球路分布 × 打者對各球路的能力（部分池化），再依局勢換算成勝率。

所有估計只使用 cutoff 日期以前的資料，可用於歷史回放而不偷看未來。
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from load import CELLS, load, pitches_before

PRIOR_SEASON_WEIGHT = 0.6  # 前一季資料的權重
PITCHES_PER_PA = 3.76
# 投手整體效果的近期加權：資料權重每經過 PITCHER_HALF_LIFE 天減半（天數不含休季）；None 為不加權。
# 回測（src/recency_backtest.py，2024/6–9、2025/5–9 共 9 個月）：投手改善很小且 95% 區間含 0，
# 打者持平或變差，因此目前不啟用；之後資料增加可重跑回測再決定。
PITCHER_HALF_LIFE = None


def _mom_k(sum_r, n, sigma2, w2=None):
    """以動差法估計部分池化的縮減強度 k = 噪音變異 / 真實變異。

    n 為加權球數；w2 為權重平方和（加權平均的噪音變異 = sigma2 × Σw² / (Σw)²）。
    """
    w2 = n if w2 is None else w2
    ok = n >= 50
    if ok.sum() < 5:
        return 1e9
    means = sum_r[ok] / n[ok]
    tau2 = np.var(means) - np.mean(sigma2 * w2[ok] / n[ok] ** 2)
    if tau2 <= 0:
        return 1e9
    return sigma2 / tau2


@dataclass
class Model:
    cutoff: pd.Timestamp
    league: pd.Series        # (platoon, cell) → 每球平均得分值
    bat_all: pd.DataFrame    # batter → effect, var, n
    bat_cell: pd.DataFrame   # (batter, cell) → effect, var, n
    pit_all: pd.DataFrame    # pitcher → effect, var, n
    mix: pd.DataFrame        # (pitcher, bhand) → 各 cell 機率
    mix_n: pd.Series         # (pitcher, bhand) → 樣本球數
    league_mix: pd.DataFrame # (phand, bhand) → 各 cell 機率
    phand: pd.Series         # pitcher → R/L
    k: dict
    slope_fine: pd.Series
    slope_coarse: pd.Series
    slope_all: float

    # ---------- 對戰 ----------
    def _lookup(self):
        """matchup 用的查詢表（第一次呼叫時建立）。只是把 pandas 逐筆查詢換成字典，數值完全相同。"""
        c = self.__dict__.get("_lookup_cache")
        if c is None:
            idx = {cell: i for i, cell in enumerate(CELLS)}
            bat_cell = {}
            for (b, cell), eff, var in zip(self.bat_cell.index, self.bat_cell["effect"].to_numpy(), self.bat_cell["var"].to_numpy()):
                if cell in idx:
                    e, v = bat_cell.setdefault(b, (np.zeros(len(CELLS)), np.zeros(len(CELLS))))
                    e[idx[cell]], v[idx[cell]] = eff, var
            mix_arr = self.mix.reindex(columns=CELLS).fillna(0).to_numpy()
            c = dict(
                league={pl: self.league.loc[pl].reindex(CELLS).fillna(0).to_numpy()
                        for pl in self.league.index.get_level_values(0).unique()},
                neutral=self.league.groupby(level=1).mean().reindex(CELLS).fillna(0).to_numpy(),
                bat_all={b: (e, v, int(n)) for b, e, v, n in zip(self.bat_all.index, self.bat_all["effect"].to_numpy(),
                                                                  self.bat_all["var"].to_numpy(), self.bat_all["n"].to_numpy())},
                bat_cell=bat_cell,
                pit=self.pit_all["effect"].to_dict(),
                mix={k: mix_arr[i] for i, k in enumerate(self.mix.index)},
                mix_n={k: int(v) for k, v in self.mix_n.items()},
                league_mix={k: self.league_mix.loc[k].reindex(CELLS).fillna(0).to_numpy() for k in self.league_mix.index},
                phand=self.phand.to_dict(),
            )
            self.__dict__["_lookup_cache"] = c
        return c

    def pitch_mix(self, pitcher, bhand):
        bhand = bhand if bhand in ("L", "R") else "R"
        if (pitcher, bhand) in self.mix.index:
            return self.mix.loc[(pitcher, bhand)], int(self.mix_n.get((pitcher, bhand), 0))
        ph = self.phand.get(pitcher, "R")
        return self.league_mix.loc[(ph, bhand)], 0

    def matchup(self, batter, bhand, pitcher):
        """回傳 (每打席預期得分值，相對聯盟平均打者)、標準誤、打者總樣本球數、投手樣本。"""
        L = self._lookup()
        bhand = bhand if bhand in ("L", "R") else "R"
        if (pitcher, bhand) in L["mix"]:
            m, mix_n = L["mix"][(pitcher, bhand)].copy(), L["mix_n"].get((pitcher, bhand), 0)
        else:
            m, mix_n = L["league_mix"][(L["phand"].get(pitcher, "R"), bhand)].copy(), 0
        ph = L["phand"].get(pitcher, "R")
        ph = ph if ph in ("L", "R") else "R"
        platoon = "同側" if ph == bhand else "異側"
        lg_base = float((m * L["league"][platoon]).sum())

        a = L["bat_all"].get(batter)
        a_eff, a_var, n = a if a is not None else (0.0, self.k["sigma2"] / self.k["bat"], 0)
        bc = L["bat_cell"].get(batter)
        cell_eff, cell_var = (bc[0].copy(), bc[1].copy()) if bc is not None else (np.zeros(len(CELLS)), np.zeros(len(CELLS)))
        q = float(L["pit"].get(pitcher, 0.0))

        skill = a_eff + float((m * cell_eff).sum())          # 打者本身（含對這種球路的適性）
        platoon = lg_base - float((m * L["neutral"]).sum())    # 左右投打的優劣勢
        se = np.sqrt(a_var + (m ** 2 * cell_var).sum())
        f = PITCHES_PER_PA
        return dict(
            per_pa=(lg_base + skill + q) * f,                  # 預期每打席得分值（絕對）
            rel_pa=(skill + platoon) * f,                      # 相對聯盟平均打者（同一投手）
            skill_pa=skill * f, fit_pa=float((m * cell_eff).sum()) * f, platoon_pa=platoon * f,
            se_pa=se * f, n=n, mix_n=mix_n, mix=pd.Series(m, CELLS), cell_eff=pd.Series(cell_eff, CELLS),
            pitcher_q=q * f,
        )

    def _neutral_base(self, m):
        lg = self.league.groupby(level=1).mean().reindex(CELLS).fillna(0).to_numpy()
        return float((m * lg).sum())

    # ---------- 局勢 ----------
    def run_to_win(self, inning, half, bat_score, fld_score, bases, outs):
        key = _state_key(inning, half, bat_score - fld_score, bases, outs)
        if key in self.slope_fine.index:
            return float(self.slope_fine[key])
        ck = key[:3]
        return float(self.slope_coarse.get(ck, self.slope_all))


def _state_key(inning, half, diff, bases, outs):
    inn = min(max(inning, 1), 9)
    inn_b = "1-3" if inn <= 3 else "4-6" if inn <= 6 else str(inn)
    return (inn_b, half, int(np.clip(diff, -4, 4)), int(bases), int(outs))


def _age_days(p):
    """每顆球距離最後一筆資料的天數，扣掉球季之間的休季天數。"""
    age = (p["date"].max() - p["date"]).dt.days.to_numpy().astype(float)
    b = p.groupby("season")["date"].agg(["min", "max"]).sort_index()
    gap = ((b["min"].shift(-1) - b["max"]).dt.days - 1).fillna(0).clip(lower=0)
    offset = gap[::-1].cumsum()[::-1]   # 該季之後所有休季天數合計
    return age - p["season"].map(offset).to_numpy()


def fit(cutoff, season=None, pitcher_half_life=PITCHER_HALF_LIFE):
    """以 cutoff 之前的資料建模。season 為 cutoff 所屬球季（前一季資料降權）。

    pitcher_half_life：投手整體效果的近期加權半衰期（天，不含休季）；None 表示不加權。
    """
    cutoff = pd.Timestamp(cutoff)
    season = season or cutoff.year
    pa, _, _ = load()
    p = pitches_before(str(cutoff.date()))
    p = p[p["cell"].notna() & p["rv"].notna()].copy()
    p["w"] = np.where(p["season"] < season, PRIOR_SEASON_WEIGHT, 1.0)
    pa_ = pa[pa["date"] < cutoff].copy()

    # 聯盟基準：左右打組合 × 球路格
    g = p.groupby(["platoon", "cell"])
    league = (g[["rv", "w"]].apply(lambda d: np.average(d["rv"], weights=d["w"]))).rename("rv")
    p["resid"] = p["rv"] - league.reindex(pd.MultiIndex.from_frame(p[["platoon", "cell"]])).to_numpy()
    sigma2 = float(np.average(p["resid"] ** 2, weights=p["w"]))

    # 打者整體效果（部分池化）
    p["wr"] = p["w"] * p["resid"]
    p["w2"] = p["w"] ** 2
    ba = p.groupby("batter").agg(sr=("wr", "sum"), n=("w", "sum"), w2=("w2", "sum"))
    k_bat = _mom_k(ba["sr"].to_numpy(), ba["n"].to_numpy(), sigma2, ba["w2"].to_numpy())
    ba["effect"] = ba["sr"] / (ba["n"] + k_bat)
    ba["var"] = sigma2 / (ba["n"] + k_bat)

    # 打者 × 球路格的適性：逐球得分值太吵、偵測不到（k 趨近無限大），
    # 改用穩定得快的兩個成分——揮空率、強勁擊球率——相對打者自身平均的偏離，再換算成得分。
    other = (p["whiff"] == 0) & (p["hard"] == 0)
    rv_other = np.average(p.loc[other, "rv"], weights=p.loc[other, "w"])
    to_runs = {
        "whiff": np.average(p.loc[p["whiff"] == 1, "rv"], weights=p.loc[p["whiff"] == 1, "w"]) - rv_other,
        "hard": np.average(p.loc[p["hard"] == 1, "rv"], weights=p.loc[p["hard"] == 1, "w"]) - rv_other,
    }
    bc = None
    k_comp = {}
    for comp, runs in to_runs.items():
        r = p[comp] - p.groupby(["platoon", "cell"])[comp].transform(lambda s: np.average(s, weights=p.loc[s.index, "w"]))
        s2 = float(np.average(r ** 2, weights=p["w"]))
        tmp = pd.DataFrame({"batter": p["batter"], "cell": p["cell"], "wr": p["w"] * r, "w": p["w"], "w2": p["w2"]})
        b = tmp.groupby("batter").agg(sr=("wr", "sum"), n=("w", "sum"), w2=("w2", "sum"))
        kb = _mom_k(b["sr"].to_numpy(), b["n"].to_numpy(), s2, b["w2"].to_numpy())
        tmp["wr"] = tmp["w"] * (r - (b["sr"] / (b["n"] + kb)).reindex(tmp["batter"]).to_numpy())
        c = tmp.groupby(["batter", "cell"]).agg(sr=("wr", "sum"), n=("w", "sum"), w2=("w2", "sum"))
        kc = _mom_k(c["sr"].to_numpy(), c["n"].to_numpy(), s2, c["w2"].to_numpy())
        k_comp[comp] = kc
        eff = c["sr"] / (c["n"] + kc) * runs
        var = s2 / (c["n"] + kc) * runs ** 2
        if bc is None:
            bc = pd.DataFrame({"effect": eff, "var": var, "n": c["n"]})
        else:
            bc["effect"] += eff
            bc["var"] += var
        bc[comp] = c["sr"] / (c["n"] + kc)  # 揮空率／強勁擊球率的偏離（比例）
    k_cell = k_comp

    # 投手整體效果（失分傾向），近期資料權重較高
    wp = p["w"] * (0.5 ** (_age_days(p) / pitcher_half_life) if pitcher_half_life else 1.0)
    tmp = pd.DataFrame({"pitcher": p["pitcher"], "wr": wp * p["resid"], "w": wp, "w2": wp ** 2})
    pp = tmp.groupby("pitcher").agg(sr=("wr", "sum"), n_eff=("w", "sum"), w2=("w2", "sum"))
    k_pit = _mom_k(pp["sr"].to_numpy(), pp["n_eff"].to_numpy(), sigma2, pp["w2"].to_numpy())
    pp["effect"] = pp["sr"] / (pp["n_eff"] + k_pit)
    pp["var"] = sigma2 / (pp["n_eff"] + k_pit)
    pp["n"] = p.groupby("pitcher")["w"].sum()  # 樣本球數（顯示用），與加權前定義相同

    # 投手球路分布：投手對該左右打 → 投手整體 → 聯盟（同投打慣用手）
    league_mix = pd.crosstab([p["phand"], p["bhand"]], p["cell"], values=p["w"], aggfunc="sum", normalize="index").reindex(columns=CELLS, fill_value=0)
    cnt_h = pd.crosstab([p["pitcher"], p["bhand"]], p["cell"], values=p["w"], aggfunc="sum").reindex(columns=CELLS).fillna(0)
    cnt_a = cnt_h.groupby(level=0).sum()
    phand = p.groupby("pitcher")["phand"].agg(lambda s: s.mode().iat[0])
    rows = {}
    for (pit, bh), row in cnt_h.iterrows():
        lg = league_mix.loc[(phand[pit], bh)]
        a = cnt_a.loc[pit]
        prior_all = (a + 20 * lg) / (a.sum() + 20)
        rows[(pit, bh)] = (row + 50 * prior_all) / (row.sum() + 50)
    mix = pd.DataFrame(rows).T
    mix.index.names = ["pitcher", "bhand"]
    mix_n = cnt_h.sum(axis=1)

    # 得分 → 勝率換算斜率（WPA ≈ slope × RE24），細分局勢往粗分局勢縮減
    d = pa_.dropna(subset=["WPA", "RE24"]).copy()
    d["key"] = [_state_key(*r) for r in zip(d["inning"], d["half"], d["bat_score"] - d["fld_score"], d["bases"], d["outs"])]
    d["xy"], d["xx"] = d["WPA"] * d["RE24"], d["RE24"] ** 2
    slope_all = d["xy"].sum() / d["xx"].sum()
    d["ck"] = d["key"].map(lambda k: k[:3])
    coarse = d.groupby("ck")[["xy", "xx"]].sum()
    slope_coarse = (coarse["xy"] + 5 * slope_all) / (coarse["xx"] + 5)
    fine = d.groupby("key")[["xy", "xx"]].sum()
    prior = slope_coarse.reindex([k[:3] for k in fine.index]).fillna(slope_all).to_numpy()
    slope_fine = pd.Series((fine["xy"].to_numpy() + 3 * prior) / (fine["xx"].to_numpy() + 3), index=fine.index)

    return Model(cutoff, league, ba, bc, pp, mix, mix_n, league_mix, phand,
                 dict(sigma2=sigma2, bat=k_bat, cell=k_cell, pit=k_pit),
                 slope_fine, slope_coarse, slope_all)
