"""Explicitly train a new isolated v4 batch; never overwrite active weights."""
import argparse,hashlib,json,os,platform,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--models',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();dest=a.models.resolve();out=a.output.resolve()
    for p in (dest,out):
        if not p.is_relative_to(ROOT) or p.exists():raise ValueError('Use new directories inside this repository')
    dest.mkdir(parents=True);out.mkdir(parents=True)
    os.environ['BASEBALL_MODEL_DIR']=str(dest)
    import mlmodel,numpy,sklearn
    manifest=dict(schema_version=2,training_version=4,engine_contract=4,python=platform.python_version(),
        numpy=numpy.__version__,sklearn=sklearn.__version__,models=[],experiments=[],policy='explicit_retrain')
    def record(model,path):
        return dict(cutoff=model.cutoff,name=path.name,training_version=4,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),reference=model.calibration_reference)
    for cutoff in [*mlmodel.REPLAY_MONTHS,mlmodel.FULL]:
        model=mlmodel.get(cutoff,train_missing=True);path=Path(mlmodel.path_for(cutoff))
        manifest['models'].append(record(model,path));print('Completed '+cutoff,flush=True)
    import pickle
    for month in ['05','06','07','08','09','10']:
        model=mlmodel.train('2025-'+month+'-01',{'max_leaf_nodes':15,'l2_regularization':3.0})
        path=dest/('regularized_v4_2025-'+month+'.pkl')
        with path.open('wb') as f:pickle.dump(model,f)
        manifest['experiments'].append(record(model,path))
    manifest['batch_id']=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    (out/'training-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print('Frozen context: '+str(out/'training-manifest.json'),flush=True)

if __name__=='__main__':main()
