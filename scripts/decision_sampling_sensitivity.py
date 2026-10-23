"""Bounded diagnostic: nearest-threshold and largest-gain PA per team/kind.

This purposive fixed-day sample is not a population estimate or confidence
interval. Calibration constants are fixed: they cancel in candidate contrasts.
No configuration is selected from this diagnostic.
"""
from pathlib import Path
import json,sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
import server,mlmodel
from batch_contract import metadata
from engine import situation,evaluate_pinch_hit,evaluate_bullpen
from timing_backtest import incumbent_situation,decision_points

def compare(sit,m,ml,kind):
    if kind=='ph':
        table,_,_=evaluate_pinch_hit(sit,model=m,ml=ml)
        rows=table[(table['角色']=='代打')&table['守備'].isin(['ok','warn'])]
        name,gain='球員','相對現任'
    else:
        table,_=evaluate_bullpen(sit,model=m,ml=ml)
        rows=table[table['角色']=='牛棚'];name,gain='投手','守方勝率增減'
    if rows.empty:return dict(best=None,gain=None,suggested=False,gap=None)
    values=rows[gain].to_numpy()
    return dict(best=rows[name].iat[0],gain=float(values[0]),suggested=bool(values[0]>=1),
                gap=float(values[0]-values[1]) if len(values)>1 else None)

def main():
    date='2025-09-20';cutoff='2025-09-01'
    frame=pd.read_csv(ROOT/'output/timing_backtest.csv',encoding='utf-8-sig')
    frame=frame[frame.date.str.startswith(date)]
    contexts=decision_points().set_index('pa_id')
    jobs=[]
    for kind,team in [('ph','bat_team'),('pen','fld_team')]:
        eligible=frame[frame[kind+'_gain'].notna()].copy()
        for _,g in eligible.groupby(team):
            nearest=g.iloc[(g[kind+'_gain']-1).abs().argsort()[:1]]
            strongest=g.nlargest(1,kind+'_gain')
            for _,r in pd.concat([nearest,strongest]).drop_duplicates('pa_id').iterrows():
                sit=situation(r.pa_id)
                if kind=='pen':sit=incumbent_situation(sit,contexts.loc[r.pa_id])
                jobs.append((kind,r.pa_id,r[team],sit))
    gm=mlmodel.get(cutoff);m=server.model_for(date)
    original=[compare(s,m,gm,k) for k,_,_,s in jobs]
    tr=mlmodel.training_pitches(mlmodel._pitches(),cutoff)
    reports=[]
    for sample,seed in [(75,0),(300,0),(150,1)]:
        sim=mlmodel.Simulator(tr,gm.sim.models,gm.sim.tb,gm.sim.velo_tbl,gm.sim.velo_type,sample=sample,random_state=seed)
        variant=mlmodel.MLModel(cutoff,sim,gm.offset);variant.rel_bias=gm.rel_bias
        cases=[]
        for (kind,pid,team,sit),base in zip(jobs,original):
            got=compare(sit,m,variant,kind)
            assert got['gain'] is not None and base['gain'] is not None
            cases.append(dict(kind=kind,pa_id=pid,team=team,baseline=base,variant=got,
                top1_changed=base['best']!=got['best'],threshold_changed=base['suggested']!=got['suggested'],
                absolute_gain_shift=abs(got['gain']-base['gain'])))
        reports.append(dict(sample=sample,seed=seed,cases=cases,
            top1_changes=sum(c['top1_changed'] for c in cases),threshold_changes=sum(c['threshold_changed'] for c in cases),
            max_gain_shift=max(c['absolute_gain_shift'] for c in cases)))
        print(sample,seed,len(cases),'cases',flush=True)
    report=dict(**metadata(),status='diagnostic_completed',date=date,ml_cutoff=cutoff,cases=len(jobs),
        sampling_rule='per team and decision kind: eligible PA nearest to 1 percentage-point threshold plus highest gain; deduplicate within kind',
        limitations='Purposive single-day sample; no population accuracy, probability of winning, causal effect or full ensemble confidence interval.',
        variants=reports)
    out=ROOT/'output/revision-20261021/decision-sampling-sensitivity.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')

if __name__=='__main__':main()
