"""Evaluate the v5 site's numerical fatigue term on observed three-batter windows."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

import numpy as np
import pandas as pd
from engine import ensemble_runs, model_at, runs_matrix
from evaluate_matchup_horizons_2026 import prepare
from evaluate_pitcher_workload_2026 import prior_load
from fatigue import penalty
from load import load
from model import PITCHES_PER_PA
import mlmodel
from runtime_config import settings

REPLICATES=2000
SEED=20261020


def inputs():
    pa,pitches,boxes=load()
    _,edges,windows,skipped=prepare(pa,boxes)
    pitches=pitches.sort_values(['game','half','seq','j']).copy()
    pitches['prior_pitches']=pitches.groupby(['game','pitcher']).cumcount()
    valid=windows.merge(pitches.drop_duplicates('pa_id')[['pa_id','prior_pitches']],on='pa_id',how='left',validate='one_to_one')
    valid=valid.dropna(subset=['prior_pitches']).reset_index(drop=True)
    starters=set(boxes.loc[boxes.role.eq('P') & boxes.order.eq(1),['game','name']].itertuples(index=False,name=None))
    valid['starter']=[(g,p) in starters for g,p in zip(valid.game,valid.pitcher)]
    valid=valid.join(prior_load(valid,boxes))
    # Separate recent workload from the published formula, which uses zero
    # for prior-day fatigue unless the viewer supplies their assumptions.
    second=boxes.loc[boxes.role.eq('P'),['name','date']].drop_duplicates()
    second['prior2']=True
    valid['prior2_date']=valid.date-pd.Timedelta(days=2)
    valid=valid.merge(second,left_on=['pitcher','prior2_date'],right_on=['name','date'],how='left',suffixes=('','_event'))
    valid['worked_two_days']=valid.previous_day.gt(0)&valid.prior2.eq(True)
    return edges,valid,skipped


def state_baseline(edges,cutoff):
    prior=edges[edges.date<cutoff]
    counts=np.zeros((25,25))
    reward=np.zeros(25)
    np.add.at(counts,(prior.state.to_numpy(),prior.end.to_numpy()),1)
    np.add.at(reward,prior.state.to_numpy(),prior.runs.to_numpy())
    counts[24,24]=1
    den=counts.sum(axis=1)
    transitions=counts/den[:,None]
    reward/=den
    survival=np.r_[np.ones(24),0.]
    return reward+transitions@reward+transitions@transitions@reward, np.stack((survival,transitions@survival,transitions@transitions@survival),axis=1)


def run_month(job):
    cutoff,rows,baseline,survival=job
    tree=mlmodel.get(cutoff)
    parts=[]
    for stamp,day in rows.groupby('date'):
        date=str(stamp.date())
        if settings().month_for(date)!=cutoff:
            raise ValueError('Weight crossed test month')
        m=model_at(date)
        for pitcher,group in day.groupby('pitcher'):
            # Shared query batches populate the existing simulator cache and
            # query all projected hitters using the pre-PA lineup.
            batters=list(dict.fromkeys(group[['b1','b2','b3']].to_numpy().flatten()))
            h,g=runs_matrix(m,tree,[pitcher],batters)
            per_batter=dict(zip(batters,((1-mlmodel.ENSEMBLE_W)*h+mlmodel.ENSEMBLE_W*g)[0]))
            estimates=np.array([[per_batter[b] for b in row] for row in group[['b1','b2','b3']].itertuples(index=False,name=None)])
            states=group.state.to_numpy(dtype=int)
            exposure=survival[states]
            term=np.array([[penalty(pc+PITCHES_PER_PA*i,starter,date) for i in range(3)]
                           for pc,starter in zip(group.prior_pitches,group.starter)])
            base=baseline[states]
            no=base+(estimates*exposure).sum(1)
            on=no+(term*exposure).sum(1)
            result=group[['pa_id','game','date','inning','score_diff','state','prior_pitches','starter','replacement',
                          'worked_two_days','previous_day','last_three_days','runs']].copy()
            result['situation']=base
            result['without_fatigue']=no.clip(0)
            result['with_fatigue']=on.clip(0)
            result['fatigue_increment']=(term*exposure).sum(1)
            parts.append(result)
    print(f'{cutoff}: {len(rows)} eligible windows',flush=True)
    return pd.concat(parts)


def summarize(rows):
    targets=rows.runs.to_numpy()
    result={'windows':len(rows),'games':int(rows.game.nunique())}
    if not len(rows):return result
    forecasts=('situation','without_fatigue','with_fatigue')
    errors={v:rows[v].to_numpy()-targets for v in forecasts}
    result['metrics']={v:dict(mse=float(np.mean(e**2)),mae=float(np.mean(abs(e))),bias=float(np.mean(e)))
                       for v,e in errors.items()}
    result['adjusted_windows']=int(rows.fatigue_increment.ne(0).sum())
    pairings=(('with_fatigue','without_fatigue'),('with_fatigue','situation'))
    for metric,base in pairings:
        values=errors[metric]**2-errors[base]**2
        stats=pd.DataFrame({'game':rows.game,'delta':values}).groupby('game').delta.agg(['sum','size']).to_numpy()
        item={'mse_delta':float(values.mean()),'paired_95_ci':None}
        if len(stats)>1:
            rng=np.random.default_rng(SEED)
            draws=stats[rng.integers(0,len(stats),size=(REPLICATES,len(stats)))].sum(1)
            item['paired_95_ci']=list(np.percentile(draws[:,0]/draws[:,1],[2.5,97.5]))
        result[f'{metric}_minus_{base}']=item
    bins=pd.cut(rows.with_fatigue,[-np.inf,.25,.5,1,np.inf],include_lowest=True)
    result['with_fatigue_calibration']=[dict(bucket=str(band),n=len(g),forecast=float(g.with_fatigue.mean()),
                                             observed=float(g.runs.mean()))
                                        for band,g in rows.groupby(bins,observed=True)]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--workers',default=4,type=int)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    runtime=settings()
    if runtime.data_seasons!=(2024,2025,2026) or runtime.season!=2026:
        parser.error('Use the three-season 2026 research batch')
    edges,rows,skipped=inputs()
    rows=rows.loc[rows.date.dt.year.eq(2026)].copy()
    rows['month']=rows.date.dt.strftime('%Y-%m-01')
    jobs=[(cutoff,rows[rows.month.eq(cutoff)],*state_baseline(edges,cutoff)) for cutoff in runtime.replay_cutoffs]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        result=pd.concat(pool.map(run_month,jobs)).sort_values(['date','game','pa_id'])
    assert result.pa_id.is_unique and len(result)==len(rows)
    assert np.isfinite(result[['situation','without_fatigue','with_fatigue','runs']]).all().all()
    result.to_csv(args.out/'predictions.csv',index=False)
    groups={'all':result,'starter':result[result.starter],
            'starter_95_plus':result[result.starter & result.prior_pitches.ge(95)],
            'reliever':result[~result.starter],
            'reliever_worked_two_days':result[~result.starter & result.worked_two_days],
            'observed_replacement':result[result.replacement],
            'late_close':result[result.inning.ge(8)&result.score_diff.abs().le(1)]}
    summaries={name:summarize(group) for name,group in groups.items()}
    monthly={month:summarize(group) for month,group in result.groupby(result.date.dt.strftime('%Y-%m'))}
    metadata=dict(season=2026,months=list(runtime.replay_cutoffs),bootstrap_reps=REPLICATES,seed=SEED,
                  three_season_exclusions=skipped,monthly=monthly,groups=summaries,
                  treatment='Numerical fatigue uses site starter curve. Default reliever and previous-day penalty are zero.',
                  accounting='Runs through third out or three batters. State base and planned PA survival are estimated before the test month. The site pregame ensemble and fatigue terms are compared on matched observed actors and converted to a run forecast with that same base. This is an offline diagnostic.',
                  status='diagnostic_no_production_change')
    (args.out/'summary.json').write_text(json.dumps(metadata,allow_nan=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({name:{'windows':value['windows'],'added_fatigue':value.get('with_fatigue_minus_without_fatigue')}
                      for name,value in summaries.items()},indent=2))

if __name__=='__main__':
    main()
