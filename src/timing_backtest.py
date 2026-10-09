"""換人時機回測：用歷史資料模擬「系統在每個打席前會不會建議換人」，並與實際比對。

2025 例行賽 6 局以後的每個打席，在打席開始前：
- 換投（防守方）：上一打席的投手續投 vs 推估可用牛棚，對上接下來 3 棒
- 代打（進攻方）：輪到的打者 vs 推估板凳
算法與網站「歷史回放」相同（集成模型＋用球數疲勞）：階層式模型用比賽當天以前的資料，
梯度提升樹用當月月初截止的版本，不偷看未來。
最佳候選的勝率換算差值 ≥ THRESHOLD 百分點，視為「系統建議換人」。

驗證：系統建議換、但實際沒換時，留在場上的人實際表現是否比系統不建議時差（用該打席 RE24）。

輸出：
  output/timing_backtest.csv   每個打席的模擬結果
  docs/data/timing-2025.json   網站回放用的標記與總覽
用法：python timing_backtest.py [平行程序數，預設 4]
      python timing_backtest.py --from-csv     # 由 output/timing_backtest.csv 重建 JSON
"""
import json
import os
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

from engine import evaluate_bullpen, evaluate_pinch_hit, model_at, situation
from fatigue import pitch_count_before
from load import ROOT, load
import mlmodel

MIN_INNING = 6
THRESHOLD = 1.0          # 百分點；網站標記與總覽使用
THRESHOLDS = [0.5, 1.0, 2.0]
SEASON = 2025
CHUNK = 300              # 每個平行工作的打席數


def decision_points():
    """每個打席前的決策點；inc 為上一打席（同場、同防守隊）的投手，即「若不換投會續投的人」。"""
    pa, _, _ = load()
    d = pa[pa["season"] == SEASON].copy()
    d["h"] = d["half"].map({"away": 0, "home": 1})
    d = d.sort_values(["game", "inning", "h", "seq"])
    g = d.groupby(["game", "fld_team"])
    d["inc"], d["inc_hand"] = g["pitcher"].shift(), g["phand"].shift()
    return d[(d["inning"] >= MIN_INNING) & d["inc"].notna()]


def incumbent_situation(sit, r):
    """把情境的場上投手換回上一打席的投手（實際在此打席換投時）。"""
    if r["inc"] == sit["row"]["pitcher"]:
        return sit
    row = sit["row"].copy()
    row["pitcher"], row["phand"] = r["inc"], r["inc_hand"]
    pc, starter = pitch_count_before(row)
    used = (set(sit["used_pitchers"]) - {sit["row"]["pitcher"]}) | {r["inc"]}
    return dict(sit, row=row, used_pitchers=used, pitch_count=pc, starter=starter)


def evaluate(r, m, ml):
    sit = situation(r["pa_id"])
    out = dict(pa_id=r["pa_id"], game=r["game"], date=str(r["date"].date()), inning=int(r["inning"]), half=r["half"],
               bat_team=r["bat_team"], fld_team=r["fld_team"], inc=r["inc"], pitcher=r["pitcher"],
               due=sit["due"], batter=r["batter"], is_ph=bool(r["is_ph"]), pen_change=bool(r["pitcher"] != r["inc"]),
               RE24=float(r["RE24"]) if pd.notna(r["RE24"]) else None)
    ph, _, _ = evaluate_pinch_hit(sit, model=m, ml=ml, scores=False)
    bench = ph[ph["角色"] == "代打"]
    out["ph_gain"] = float(bench["相對現任"].max()) if len(bench) else None
    out["ph_best"] = bench["球員"].iat[0] if len(bench) else None
    bp, _ = evaluate_bullpen(incumbent_situation(sit, r), model=m, ml=ml, scores=False)
    pen = bp[bp["角色"] == "牛棚"]
    # 與回放頁相同取「預估失分最低」者；大比分時換算斜率可能為負，此時不等於差值最大者
    out["pen_gain"] = float(pen["守方勝率增減"].iat[0]) if len(pen) else None
    out["pen_best"] = pen["投手"].iat[0] if len(pen) else None
    out["inc_pc"] = bp["用球數"].iat[0]
    return out


_ml = {}


def run_month(args):
    """與網站回放相同：階層式模型用比賽當天截止（model_at），梯度提升樹用當月月初截止（for_date）。"""
    month, rows = args
    res = []
    for r in rows:
        day = str(r["date"].date())
        if month not in _ml:
            _ml[month] = mlmodel.for_date(day)
        try:
            res.append(evaluate(r, model_at(day), _ml[month]))
        except Exception as e:  # 少數情境無法重建（例如名單推估不到），略過並記錄
            res.append(dict(pa_id=r["pa_id"], error=f"{type(e).__name__}: {e}"))
    return res


def month_of(date):
    return max(mlmodel.REPLAY_MONTHS[0], str(date.date())[:7] + "-01")


def summarize(d, t):
    """d：成功評估的打席；t：建議門檻（百分點）。"""
    s = {}
    for kind, gain, actual in (("pen", "pen_gain", "pen_change"), ("ph", "ph_gain", "is_ph")):
        x = d.dropna(subset=[gain])
        sug, act = x[gain] >= t, x[actual]
        stay = x[~act & x["RE24"].notna()]
        # 留在場上的人該打席的 RE24：換投看防守方失分（越高越差），代打看進攻方得分（越低越差）
        re_sug, re_not = stay.loc[stay[gain] >= t, "RE24"], stay.loc[stay[gain] < t, "RE24"]
        diff = ci = None
        if len(re_sug) > 1 and len(re_not) > 1:
            diff = float(re_sug.mean() - re_not.mean())
            se = float(np.sqrt(re_sug.var() / len(re_sug) + re_not.var() / len(re_not)))
            ci = [round(diff - 1.96 * se, 3), round(diff + 1.96 * se, 3)]
        s[kind] = dict(stay_diff=None if diff is None else round(diff, 3), stay_diff_ci=ci,n=int(len(x)), actual=int(act.sum()), suggested=int(sug.sum()),
                       both=int((sug & act).sum()), sys_only=int((sug & ~act).sum()), actual_only=int((~sug & act).sum()),
                       stay_re24_suggested=round(float(re_sug.mean()), 3) if len(re_sug) else None, stay_n_suggested=int(len(re_sug)),
                       stay_re24_not=round(float(re_not.mean()), 3) if len(re_not) else None, stay_n_not=int(len(re_not)))
    return s


def timing_summary(timing):
    early = [k for k in timing if k is not None]
    return dict(changes=len(timing), system_never=sum(k is None for k in timing), same=sum(k == 0 for k in early),
                earlier=sum(k > 0 for k in early),
                earlier_median=float(np.median([k for k in early if k > 0])) if any(k > 0 for k in early) else None)


def pen_timing(d, t):
    """每次實際換投：系統在這位投手本段登板中，最早在幾個打席前就建議換。"""
    out = []
    for (game, team), g in d.dropna(subset=["pen_gain"]).groupby(["game", "fld_team"], sort=False):
        stint = []
        for _, r in g.iterrows():
            if r["pen_change"]:
                first = next((i for i, x in enumerate(stint) if x >= t), None)
                out.append(None if first is None and r["pen_gain"] < t else 0 if first is None else len(stint) - first)
                stint = []
            else:
                stint.append(r["pen_gain"])
    return out


CSV = os.path.join(ROOT, "output", "timing_backtest.csv")


def simulate(d, workers):
    """平行評估所有決策點，結果存成 CSV。"""
    d = d.assign(month=d["date"].map(month_of))
    jobs = [(mo, [r for _, r in g.iloc[i:i + CHUNK].iterrows()])
            for mo, g in d.groupby("month") for i in range(0, len(g), CHUNK)]
    print(f"決策點 {len(d)} 個（{SEASON} 年 {MIN_INNING} 局以後），{len(jobs)} 份工作，{workers} 個程序")
    t0 = time.time()
    rows = []
    with Pool(workers) as pool:
        for res in pool.imap_unordered(run_month, jobs):
            rows += res
            print(f"  完成 {len(rows)}/{len(d)}（{time.time() - t0:.0f} 秒）", flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(CSV, index=False, encoding="utf-8-sig")
    return res


def _num(v):
    return None if pd.isna(v) else round(float(v), 2)


def _txt(v):
    return None if pd.isna(v) else str(v)


def build_outputs(res, d):
    """由模擬結果產生網站用的 JSON 並印出總覽。"""
    ok = res[res.get("error").isna()] if "error" in res else res
    ok = ok.set_index("pa_id").loc[[p for p in d["pa_id"] if p in set(ok["pa_id"])]].reset_index()  # 依比賽順序
    print(f"成功 {len(ok)}，略過 {len(res) - len(ok)}")

    teams = sorted(set(ok["fld_team"]))
    by_team = {}
    for tm in teams:
        fld, bat = ok[ok["fld_team"] == tm], ok[ok["bat_team"] == tm]
        by_team[tm] = dict(pen=summarize(fld, THRESHOLD)["pen"], ph=summarize(bat, THRESHOLD)["ph"],
                           pen_timing=timing_summary(pen_timing(fld, THRESHOLD)))
    result = dict(
        season=SEASON, min_inning=MIN_INNING, threshold=THRESHOLD, generated=time.strftime("%Y-%m-%d"),
        method="每個打席前以與歷史回放相同的集成模型評估（只用比賽當天以前的資料）；換投比較上一打席投手續投與推估可用牛棚（接下來 3 棒），代打比較輪到的打者與推估板凳。最佳候選差值達門檻視為系統建議。",
        limits="可用名單由此前出賽推估，不含傷病與登錄；換了以後的結果無法觀測，只能比較模型估計；只看接下來 3 棒，不是整場最佳策略。",
        summary={str(t): summarize(ok, t) for t in THRESHOLDS},
        pen_timing=timing_summary(pen_timing(ok, THRESHOLD)),
        by_team=by_team,
        games={gid: {r["pa_id"]: [_num(r["pen_gain"]), _txt(r["pen_best"]), _txt(r["inc"]),
                                  _num(r["ph_gain"]), _txt(r["ph_best"]), _txt(r["due"])]
                     for _, r in g.iterrows()} for gid, g in ok.groupby("game")},
    )
    p = os.path.join(ROOT, "docs", "data", "timing-2025.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    print(f"輸出 {p}（{os.path.getsize(p) / 1024:.0f} KB）")
    for t in THRESHOLDS:
        s = result["summary"][str(t)]
        for kind, lab in (("pen", "換投"), ("ph", "代打")):
            x = s[kind]
            print(f"門檻 {t}：{lab} 決策點 {x['n']}，實際 {x['actual']}，系統建議 {x['suggested']}，兩者皆是 {x['both']}；"
                  f"沒換時 RE24 建議 {x['stay_re24_suggested']}（n={x['stay_n_suggested']}）vs 不建議 {x['stay_re24_not']}（n={x['stay_n_not']}），"
                  f"差 {x['stay_diff']}，95% 區間 {x['stay_diff_ci']}")
    print("換投時機：", result["pen_timing"])


def main():
    d = decision_points()
    if "--from-csv" in sys.argv:  # 只重建 JSON，不重跑模擬
        res = pd.read_csv(CSV, encoding="utf-8-sig", dtype={"pa_id": str, "game": str})
    else:
        res = simulate(d, int(sys.argv[1]) if len(sys.argv) > 1 else 4)
    build_outputs(res, d)


if __name__ == "__main__":
    main()
