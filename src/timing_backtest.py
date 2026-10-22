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
import hashlib
import os
from pathlib import Path
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

from engine import evaluate_bullpen, evaluate_pinch_hit, model_at, situation
from fatigue import pitch_count_before
from load import ROOT, load
from batch_contract import metadata as batch_metadata
import mlmodel

MIN_INNING = 6
THRESHOLD = 1.0          # 百分點；網站標記與總覽使用
THRESHOLDS = [0.5, 1.0, 2.0]
BOOTSTRAP_REPS = 2000
BOOTSTRAP_SEED = 20261020
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
    # Construct stints before filtering or evaluation: missing gains must never
    # erase a real pitching change and join two different pitchers' segments.
    changed = d["pitcher"].ne(d["inc"])
    d["stint_id"] = changed.groupby([d["game"], d["fld_team"]]).cumsum().astype(int)
    d["inc_stint_id"] = d.groupby(["game", "fld_team"])["stint_id"].shift()
    starts=d.groupby(['game','fld_team','stint_id']).inning.min()
    d['window_left_censored']=[bool(starts.get((r.game,r.fld_team,r.inc_stint_id),MIN_INNING)<MIN_INNING)
                               for r in d.itertuples()]
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
    out.update(bat_score=int(r['bat_score']),fld_score=int(r['fld_score']),
               outs=int(r['outs']),bases=int(r['bases']))
    out.update(stint_id=int(r['stint_id']), inc_stint_id=int(r['inc_stint_id']),
               window_left_censored=bool(r['window_left_censored']))
    ph, _, _ = evaluate_pinch_hit(sit, model=m, ml=ml, scores=False)
    # 與網站建議相同：換下後守備排不出來的人選（守備 = bad）不能代打，不列入
    bench = ph[(ph["角色"] == "代打") & ph["守備"].isin(['ok','warn'])]
    out["ph_has_bench"] = bool((ph["角色"] == "代打").any())  # 未確認守位另列排除，不當成未提示
    out["ph_gain"] = float(bench["相對現任"].max()) if len(bench) else None
    out['ph_status'] = 'evaluated' if len(bench) else 'fielding_unconfirmed' if out['ph_has_bench'] else 'no_candidate'
    out["ph_best"] = bench["球員"].iat[0] if len(bench) else None
    pitching_sit=incumbent_situation(sit,r)
    out['inc_starter']=bool(pitching_sit['starter'])
    bp, _ = evaluate_bullpen(pitching_sit, model=m, ml=ml, scores=False)
    pen = bp[bp["角色"] == "牛棚"]
    # 與回放頁相同取「預估失分最低」者；勝率斜率已限制為非負。
    out["pen_gain"] = float(pen["守方勝率增減"].iat[0]) if len(pen) else None
    out["pen_best"] = pen["投手"].iat[0] if len(pen) else None
    out['pen_status'] = 'evaluated' if len(pen) else 'no_candidate'
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
            res.append(dict(pa_id=r["pa_id"], game=r['game'], fld_team=r['fld_team'],
                            stint_id=int(r['stint_id']), inc_stint_id=int(r['inc_stint_id']),
                            window_left_censored=bool(r['window_left_censored']),
                            pen_change=bool(r['pitcher'] != r['inc']), error=f"{type(e).__name__}: {e}"))
    return res


def month_of(date):
    return max(mlmodel.REPLAY_MONTHS[0], str(date.date())[:7] + "-01")


def cluster_interval(stay, gain, threshold, reps=BOOTSTRAP_REPS):
    """Resample complete games; retain both groups and all PA within each game."""
    a = stay[gain].ge(threshold)
    grouped = pd.DataFrame({'game':stay['game'], 'a_sum':stay['RE24'].where(a, 0),
                            'a_n':a.astype(int), 'b_sum':stay['RE24'].where(~a, 0),
                            'b_n':(~a).astype(int)}).groupby('game').sum().to_numpy()
    if len(grouped) < 2 or grouped[:, 1].sum() < 2 or grouped[:, 3].sum() < 2:
        return None
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    diffs = []
    for _ in range(reps):
        sums = grouped[rng.integers(0, len(grouped), len(grouped))].sum(axis=0)
        if sums[1] and sums[3]:
            diffs.append(sums[0] / sums[1] - sums[2] / sums[3])
    if len(diffs) < reps * .9:
        return None
    return [round(float(v), 3) for v in np.percentile(diffs, [2.5, 97.5])]


def summarize(d, t):
    """d：成功評估的打席；t：建議門檻（百分點）。"""
    s = {}
    for kind, gain, actual in (("pen", "pen_gain", "pen_change"), ("ph", "ph_gain", "is_ph")):
        # Both decision types require a finite eligible-candidate comparison.
        # A missing/no-eligible-candidate estimate is unevaluable, not a negative
        # recommendation. Keep it in coverage counts, outside the four cells.
        x = d.dropna(subset=[gain])
        sug, act = x[gain].fillna(-np.inf) >= t, x[actual].astype(bool)
        stay = x[~act & x["RE24"].notna()]
        # 留在場上的人該打席的 RE24：換投看防守方失分（越高越差），代打看進攻方得分（越低越差）
        stay_sug = stay[gain].fillna(-np.inf) >= t
        re_sug, re_not = stay.loc[stay_sug, "RE24"], stay.loc[~stay_sug, "RE24"]
        diff = ci = None
        if len(re_sug) > 1 and len(re_not) > 1:
            diff = float(re_sug.mean() - re_not.mean())
            se = float(np.sqrt(re_sug.var() / len(re_sug) + re_not.var() / len(re_not)))
            ci = [round(diff - 1.96 * se, 3), round(diff + 1.96 * se, 3)]
        s[kind] = dict(stay_diff=None if diff is None else round(diff, 3), stay_diff_ci=cluster_interval(stay, gain, t),
                       stay_diff_ci_normal=ci, ci_method='game_cluster_bootstrap', bootstrap_reps=BOOTSTRAP_REPS,
                       excluded=int(len(d)-len(x)), n=int(len(x)), actual=int(act.sum()), suggested=int(sug.sum()),
                       both=int((sug & act).sum()), sys_only=int((sug & ~act).sum()), actual_only=int((~sug & act).sum()),
                       neither=int((~sug & ~act).sum()),
                       stay_re24_suggested=round(float(re_sug.mean()), 3) if len(re_sug) else None, stay_n_suggested=int(len(re_sug)),
                       stay_re24_not=round(float(re_not.mean()), 3) if len(re_not) else None, stay_n_not=int(len(re_not)))
        s[kind].update(stay_games_suggested=int(stay.loc[stay_sug,'game'].nunique()),
                       stay_games_not=int(stay.loc[~stay_sug,'game'].nunique()))
    return s


def timing_summary(timing):
    early = [k for k in timing if k is not None]
    return dict(changes=len(timing), system_never=sum(k is None for k in timing), same=sum(k == 0 for k in early),
                earlier=sum(k > 0 for k in early),
                earlier_median=float(np.median([k for k in early if k > 0])) if any(k > 0 for k in early) else None)


def composition_diagnostic(d,kind,t):
    """Descriptive standardization on shared support; not a causal estimator.

    Predefined coarse strata: team, month, 6–7/8+, score <=-3/-2..2/>=3,
    and incumbent starter/reliever. Require at least five PA in each group.
    """
    gain,actual=('pen_gain','pen_change') if kind=='pen' else ('ph_gain','is_ph')
    x=d[d[gain].notna() & ~d[actual].astype(bool) & d.RE24.notna()].copy()
    x['month']=x['date'].astype(str).str[:7]
    x['late']=np.where(x.inning<8,'6-7','8+')
    diff=x.bat_score-x.fld_score
    x['score_band']=np.select([diff<=-3,diff>=3],['behind_3plus','ahead_3plus'],default='within_2')
    x['signal']=x[gain]>=t
    rows=[];numerator=weight=0
    fields=['fld_team' if kind=='pen' else 'bat_team','month','late','score_band','inc_starter']
    for keys,g in x.groupby(fields):
        a,b=g[g.signal].RE24,g[~g.signal].RE24
        supported=len(a)>=5 and len(b)>=5
        row=dict(zip(fields,[v.item() if hasattr(v,'item') else v for v in keys]))
        row.update(n_suggested=len(a),n_not=len(b),supported=supported,
                   observed_difference=float(a.mean()-b.mean()) if len(a) and len(b) else None)
        rows.append(row)
        if supported:numerator+=(a.mean()-b.mean())*len(g);weight+=len(g)
    return dict(method='descriptive_common_support_standardization_not_causal',
                minimum_per_group=5,total_stay_pa=len(x),supported_pa=weight,
                standardized_difference=float(numerator/weight) if weight else None,strata=rows)


def pen_timing(d, t):
    """每次實際換投：系統在這位投手本段登板中，最早在幾個打席前就建議換。"""
    out = []
    if 'inc_stint_id' in d:
        for _, group in d.groupby(['game', 'fld_team'], sort=False):
            for _, change in group[group['pen_change'].astype(bool)].iterrows():
                previous = group[(group['stint_id'] == change['inc_stint_id']) & ~group['pen_change'].astype(bool)]
                # Missing estimates make "never" or a precise earliest time
                # unknowable. Such events are counted separately in coverage.
                values = list(previous['pen_gain']) + [change['pen_gain']]
                if any(pd.isna(v) for v in values):
                    continue
                first = next((i for i, v in enumerate(values) if v >= t), None)
                out.append(None if first is None else len(values) - 1 - first)
        return out
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


def run_cached_month(args):
    month, rows, filename = args
    path=Path(filename)
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    result=run_month((month,rows))
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,
                                   default=lambda v:v.item() if hasattr(v,'item') else str(v)),encoding='utf-8')
    temporary.replace(path)
    return result


def simulate(d, workers):
    """平行評估所有決策點，結果存成 CSV。"""
    d = d.assign(month=d["date"].map(month_of))
    jobs = [(mo, [r for _, r in g.iloc[i:i + CHUNK].iterrows()])
            for mo, g in d.groupby("month") for i in range(0, len(g), CHUNK)]
    digest=hashlib.sha256()
    for name in ('load.py','identity.py','model.py','engine.py','roster.py','fatigue.py','mlmodel.py','timing_backtest.py'):
        digest.update((Path(__file__).parent/name).read_bytes())
    for path in sorted(Path(mlmodel.MODEL_DIR).glob(f'gbt_*_v{mlmodel.TRAINING_VERSION}.pkl')):
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    digest.update(json.dumps(list(d.pa_id)).encode())
    audit=Path(ROOT)/'output/closeout/input-audit.json'
    if audit.exists():digest.update(audit.read_bytes())
    cache=Path(ROOT)/'output/closeout/timing-checkpoints'/digest.hexdigest()[:20]
    cache.mkdir(parents=True,exist_ok=True)
    jobs=[(month,rows,str(cache/f'{i:03d}.json')) for i,(month,rows) in enumerate(jobs)]
    print(f"決策點 {len(d)} 個（{SEASON} 年 {MIN_INNING} 局以後），{len(jobs)} 份工作，{workers} 個程序")
    t0 = time.time()
    rows = []
    with Pool(workers) as pool:
        for res in pool.imap_unordered(run_cached_month, jobs):
            rows += res
            print(f"  完成 {len(rows)}/{len(d)}（{time.time() - t0:.0f} 秒）", flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(CSV, index=False, encoding="utf-8-sig")
    return res


def _num(v):
    # Do not round a gain across the recommendation threshold in the UI.
    return None if pd.isna(v) else round(float(v), 6)


def _txt(v):
    return None if pd.isna(v) else str(v)


def divergent(ok, d, team, kind, t=THRESHOLD, n=10):
    """系統建議換人、但實際沒換，且建議最強的打席（賽季回顧的「分歧最大的打席」）。

    同一場同一位投手（換投）或打者（代打）只列建議最強的一次，避免同一段登板佔滿清單。
    """
    if kind == "pen":
        x = ok[(ok["fld_team"] == team) & ~ok["pen_change"].astype(bool) & (ok["pen_gain"] >= t)]
        x = x.sort_values("pen_gain", ascending=False).drop_duplicates(["game", "inc"]).head(n)
        who, best, gain, opp = "inc", "pen_best", "pen_gain", "bat_team"
    else:
        x = ok[(ok["bat_team"] == team) & ~ok["is_ph"].astype(bool) & (ok["ph_gain"].fillna(-np.inf) >= t)]
        x = x.sort_values("ph_gain", ascending=False).drop_duplicates(["game", "due"]).head(n)
        who, best, gain, opp = "due", "ph_best", "ph_gain", "fld_team"
    info = d.set_index("pa_id")
    return [dict(pa=r["pa_id"], game=r["game"], date=str(r["date"])[:10], inning=int(r["inning"]), half=r["half"],
                 opp=r[opp], who=_txt(r[who]), best=_txt(r[best]), gain=_num(r[gain]),
                 outs=int(info.at[r["pa_id"], "outs"]), bases=int(info.at[r["pa_id"], "bases"]),
                 bat_score=int(info.at[r["pa_id"], "bat_score"]), fld_score=int(info.at[r["pa_id"], "fld_score"]),
                 result=_txt(info.at[r["pa_id"], "result"]))
            for _, r in x.iterrows()]


def build_outputs(res, d, reuse_provenance=None):
    """由模擬結果產生網站用的 JSON 並印出總覽。"""
    ok = res[res.get("error").isna()] if "error" in res else res
    ok = ok.set_index("pa_id").loc[[p for p in d["pa_id"] if p in set(ok["pa_id"])]].reset_index()  # 依比賽順序
    # Keep failed decisions in event reconstruction; they can censor a stint.
    events = res.set_index('pa_id').reindex(d['pa_id']).reset_index()
    classified = pen_timing(events, THRESHOLD)
    print(f"成功 {len(ok)}，略過 {len(res) - len(ok)}")

    teams = sorted(set(ok["fld_team"]))
    by_team = {}
    for tm in teams:
        fld, bat = ok[ok["fld_team"] == tm], ok[ok["bat_team"] == tm]
        by_team[tm] = dict(pen=summarize(fld, THRESHOLD)["pen"], ph=summarize(bat, THRESHOLD)["ph"],
                           pen_timing=timing_summary(pen_timing(events[events['fld_team']==tm], THRESHOLD)),
                           divergent=dict(pen=divergent(ok, d, tm, "pen"), ph=divergent(ok, d, tm, "ph")))
    result = dict(
        schema_version=2, **batch_metadata(),
        ci_method='game_cluster_bootstrap', bootstrap_seed=BOOTSTRAP_SEED,
        observation_target='single_pa_RE24_diagnostic_not_three_batter_policy_value',
        coverage=dict(attempted=len(res), successful=len(ok), errors=len(res)-len(ok)),
        exclusion_reasons={kind:ok[kind+'_status'].value_counts().to_dict() for kind in ('pen','ph')},
        monthly={month:summarize(group, THRESHOLD) for month,group in ok.groupby(ok['date'].astype(str).str[:7])},
        composition={kind:composition_diagnostic(ok,kind,THRESHOLD) for kind in ('pen','ph')},
        season=SEASON, min_inning=MIN_INNING, threshold=THRESHOLD, generated=time.strftime("%Y-%m-%d"),
        method="每個打席前以與歷史回放相同的集成模型評估（只用比賽當天以前的資料）；換投比較上一打席投手續投與推估可用牛棚（接下來 3 棒），代打比較輪到的打者與推估板凳。最佳候選差值達門檻視為系統建議。",
        limits="可用名單與守位由此前出賽推估，不含傷病與登錄；換下後板凳無人能接守的代打不列入建議；換了以後的結果無法觀測，只能比較模型估計；只看接下來 3 棒，不是整場最佳策略。",
        summary={str(t): summarize(ok, t) for t in THRESHOLDS},
        pen_timing=dict(timing_summary(classified),
                        left_censored_changes=int(events.loc[events.pen_change.astype(bool),'window_left_censored'].sum()),
                        actual_changes_observed=int(events['pen_change'].sum()),
                        not_classified=int(events['pen_change'].sum())-len(classified),
                        scope='sixth_inning_onward_only_not_full_stint_before_sixth'),
        by_team=by_team,
        games={gid: {r["pa_id"]: [_num(r["pen_gain"]), _txt(r["pen_best"]), _txt(r["inc"]),
                                  _num(r["ph_gain"]), _txt(r["ph_best"]), _txt(r["due"]), int(bool(r["ph_has_bench"]))]
                     for _, r in g.iterrows()} for gid, g in ok.groupby("game")},
    )
    if reuse_provenance is not None:result['calibration_revision_reuse']=reuse_provenance
    p = os.path.join(os.environ.get('BASEBALL_STATIC_OUT',os.path.join(ROOT,'docs','data')), 'timing-2025.json')
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
        proof_path=os.environ.get('BASEBALL_CALIBRATION_PROOF')
        if not proof_path:raise ValueError('CSV reuse requires a verified calibration invariance proof')
        import hashlib
        proof=json.loads(Path(proof_path).read_text(encoding='utf8'))
        if proof.get('passed') is not True or proof.get('batch_id')!=batch_metadata()['batch_id'] or proof['timing_csv_sha256']!=hashlib.sha256(Path(CSV).read_bytes()).hexdigest():
            raise ValueError('Timing reuse proof does not match this batch/CSV')
        res = pd.read_csv(CSV, encoding="utf-8-sig", dtype={"pa_id": str, "game": str})
    else:
        res = simulate(d, int(sys.argv[1]) if len(sys.argv) > 1 else 4)
    provenance=dict(proof_sha256=hashlib.sha256(Path(proof_path).read_bytes()).hexdigest(),source_csv_sha256=proof['timing_csv_sha256'],reason=proof['timing_reuse_proof']) if "--from-csv" in sys.argv else None
    build_outputs(res, d, provenance)


if __name__ == "__main__":
    main()
