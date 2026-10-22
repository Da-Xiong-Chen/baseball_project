"""Create a separate v4 batch; never overwrite v3 or retrain unchanged trees."""
from pathlib import Path
import hashlib,json,os,pickle,platform,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import mlmodel,numpy,sklearn
from load import load


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    out=ROOT/'output/revision-20261021';out.mkdir(exist_ok=True,parents=True)
    dest=ROOT/'models/revision-20261021';dest.mkdir(exist_ok=True)
    pa=load()[0];records=[];experiments=[]
    sources=[*sorted((ROOT/'models').glob('gbt_*_v3.pkl')),
             *sorted((ROOT/'models/closeout-candidate').glob('regularized_v3_*.pkl'))]
    for source in sources:
        started=time.time();target=dest/source.name.replace('_v3','_v4')
        if target.exists():
            with target.open('rb') as f:corrected=pickle.load(f)
        else:
            with source.open('rb') as f:old=mlmodel._Unpickler(f).load()
            corrected=mlmodel.recalibrate(old,pa)
            assert pickle.dumps(old.sim.models)==pickle.dumps(corrected.sim.models)
            with target.open('wb') as f:pickle.dump(corrected,f)
        row={'cutoff':corrected.cutoff,'name':target.name,'sha256':sha(target),
             'source_v3_sha256':sha(source),'training_version':4,
             'reference':corrected.calibration_reference}
        (experiments if source.name.startswith('regularized') else records).append(row)
        print(target.name, row['reference']['first_date'],row['reference']['last_date'],
              f'{time.time()-started:.1f}s',flush=True)
    assert len(records)==9 and len(experiments)==6
    manifest={'schema_version':2,'training_version':4,'engine_contract':4,
              'python':platform.python_version(),'numpy':numpy.__version__,'sklearn':sklearn.__version__,
              'input_audit_sha256':sha(ROOT/'output/closeout/input-audit.json'),
              'models':records,'experiments':experiments,'policy':'reuse_identical_trees_recalibrate_only'}
    # The identity is a hash of frozen model artifacts and their input lineage.
    manifest['batch_id']=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    (out/'training-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print('Batch:',manifest['batch_id'],flush=True)


if __name__=='__main__':main()
