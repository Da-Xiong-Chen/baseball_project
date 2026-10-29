"""Retrospective rolling comparison with development-only parameter selection.

No test-month centering, no coach-action-as-ground-truth accuracy. All methods
share observable PA targets. Run after train_closeout.py with its candidate dir.
"""
import hashlib
import json
import os
import pickle
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
import numpy as np
import pandas as pd
from load import load
import mlmodel
from model import fit

MONTHS = ['2025-05-01','2025-06-01','2025-07-01','2025-08-01','2025-09-01','2025-10-01','2025-11-01']
WEIGHTS = [0,.25,.5,.75,1]
SCALES = [.75,1,1.25]


def main():
    if mlmodel.TRAINING_VERSION != 4:
        raise RuntimeError('Historical v4 evaluation workflow; use scripts/evaluate_identity_batch.py and scripts/report_identity_evaluation.py for v5.')
    out=Path(os.environ.get('BASEBALL_REPORT_OUT',ROOT/'output/closeout'));out.mkdir(exist_ok=True,parents=True)
    pa=load()[0]; records=[]; candidates={}; sensitivity=[]
    for scale in SCALES:
        for weight in WEIGHTS:
            candidates[f's{scale:g}_w{weight:g}']={'hierarchy_scale':scale,'gbt_weight':weight,'tree_variant':'current'}
    for weight in WEIGHTS[1:]:
        candidates[f'reg_w{weight:g}']={'hierarchy_scale':1,'gbt_weight':weight,'tree_variant':'regularized_15_leaf_l2_3'}
    reuse=os.environ.get('BASEBALL_RECALIBRATED_PREDICTIONS')
    if reuse:
        from batch_contract import metadata as batch_metadata
        proof=json.loads((out/'calibration-impact.json').read_text(encoding='utf8'))
        if proof.get('passed') is not True or proof.get('batch_id')!=batch_metadata()['batch_id'] or hashlib.sha256(Path(reuse).read_bytes()).hexdigest()!=proof['corrected_predictions_sha256']:
            raise ValueError('Recalibration proof does not match this batch/predictions')
        d=pd.read_csv(reuse)
        for month,frame in d.groupby('month'):
            for sample,seed in [(75,0),(300,0),(150,1)]:
                pred=frame[f'sample{sample}_seed{seed}'];shift=abs(pred-frame['s1_w0.5'])
                sensitivity.append({'month':month,'sample':sample,'seed':seed,'n':len(frame),
                    'mse':float(np.mean((pred-frame.y)**2)),
                    'mean_absolute_prediction_shift':float(shift.mean()),'max_absolute_prediction_shift':float(shift.max())})
    else:
        for start,end in zip(MONTHS[:-1],MONTHS[1:]):
            test=pa[(pa.date>=start)&(pa.date<end)].dropna(subset=['RE24']).copy()
            hm=fit(start); gm=mlmodel.get(start)
            queries=list(dict.fromkeys(test[['batter','bhand','pitcher']].itertuples(index=False,name=None)))
            hs=[hm.matchup(*q) for q in queries]; gs=[]; regularized=[]
            variant_path=Path(mlmodel.MODEL_DIR)/f'regularized_v{mlmodel.TRAINING_VERSION}_{start[:7]}.pkl'
            if variant_path.exists():
                with variant_path.open('rb') as f: variant=pickle.load(f)
            else:
                raise FileNotFoundError('請先以 train_closeout.py 明確建立實驗權重及批次來源')
            for i in range(0,len(queries),128):
                gs.extend(gm.abs_many(queries[i:i+128]))
                regularized.extend(variant.abs_many(queries[i:i+128]))
            lookup={q:i for i,q in enumerate(queries)}
            indices=np.array([lookup[q] for q in test[['batter','bhand','pitcher']].itertuples(index=False,name=None)])
            h=np.array([x['per_pa'] for x in hs])[indices]
            effects=np.array([x['skill_pa']+x['pitcher_q'] for x in hs])[indices]
            g=np.array(gs)[indices]; reg=np.array(regularized)[indices]; y=test.RE24.to_numpy()
            baseline=float(pa[pa.date<start].RE24.dropna().mean())
            frame=pd.DataFrame({'pa_id':test.pa_id.to_numpy(),'game':test.game.to_numpy(),
                                'month':start[:7],'period':'development' if start<'2025-09-01' else 'time_check',
                                'y':y,'baseline':baseline})
            for key,c in candidates.items():
                tree=reg if c['tree_variant']!='current' else g
                pred=(1-c['gbt_weight'])*(h+(c['hierarchy_scale']-1)*effects)+c['gbt_weight']*tree
                frame[key]=pred
            # These are sensitivity checks, not additional model-selection choices.
            tr=mlmodel.training_pitches(mlmodel._pitches(),start)
            for sample,seed in [(75,0),(300,0),(150,1)]:
                sim=mlmodel.Simulator(tr,gm.sim.models,gm.sim.tb,gm.sim.velo_tbl,gm.sim.velo_type,
                                      sample=sample,random_state=seed)
                variant=mlmodel.MLModel(start,sim,gm.offset)
                values=[]
                for i in range(0,len(queries),128):values.extend(variant.abs_many(queries[i:i+128]))
                pred=.5*h+.5*np.asarray(values)[indices]
                frame[f'sample{sample}_seed{seed}']=pred
                sensitivity.append({'month':start[:7],'sample':sample,'seed':seed,'n':len(y),
                                    'mse':float(np.mean((pred-y)**2)),
                                    'mean_absolute_prediction_shift':float(np.mean(abs(pred-(.5*h+.5*g)))),
                                    'max_absolute_prediction_shift':float(np.max(abs(pred-(.5*h+.5*g))))})
            records.append(frame)
            print(start, len(test), 'PA;',len(queries),'unique matchups',flush=True)
        d=pd.concat(records,ignore_index=True)
    d.to_csv(out/'rolling-predictions.csv',index=False)
    def metrics(sub,key):
        err=(sub[key]-sub.y).to_numpy(); base=(sub.baseline-sub.y).to_numpy()
        grouped=pd.DataFrame({'game':sub.game,'loss':err**2,'base':base**2,'n':1}).groupby('game').sum().to_numpy()
        rng=np.random.default_rng(20261020);boot=[]
        for _ in range(2000):
            b=grouped[rng.integers(0,len(grouped),len(grouped))].sum(axis=0)
            boot.append((b[1]-b[0])/b[2])
        return {'n':len(sub),'games':len(grouped),'mse':float(np.mean(err**2)),'mae':float(np.mean(abs(err))),
                'baseline_mse':float(np.mean(base**2)), 'mse_reduction':float(np.mean(base**2-err**2)),
                'mse_reduction_ci':[float(x) for x in np.percentile(boot,[2.5,97.5])]}
    development=d[d.period=='development']; check=d[d.period=='time_check']
    ranked=sorted(candidates,key=lambda k:float(((development[k]-development.y)**2).mean()))
    selected=ranked[0]; current='s1_w0.5'
    # A development winner alone is insufficient to replace the deployed model.
    # Freeze this rule before inspecting results: paired game-bootstrap lower
    # bound against current must exceed zero. Later months remain descriptive.
    paired=development.copy()
    paired['baseline']=paired[current]
    difference=(paired[current]-paired.y)**2-(paired[selected]-paired.y)**2
    sums=pd.DataFrame({'game':paired.game,'diff':difference,'n':1}).groupby('game').sum().to_numpy()
    rng=np.random.default_rng(20261020);delta=[]
    for _ in range(2000):
        sample=sums[rng.integers(0,len(sums),len(sums))].sum(axis=0)
        delta.append(sample[0]/sample[1])
    paired_ci=[float(x) for x in np.percentile(delta,[2.5,97.5])]
    adopted=current  # Calibration-only revision: retain the predeclared 0.5 ensemble.
    # Selection was fixed before looking at the later-period metrics below.
    from batch_contract import metadata as batch_metadata
    report={'schema_version':1,**batch_metadata(),
            'status':'evaluated','evaluation':'retrospective_rolling_not_prospective',
            'target':'observed_single_pa_RE24','primary_metric':'mse','ci_method':'paired_game_cluster_bootstrap',
            'seed':20261020,'bootstrap_reps':2000,'development_months':['2025-05','2025-08'],
            'time_check_months':['2025-09','2025-10'],'selected_config':candidates[selected],
            'selected_key':selected,'current_key':current,'candidates':[], 'monthly':[]}
    report.update(adopted_key=adopted,adopted_config=candidates[adopted],
                  sampling_sensitivity=sensitivity,
                  development_selected_vs_current_ci=paired_ci,
                  adoption_rule='calibration-only revision; retain s1_w0.5; development-selected intervals are descriptive, not independent selection evidence')
    for key in ranked:
        report['candidates'].append({'key':key,**candidates[key], 'development':metrics(development,key),
                                     'time_check':metrics(check,key)})
    for month,sub in d.groupby('month'):
        report['monthly'].append({'month':month,'period':sub.period.iat[0],
                                  'current':metrics(sub,current),'selected':metrics(sub,selected)})
    report['provenance']={'git_base':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
                          'training_manifest_sha256':hashlib.sha256((out/'training-manifest.json').read_bytes()).hexdigest(),
                          'calibration_revision_proof_sha256':hashlib.sha256((out/'calibration-impact.json').read_bytes()).hexdigest() if reuse else None,
                          'prediction_sha256':hashlib.sha256((out/'rolling-predictions.csv').read_bytes()).hexdigest()}
    (out/'model-evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    # Publish only the frozen completed evaluation, never interim predictions.
    static=Path(os.environ.get('BASEBALL_STATIC_OUT',ROOT/'docs/data'))
    static.mkdir(parents=True,exist_ok=True)
    (static/'model-evaluation.json').write_text(json.dumps(report,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8')
    print('Selected on development:',selected,flush=True)


if __name__=='__main__':main()
