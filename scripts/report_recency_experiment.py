"""Offline hierarchical-effect recency comparison; never changes active weights.

Reuses the existing chronological experiment. Paired bootstrap resamples games
and divides by the resampled pitch count, preserving game-size differences.
This is not an ensemble/decision-policy evaluation or a causal benefit estimate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import numpy as np
import pandas as pd
from recency_backtest import PERIODS, HALF_LIVES, month_data, batter_effects, gain
from model import fit


def paired_summary(difference, counts, seed, resamples=2000):
    difference=np.asarray(difference,dtype=float); counts=np.asarray(counts,dtype=float)
    if difference.ndim!=1 or len(difference)!=len(counts) or not len(counts):
        raise ValueError('Expected aligned nonempty game arrays')
    if not np.isfinite(difference).all() or not np.isfinite(counts).all() or (counts<=0).any():
        raise ValueError('Nonfinite or nonpositive game data')
    rng=np.random.default_rng(seed);boots=[]
    for _ in range(resamples):
        idx=rng.integers(0,len(counts),len(counts))
        boots.append(float(difference[idx].sum()/counts[idx].sum()*10000))
    lo,hi=np.percentile(boots,[2.5,97.5])
    return dict(paired_gain_per_10000_pitches=float(difference.sum()/counts.sum()*10000),
                game_bootstrap_ci95=[float(lo),float(hi)],games=len(counts),pitches=int(counts.sum()),
                seed=seed,resamples=resamples,interval_excludes_zero=bool(lo>0 or hi<0))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--seed',type=int,default=20261025);p.add_argument('--resamples',type=int,default=2000)
    args=p.parse_args()
    if args.resamples<100: p.error('Use at least 100 resamples')
    if args.out.exists():p.error('Output exists; choose another path to preserve the previous experiment')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    checkpoint=args.out.with_suffix('.progress.json');started=time.time();results=[]
    collected={(who,h):[] for who in ('pitcher','batter') for h in HALF_LIVES};count_rows=[]
    for start,end in PERIODS:
        tr,te,lg=month_data(start,end)
        assert (tr['date']<pd.Timestamp(start)).all()
        assert ((te['date']>=pd.Timestamp(start))&(te['date']<pd.Timestamp(end))).all()
        counts=te.groupby('game').size();count_rows.append(counts)
        for h in HALF_LIVES:
            m=fit(start,pitcher_half_life=h)
            for who,eff in [('pitcher',m.pit_all['effect']),('batter',batter_effects(tr,lg,h,int(start[:4])))]:
                g=gain(te,who,eff).reindex(counts.index)
                assert g.notna().all()
                collected[(who,h)].append(g)
        for who in ('pitcher','batter'):
            base=collected[(who,None)][-1]
            for h in HALF_LIVES[1:]:
                diff=collected[(who,h)][-1]-base
                results.append(dict(start=start,end=end,role=who,half_life_days=h,
                                    gain_vs_no_decay_per_10000_pitches=float(diff.sum()/counts.sum()*10000)))
        checkpoint.write_text(json.dumps(dict(completed_months=len(count_rows),total_months=len(PERIODS),
            latest_month=start,monthly_results=results,elapsed_seconds=round(time.time()-started,2)),ensure_ascii=False,indent=2),encoding='utf8')
        print(f'{start}: {len(counts)} games / {len(te)} pitches completed',flush=True)
    counts=pd.concat(count_rows);summaries=[]
    for who in ('pitcher','batter'):
        base=pd.concat(collected[(who,None)])
        for h in HALF_LIVES[1:]:
            diff=pd.concat(collected[(who,h)])-base
            assert diff.index.equals(counts.index)
            summaries.append(dict(role=who,half_life_days=h,**paired_summary(diff,counts,args.seed,args.resamples)))
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted((ROOT/'data/rebas').glob('*/*.json'))}
    code={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
          for p in [Path(__file__).resolve(),ROOT/'src/recency_backtest.py',ROOT/'src/model.py',ROOT/'src/load.py',ROOT/'src/identity.py']}
    result=dict(schema='baseball.recency-experiment.v1',status='complete',adopted=False,
        scope='Hierarchical player overall effects only; not the full ensemble, recommendation policy or causal value.',
        evaluation='Train before month start; score observed pitches in that month; paired game bootstrap.',
        selection_limit='Nine evaluation months reused for multiple candidates; no untouched post-selection holdout. Exploratory intervals, not adoption proof.',
        unit='Squared-error reduction per 10000 pitches relative to the same no-decay hierarchical baseline; positive is better.',
        active_half_life_days=None,seed=args.seed,resamples=args.resamples,periods=PERIODS,
        monthly=results,summary=summaries,source_manifest=sources,code_manifest=code,
        elapsed_seconds=round(time.time()-started,2))
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    print(json.dumps(summaries,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
