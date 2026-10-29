"""Checkpointed isolated v5 training, bounded workers and immutable job receipts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
CUTOFFS=[f'2025-{month:02d}-01' for month in range(3,11)]+['2026-01-01']
CODE=['load.py','identity.py','model.py','ml_compare.py','mlmodel.py','batch_contract.py']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path,data):
    temp=path.with_suffix('.next')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    temp.replace(path)


def name(cutoff):
    return 'gbt_full_v5.pkl' if cutoff=='2026-01-01' else f'gbt_{cutoff[:7]}_v5.pkl'


def pid_running(pid):
    if os.name=='nt':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_bool,ctypes.c_ulong]
        kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x1000,False,int(pid))
        if not handle:return ctypes.get_last_error()==5
        try:
            code=ctypes.c_ulong()
            return not kernel.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value==259
        finally:kernel.CloseHandle(handle)
    try:os.kill(int(pid),0);return True
    except ProcessLookupError:return False
    except PermissionError:return True


def worker(args):
    for variable in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[variable]=str(args.threads)
    os.environ['BASEBALL_MODEL_DIR']=str(args.models.resolve())
    sys.path.insert(0,str(ROOT/'src'))
    import mlmodel
    started=time.monotonic()
    model=mlmodel.train(args.worker)
    model.training_source_id=args.source_id
    target=args.models/name(args.worker)
    if target.exists():raise FileExistsError('Refusing to overwrite '+str(target))
    temp=target.with_suffix('.partial')
    with temp.open('xb') as stream:pickle.dump(model,stream,pickle.HIGHEST_PROTOCOL)
    temp.rename(target)
    record={'cutoff':args.worker,'name':target.name,'training_version':5,'engine_contract':5,
            'sha256':digest(target),'source_id':args.source_id,'threads':args.threads,
            'training_samples':model.training_samples,'reference':model.calibration_reference,
            'elapsed_seconds':round(time.monotonic()-started,3),'status':'complete'}
    atomic_json(args.reports/(target.stem+'.json'),record)
    print(json.dumps(record,ensure_ascii=True),flush=True)


def controller(args):
    args.models=args.models.resolve();args.reports=args.reports.resolve()
    for folder in (args.models,args.reports):
        if not folder.is_relative_to(ROOT/'output'):raise ValueError('Use isolated output/ directories')
        if folder.exists() and not args.resume:raise FileExistsError('Use --resume with a matching immutable source: '+str(folder))
        folder.mkdir(parents=True,exist_ok=True)
    lock=args.reports/'controller.lock'
    with lock.open('x',encoding='utf8') as stream:stream.write(str(os.getpid()))
    try:
        spec=ROOT/'output/identity-integration-20261025/execution-spec.json'
        baseline=ROOT/'output/identity-integration-20261025/baseline-manifest.json'
        authority={'code':{f:digest(ROOT/'src'/f) for f in CODE},'spec':digest(spec),
                   'raw':json.loads(baseline.read_text(encoding='utf8'))['raw'],'seed':0,
                   'driver_sha256':digest(Path(__file__))}
        source_id=hashlib.sha256(json.dumps(authority,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        authority_path=args.reports/'training-source.json'
        if authority_path.exists():
            old=json.loads(authority_path.read_text(encoding='utf8'))
            if old['source_id']!=source_id:raise ValueError('Training source changed; choose new output directories')
        else:atomic_json(authority_path,{'source_id':source_id,**authority})
        old_progress=args.reports/'progress.json'
        if old_progress.exists():
            old=json.loads(old_progress.read_text(encoding='utf8'))
            live=[row['pid'] for row in old.get('jobs',{}).values()
                  if row.get('status')=='running' and pid_running(row['pid'])]
            if live:raise RuntimeError(f'Existing worker PIDs still active; inspect them before resuming: {live}')
        jobs=[args.cutoff] if args.cutoff else CUTOFFS
        state={'controller_pid':os.getpid(),'source_id':source_id,'max_workers':args.workers,
               'threads_per_worker':args.threads,'status':'running','jobs':{}}
        pending=[]
        for cutoff in jobs:
            target=args.models/name(cutoff);receipt=args.reports/(target.stem+'.json')
            if receipt.exists():
                row=json.loads(receipt.read_text(encoding='utf8'))
                if row['source_id']!=source_id or row['sha256']!=digest(target):raise ValueError('Invalid checkpoint '+str(target))
                state['jobs'][cutoff]={'status':'complete','receipt':receipt.name,'reused':True}
            else:
                if target.exists() or target.with_suffix('.partial').exists():raise ValueError('Unsealed partial model needs inspection: '+str(target))
                pending.append(cutoff);state['jobs'][cutoff]={'status':'pending'}
        atomic_json(args.reports/'progress.json',state)
        processes={}
        def launch(cutoff):
            command=[sys.executable,str(Path(__file__).resolve()),'--worker',cutoff,'--models',str(args.models),
                     '--reports',str(args.reports),'--source-id',source_id,'--threads',str(args.threads)]
            log=args.reports/(name(cutoff)+'.log')
            attempt=1
            while log.exists():
                log=args.reports/(name(cutoff)+f'.attempt-{attempt}.log');attempt+=1
            with log.open('xb') as stream:
                process=subprocess.Popen(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                processes[cutoff]=process
                return cutoff,process
        # The controller alone writes the shared progress journal. Worker
        # receipts and model paths are unique per cutoff.
        active={}
        while pending or active:
            while pending and len(active)<args.workers:
                cutoff=pending.pop(0);_,process=launch(cutoff);active[cutoff]=process
                state['jobs'][cutoff]={'status':'running','pid':process.pid}
                atomic_json(args.reports/'progress.json',state)
            for cutoff,process in list(active.items()):
                code=process.poll()
                if code is not None:
                    state['jobs'][cutoff]={'status':'complete' if code==0 else 'failed','pid':process.pid,'exit_code':code}
                    del active[cutoff];atomic_json(args.reports/'progress.json',state)
            if any(row['status']=='failed' for row in state['jobs'].values()):
                # Let already running jobs finish and preserve their receipts;
                # do not start further jobs after a failure.
                for cutoff in pending:state['jobs'][cutoff]={'status':'not_started_after_failure'}
                pending=[]
            if active:time.sleep(1)
        state['status']='complete' if all(r['status']=='complete' for r in state['jobs'].values()) else 'failed'
        atomic_json(args.reports/'progress.json',state)
        if state['status']!='complete':raise RuntimeError('Training failed; inspect per-cutoff logs')
        models=[json.loads((args.reports/(Path(name(c)).stem+'.json')).read_text(encoding='utf8')) for c in jobs]
        atomic_json(args.reports/('benchmark-manifest.json' if args.cutoff else 'training-manifest.json'),
                    {'schema_version':3,'training_version':5,'engine_contract':5,'source_id':source_id,'models':models,'status':'complete'})
        print(json.dumps({'status':'complete','models':len(models),'source_id':source_id}),flush=True)
    finally:
        lock.unlink(missing_ok=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--models',type=Path,required=True);ap.add_argument('--reports',type=Path,required=True)
    ap.add_argument('--workers',type=int,default=6);ap.add_argument('--threads',type=int,default=2)
    ap.add_argument('--cutoff',choices=CUTOFFS);ap.add_argument('--resume',action='store_true')
    ap.add_argument('--worker',choices=CUTOFFS);ap.add_argument('--source-id')
    a=ap.parse_args()
    if not 1<=a.workers<=6 or not 1<=a.threads<=4:ap.error('workers 1..6; threads 1..4')
    if not a.worker and a.workers*a.threads>12:ap.error('Use at most 12 total worker threads to preserve desktop capacity')
    worker(a) if a.worker else controller(a)
