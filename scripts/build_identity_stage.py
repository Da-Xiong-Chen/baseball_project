"""Resumable staging exports, isolated from docs/data and active models.

Receipts bind each completed step to executable source, weights and input hashes.
Changed source invalidates receipts instead of silently reusing stale output.
"""
import hashlib,json,os,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/identity-integration-20261025'
STAGE=OUT/'staging-site'

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    STAGE.mkdir(exist_ok=True);(STAGE/'data').mkdir(exist_ok=True)
    # Staging starts with assets only; no legacy generated data is copied.
    for path in (ROOT/'docs').iterdir():
        if path.is_file():shutil.copy2(path,STAGE/path.name)
        elif path.is_dir() and path.name!='data':
            shutil.copytree(path,STAGE/path.name,dirs_exist_ok=True)
    env=dict(os.environ,BASEBALL_MODEL_DIR=str(OUT/'candidate-models'),
        BASEBALL_BATCH_CONTEXT=str(OUT/'candidate-context.json'),BASEBALL_STATIC_OUT=str(STAGE/'data'),
        BASEBALL_REPORT_OUT=str(OUT/'verification'),OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2')
    logs=OUT/'exports';logs.mkdir(exist_ok=True)
    authority={str(p.relative_to(ROOT)):digest(p) for folder in ('src','scripts') for p in (ROOT/folder).glob('*.py')}
    authority['context']=digest(OUT/'candidate-context.json')
    authority['raw']=digest(OUT/'identity-store-manifest.json')
    token=hashlib.sha256(json.dumps(authority,sort_keys=True).encode()).hexdigest()
    steps=[('model-replays',['src/export_static.py']),('daily',['scripts/export_history_day.py']),
        ('history-context',['scripts/export_history_context.py']),('lineups',['scripts/export_default_lineups.py']),
        ('fielding',['scripts/export_fielding_plans.py','--out',str(STAGE/'data/fielding-plans-2025-09-20.json')]),
        ('auxiliary',['scripts/export_identity_auxiliary.py']),('pitch-change',['src/export_pitch_change.py']),
        ('timing',['src/timing_backtest.py','4'])]
    for name,args in steps:
        receipt=logs/(name+'.json')
        if receipt.exists():
            saved=json.loads(receipt.read_text(encoding='utf8'))
            if saved['authority']!=token:raise ValueError('Export source changed: use a new output stage or inspect '+name)
            for rel,sha in saved['files'].items():
                if digest(STAGE/'data'/rel)!=sha:raise ValueError('Export changed: '+rel)
            print('Verified completed '+name,flush=True);continue
        before={p.relative_to(STAGE/'data').as_posix():digest(p) for p in (STAGE/'data').rglob('*.json')}
        started=time.time();print('Starting '+name,flush=True)
        with (logs/(name+'.log')).open('w',encoding='utf8') as log:
            result=subprocess.run([sys.executable,'-X','utf8',*args],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError(name+' failed; inspect '+str(logs/(name+'.log')))
        after={p.relative_to(STAGE/'data').as_posix():digest(p) for p in (STAGE/'data').rglob('*.json')}
        receipt.write_text(json.dumps(dict(authority=token,elapsed_seconds=time.time()-started,
            files={key:value for key,value in after.items() if before.get(key)!=value}),indent=2),encoding='utf8')
        print('Completed '+name,flush=True)
    print('Exports complete; staging is not yet approved for publication',flush=True)

if __name__=='__main__':main()
