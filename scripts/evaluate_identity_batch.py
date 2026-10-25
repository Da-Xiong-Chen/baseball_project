"""Fixed-configuration retrospective v4/v5 comparison on identical observed PAs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from contextlib import contextmanager

ROOT=Path(__file__).resolve().parents[1]
CORE=['load.py','identity.py','model.py','ml_compare.py','mlmodel.py','batch_contract.py']


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path,data):
    tmp=path.with_suffix('.next');tmp.write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf8');tmp.replace(path)


@contextmanager
def evaluation_lock(folder):
    lock=folder/'evaluation.lock'
    with lock.open('x',encoding='utf8') as stream:stream.write(json.dumps({'pid':os.getpid()}))
    try:yield
    finally:lock.unlink(missing_ok=True)


def validate_month(path,test,expected_sha,aliases,changed):
    import numpy as np
    import pandas as pd
    if digest(path)!=expected_sha:raise ValueError('Checkpoint hash differs: '+str(path))
    frame=pd.read_csv(path)
    fields=['pa_id','game','date','month','team','y','hierarchy','gbt','prediction','batter','pitcher','alias_actor','changed_pa_event_actor']
    if not set(fields)<=set(frame) or frame.pa_id.duplicated().any():raise ValueError('Invalid checkpoint shape: '+str(path))
    if set(frame.pa_id)!=set(test.pa_id):raise ValueError('Checkpoint PA population differs: '+str(path))
    ordered=test.set_index('pa_id').loc[frame.pa_id]
    if not np.allclose(frame.y,ordered.RE24,rtol=0,atol=1e-12):raise ValueError('Checkpoint target differs: '+str(path))
    for field,expected in [('game',ordered.game),('date',ordered.date.astype(str)),('team',ordered.bat_team),
                           ('batter',ordered.batter),('pitcher',ordered.pitcher)]:
        if frame[field].astype(str).tolist()!=expected.astype(str).tolist():raise ValueError('Checkpoint '+field+' differs: '+str(path))
    if not frame.month.eq(path.stem).all():raise ValueError('Checkpoint month differs: '+str(path))
    if not np.isfinite(frame[['y','hierarchy','gbt','prediction']].to_numpy()).all():raise ValueError('Nonfinite checkpoint: '+str(path))
    if not np.allclose(frame.prediction,.5*frame.hierarchy+.5*frame.gbt,rtol=0,atol=1e-12):raise ValueError('Checkpoint ensemble differs')
    for field,expected in [('alias_actor',ordered.batter.isin(aliases).to_numpy()|ordered.pitcher.isin(aliases).to_numpy()),
                           ('changed_pa_event_actor',ordered.index.isin(changed))]:
        actual=frame[field].astype(str).str.lower().map({'true':True,'false':False})
        if actual.isna().any() or not np.array_equal(actual.to_numpy(),expected):raise ValueError('Checkpoint subgroup differs: '+field)
    return frame


def resume_authority(args,version):
    import subprocess
    base=ROOT/'output/identity-integration-20261025'
    frozen=json.loads((base/'baseline-manifest.json').read_text(encoding='utf8'))
    code_root=args.code_root.resolve()
    code={name:digest(code_root/'src'/name) for name in CORE}
    if version==5:
        source=json.loads((base/'training/training-source.json').read_text(encoding='utf8'))
        if code!=source['code']:raise ValueError('Candidate training source changed')
    elif version==4:
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=code_root,text=True).strip()
        dirty=subprocess.check_output(['git','diff','--name-only','HEAD','--','src'],cwd=code_root,text=True).strip()
        if head!=frozen['base'] or dirty:raise ValueError('Baseline code no longer matches frozen checkout')
    else:raise ValueError('Unexpected training version')
    for rel,expected in frozen['raw'].items():
        if digest(code_root/'data/rebas'/rel)!=expected:raise ValueError('Source game changed: '+rel)
    context=json.loads(args.context.read_text(encoding='utf8'))
    if context['training_version']!=version:raise ValueError('Wrong model context version')
    authority={k:v for k,v in context.items() if k!='batch_id'}
    expected=hashlib.sha256(json.dumps(authority,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if context['batch_id']!=expected:raise ValueError('Invalid context identity')
    for row in context['models']:
        if digest(args.models/row['name'])!=row['sha256']:raise ValueError('Weight changed: '+row['name'])
    return {'prediction_contract':'fixed_hierarchy_and_gbt_0.5_v1','training_version':version,'code':code,
            'context_sha256':digest(args.context),'raw_manifest_sha256':digest(base/'baseline-manifest.json')}


def predict(args):
    if args.out.exists() and not args.resume:raise FileExistsError(args.out)
    args.out.mkdir(parents=True,exist_ok=args.resume)
    with evaluation_lock(args.out):return predict_locked(args)


def predict_locked(args):
    for variable in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[variable]='2'
    os.environ['BASEBALL_MODEL_DIR']=str(args.models.resolve())
    os.environ['BASEBALL_BATCH_CONTEXT']=str(args.context.resolve())
    sys.path.insert(0,str(args.code_root.resolve()/'src'))
    import numpy as np
    import pandas as pd
    from load import load
    from model import fit
    import mlmodel
    authority=resume_authority(args,mlmodel.TRAINING_VERSION)
    source_file=args.out/'evaluation-source.json'
    if source_file.exists() and json.loads(source_file.read_text(encoding='utf8'))!=authority:raise ValueError('Evaluation source changed')
    if not source_file.exists():atomic_json(source_file,authority)
    legacy={}
    if args.resume:
        pause=json.loads(args.pause_state.read_text(encoding='utf8'))
        expected_folder=args.pause_state.resolve().parent/('evaluation-v'+str(mlmodel.TRAINING_VERSION))
        if args.out.resolve()!=expected_folder:raise ValueError('Pause checkpoint belongs to another output directory')
        legacy=pause['evaluation']['v'+str(mlmodel.TRAINING_VERSION)]['csv_files']
    pa,p,boxes=load();aliases=set()
    if 'raw_name' in boxes:aliases=set(boxes.groupby('name').raw_name.nunique().loc[lambda s:s>1].index)
    changed=set(p.loc[(p.batter!=p.pa_batter)|(p.pitcher!=p.pa_pitcher),'pa_id']) if 'pa_batter' in p else set()
    all_rows=[];started=time.monotonic()
    months=[f'2025-{m:02d}-01' for m in range(3,12)]
    for start,end in zip(months[:-1],months[1:]):
        test=pa[(pa.date>=start)&(pa.date<end)].dropna(subset=['RE24']).copy()
        if test.empty:continue
        checkpoint=args.out/(start[:7]+'.csv');proof=checkpoint.with_suffix('.receipt.json')
        if checkpoint.exists():
            expected_sha=None
            if proof.exists():
                sealed=json.loads(proof.read_text(encoding='utf8'))
                if sealed['authority']!=authority:raise ValueError('Month authority differs')
                expected_sha=sealed['sha256']
            elif legacy.get(checkpoint.name,{}).get('at_or_before_last_completed_month'):
                expected_sha=legacy[checkpoint.name]['sha256']
            if expected_sha:
                frame=validate_month(checkpoint,test,expected_sha,aliases,changed);all_rows.append(frame)
                if not proof.exists():atomic_json(proof,{'sha256':expected_sha,'rows':len(frame),'authority':authority})
                print(start,len(frame),'PAs; validated checkpoint reused',flush=True)
                continue
            quarantine=args.out/'unsealed';quarantine.mkdir(exist_ok=True)
            target=quarantine/(checkpoint.name+'.'+digest(checkpoint)[:12])
            if target.exists():raise FileExistsError(target)
            checkpoint.rename(target)
        hm=fit(start);gm=mlmodel.get(start)
        keys=list(dict.fromkeys(test[['batter','bhand','pitcher']].itertuples(index=False,name=None)))
        hierarchy=np.asarray([hm.matchup(*q)['per_pa'] for q in keys]);tree=[]
        for begin in range(0,len(keys),128):tree.extend(gm.abs_many(keys[begin:begin+128]))
        lookup={q:i for i,q in enumerate(keys)}
        indices=np.array([lookup[q] for q in test[['batter','bhand','pitcher']].itertuples(index=False,name=None)])
        h=hierarchy[indices];g=np.asarray(tree)[indices]
        frame=pd.DataFrame({'pa_id':test.pa_id.to_numpy(),'game':test.game.to_numpy(),'date':test.date.astype(str).to_numpy(),
            'month':start[:7],'team':test.bat_team.to_numpy(),'y':test.RE24.to_numpy(),
            'hierarchy':h,'gbt':g,'prediction':.5*h+.5*g,'batter':test.batter.to_numpy(),'pitcher':test.pitcher.to_numpy(),
            'alias_actor':test.batter.isin(aliases).to_numpy()|test.pitcher.isin(aliases).to_numpy(),
            'changed_pa_event_actor':test.pa_id.isin(changed).to_numpy()})
        temp=checkpoint.with_suffix('.next');frame.to_csv(temp,index=False);temp.rename(checkpoint);all_rows.append(frame)
        atomic_json(proof,{'sha256':digest(checkpoint),'rows':len(frame),'authority':authority})
        atomic_json(args.out/'progress.json',{'status':'running','pid':os.getpid(),'completed_month':start,'rows':sum(len(x) for x in all_rows)})
        print(start,len(test),'PAs',len(keys),'matchups',flush=True)
    combined=pd.concat(all_rows,ignore_index=True)
    final=args.out/'predictions.csv'
    if final.exists():
        saved=json.loads((args.out/'receipt.json').read_text(encoding='utf8'))
        if saved['predictions_sha256']!=digest(final) or saved['context_sha256']!=digest(args.context):raise ValueError('Final predictions changed')
        print('Complete existing evaluation verified; no recalculation',flush=True);return
    combined.to_csv(final,index=False)
    receipt={'status':'complete','training_version':mlmodel.TRAINING_VERSION,'rows':len(combined),
        'months':sorted(combined.month.unique()),'ensemble_weight':.5,'evaluation':'retrospective_same_observed_PA_not_new_holdout',
        'predictions_sha256':hashlib.sha256((args.out/'predictions.csv').read_bytes()).hexdigest(),
        'context_sha256':hashlib.sha256(args.context.read_bytes()).hexdigest(),'authority':authority,
        'elapsed_seconds':round(time.monotonic()-started,3)}
    (args.out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
    (args.out/'progress.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
    print(json.dumps(receipt),flush=True)


def compare(args):
    import numpy as np
    import pandas as pd
    old=pd.read_csv(args.baseline/'predictions.csv');new=pd.read_csv(args.candidate/'predictions.csv')
    for folder,frame in ((args.baseline,old),(args.candidate,new)):
        receipt=json.loads((folder/'receipt.json').read_text(encoding='utf8'))
        if receipt['status']!='complete' or receipt['rows']!=len(frame) or receipt['predictions_sha256']!=hashlib.sha256((folder/'predictions.csv').read_bytes()).hexdigest():raise ValueError('unsealed predictions')
    paired=old.merge(new,on='pa_id',validate='one_to_one',suffixes=('_old','_new'),how='outer',indicator=True)
    if (paired._merge!='both').any() or not np.allclose(paired.y_old,paired.y_new,atol=0,rtol=0):raise ValueError('PA population or target changed')
    if not np.isfinite(paired[['prediction_old','prediction_new','y_old']].to_numpy()).all():raise ValueError('nonfinite prediction')
    def metrics(frame):
        target=frame.y_old.to_numpy();a=frame.prediction_old.to_numpy();b=frame.prediction_new.to_numpy()
        mse=[float(np.mean((x-target)**2)) for x in (a,b)];mae=[float(np.mean(abs(x-target))) for x in (a,b)]
        return {'n':len(frame),'mse_v4':mse[0],'mse_v5':mse[1],'mse_relative_change':mse[1]/mse[0]-1,
                'mae_v4':mae[0],'mae_v5':mae[1],'mae_relative_change':mae[1]/mae[0]-1,
                'mean_error_v4':float(np.mean(a-target)),'mean_error_v5':float(np.mean(b-target)),
                'mean_absolute_prediction_shift':float(np.mean(abs(a-b))),'max_absolute_prediction_shift':float(np.max(abs(a-b)))}
    overall=metrics(paired);monthly={month:metrics(frame) for month,frame in paired.groupby('month_new')}
    subgroups={}
    for field in ('alias_actor_new','changed_pa_event_actor_new'):
        rows=paired[paired[field].astype(bool)]
        if len(rows):subgroups[field]=metrics(rows)
    grouped=pd.DataFrame({'game':paired.game_new,'difference':(paired.prediction_old-paired.y_old)**2-(paired.prediction_new-paired.y_new)**2,'n':1}).groupby('game').sum().to_numpy()
    rng=np.random.default_rng(20261025);draws=[]
    for _ in range(2000):
        sums=grouped[rng.integers(0,len(grouped),len(grouped))].sum(axis=0);draws.append(sums[0]/sums[1])
    triggers=[]
    for metric in ('mse_relative_change','mae_relative_change'):
        if overall[metric]>.01:triggers.append({'scope':'overall','metric':metric,'relative_change':overall[metric]})
        for month,row in monthly.items():
            if row[metric]>.03:triggers.append({'scope':month,'metric':metric,'relative_change':row[metric]})
    report={'status':'compared','evaluation':'retrospective_correction_audit_not_new_independent_holdout',
            'target':'observed_single_PA_RE24','ensemble_weight':.5,'overall':overall,'monthly':monthly,'subgroups':subgroups,
            'team':{team:metrics(frame) for team,frame in paired.groupby('team_new')},
            'paired_game_bootstrap_mse_reduction_ci':np.quantile(draws,[.025,.975]).tolist(),
            'seed':20261025,'bootstrap_reps':2000,'review_triggers':triggers,'requires_investigation':bool(triggers),
            'data_correctness_approval_is_separate':True,'model_automatically_adopted':False}
    if args.out.exists():raise FileExistsError(args.out)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    print(json.dumps(report,ensure_ascii=True,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    p=sub.add_parser('predict');p.add_argument('--code-root',type=Path,required=True);p.add_argument('--models',type=Path,required=True);p.add_argument('--context',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--resume',action='store_true');p.add_argument('--pause-state',type=Path,default=ROOT/'output/identity-integration-20261025/pause-state-1920.json')
    p=sub.add_parser('compare');p.add_argument('--baseline',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();predict(args) if args.command=='predict' else compare(args)
