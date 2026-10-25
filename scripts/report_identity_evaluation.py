"""Publish fixed-configuration retrospective metrics from sealed PA predictions.

No parameter selection or new holdout claim. Historical period labels are retained
only for schema compatibility; both periods have already been inspected.
"""
import hashlib,json,os,sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src')]
from load import load
from batch_contract import metadata
OUT=ROOT/'output/identity-integration-20261025'

def main():
    file=OUT/'evaluation-v5/predictions.csv'
    receipt=json.loads((file.parent/'receipt.json').read_text(encoding='utf8'))
    if receipt['predictions_sha256']!=hashlib.sha256(file.read_bytes()).hexdigest() or receipt['training_version']!=5:
        raise ValueError('Predictions are not the completed v5 batch')
    d=pd.read_csv(file);d=d[d.month>='2025-05'].copy();pa=load()[0]
    d['baseline']=d.month.map({m:float(pa[pa.date<m+'-01'].RE24.dropna().mean()) for m in d.month.unique()})
    d['period']=np.where(d.month<'2025-09','development','time_check')
    def metrics(frame,key):
        err=frame[key]-frame.y;base=frame.baseline-frame.y
        sums=pd.DataFrame({'game':frame.game,'gain':base**2-err**2,'n':1}).groupby('game').sum().to_numpy()
        rng=np.random.default_rng(20261025);draw=[]
        for _ in range(2000):
            row=sums[rng.integers(0,len(sums),len(sums))].sum(axis=0);draw.append(row[0]/row[1])
        return dict(n=len(frame),games=len(sums),mse=float(np.mean(err**2)),mae=float(np.mean(abs(err))),
            baseline_mse=float(np.mean(base**2)),mse_reduction=float(np.mean(base**2-err**2)),
            mse_reduction_ci=np.quantile(draw,[.025,.975]).tolist())
    candidates=[]
    for key,column,weight in [('s1_w0','hierarchy',0),('s1_w1','gbt',1),('s1_w0.5','prediction',.5)]:
        candidates.append(dict(key=key,hierarchy_scale=1,gbt_weight=weight,tree_variant='current',
            **{period:metrics(d[d.period==period],column) for period in ('development','time_check')}))
    report=dict(schema_version=1,**metadata(),status='evaluated',
        evaluation='retrospective_fixed_config_already_inspected_not_new_holdout',
        target='observed_single_pa_RE24',primary_metric='mse',seed=20261025,bootstrap_reps=2000,
        ci_method='paired_game_cluster_bootstrap',development_months=['2025-05','2025-08'],
        time_check_months=['2025-09','2025-10'],selected_key='s1_w0.5',current_key='s1_w0.5',adopted_key='s1_w0.5',
        selected_config=dict(hierarchy_scale=1,gbt_weight=.5,tree_variant='current'),
        adopted_config=dict(hierarchy_scale=1,gbt_weight=.5,tree_variant='current'),
        adoption_rule='unchanged predeclared 0.5 ensemble; no tuning or selection from this audit',
        development_selected_vs_current_ci=[0,0],sampling_sensitivity=[],candidates=candidates,
        monthly=[dict(month=month,period=frame.period.iat[0],current=metrics(frame,'prediction'),selected=metrics(frame,'prediction')) for month,frame in d.groupby('month')],
        provenance=dict(predictions_sha256=receipt['predictions_sha256'],
            context_sha256=hashlib.sha256((OUT/'candidate-context.json').read_bytes()).hexdigest(),
            source_id=json.loads((OUT/'candidate-context.json').read_text(encoding='utf8')).get('source_id')))
    output=Path(os.environ.get('BASEBALL_STATIC_OUT',ROOT/'docs/data'))/'model-evaluation.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(candidates[-1],ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
