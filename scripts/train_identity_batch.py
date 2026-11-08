"""Checkpointed isolated v5 training, bounded workers and immutable job receipts."""
import argparse
import hashlib
from importlib.metadata import version
import platform
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
import time
from training_source import verify_source, create_manifest, snapshot, fingerprint

ROOT=Path(__file__).resolve().parents[1]
CUTOFFS=[f'2025-{month:02d}-01' for month in range(3,11)]+['2026-01-01']
SPEC=ROOT/'config/training-v5.json'


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


def source_authority(args):
    spec=json.loads(SPEC.read_text(encoding='utf8'))
    if (spec.get('schema_version')!=1 or spec.get('training_version')!=5 or spec.get('engine_contract')!=5
            or spec.get('seed')!=0 or spec.get('data_seasons')!=[2024,2025] or spec.get('cutoffs')!=CUTOFFS):
        raise ValueError('Unsupported training spec; this entry point trains the fixed v5 season contract')
    sys.path.insert(0,str(ROOT/'src'))
    from runtime_config import settings, DEFAULT
    if settings()!=DEFAULT:raise ValueError('This training entry point requires the default v5 runtime')
    manifest=verify_source(args.data_root,args.source_manifest,spec['data_seasons'])
    code={p.relative_to(ROOT).as_posix():digest(p) for p in sorted((ROOT/'src').glob('*.py'))}
    for path in (Path(__file__).resolve(), ROOT/'scripts/training_source.py'):
        code[path.relative_to(ROOT).as_posix()]=digest(path)
    authority={'schema':'baseball.training-authority.v2','code':code,'spec':digest(SPEC),
               'input':manifest,'seed':spec['seed'],'runtime':DEFAULT.payload(),
               'requirements_sha256':digest(ROOT/'requirements.txt'),
               'environment':{'python':platform.python_version(),
                              'packages':{name:version(name) for name in ('numpy','pandas','scipy','scikit-learn')}}}
    return authority, fingerprint(authority)


def output_paths(args, allow_snapshot=False):
    args.models=args.models.resolve();args.reports=args.reports.resolve()
    for folder in (args.models,args.reports):
        if not folder.is_relative_to(ROOT/'output') or folder==ROOT/'output':
            raise ValueError('Use isolated output/ subdirectories')
    if args.models==args.reports or args.models in args.reports.parents or args.reports in args.models.parents:
        raise ValueError('Model and report directories must be separate')
    data=args.data_root.resolve()
    is_private_snapshot=allow_snapshot and data==args.reports/'input-snapshot'
    if not is_private_snapshot and any(folder==data or folder in data.parents or data in folder.parents for folder in (args.models,args.reports)):
        raise ValueError('Training outputs must be separate from source data')


def worker(args):
    output_paths(args,allow_snapshot=True)
    authority,source_id=source_authority(args)
    frozen=json.loads((args.reports/'training-source.json').read_text(encoding='utf8'))
    if source_id!=args.source_id or frozen!={'source_id':source_id,**authority}:
        raise ValueError('Worker source differs from controller authority')
    for variable in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[variable]=str(args.threads)
    os.environ['BASEBALL_MODEL_DIR']=str(args.models.resolve())
    os.environ['BASEBALL_DATA_ROOT']=str(args.data_root.resolve())
    sys.path.insert(0,str(ROOT/'src'))
    import mlmodel
    started=time.monotonic()
    model=mlmodel.train(args.worker)
    if source_authority(args)[1]!=source_id:raise ValueError('Training source changed during worker execution')
    model.training_source_id=source_id
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
    output_paths(args)
    authority,source_id=source_authority(args)
    if args.dry_run:
        print(json.dumps({'status':'validated_only','training_started':False,'source_id':source_id,
                          'dataset_id':authority['input']['dataset_id'],'files':len(authority['input']['files']),
                          'cutoffs':[args.cutoff] if args.cutoff else CUTOFFS},ensure_ascii=True))
        return
    for folder in (args.models,args.reports):
        if folder.exists() and not args.resume:raise FileExistsError('Use --resume with a matching immutable source: '+str(folder))
        folder.mkdir(parents=True,exist_ok=True)
    lock=args.reports/'controller.lock'
    with lock.open('x',encoding='utf8') as stream:stream.write(str(os.getpid()))
    try:
        authority_path=args.reports/'training-source.json'
        if authority_path.exists():
            old=json.loads(authority_path.read_text(encoding='utf8'))
            if old['source_id']!=source_id:raise ValueError('Training source changed; choose new output directories')
        else:atomic_json(authority_path,{'source_id':source_id,**authority})
        frozen_manifest=args.reports/'training-input.json'
        if frozen_manifest.exists():
            if json.loads(frozen_manifest.read_text(encoding='utf8'))!=authority['input']:
                raise ValueError('Frozen training input differs')
        else:atomic_json(frozen_manifest,authority['input'])
        input_snapshot=snapshot(args.data_root,frozen_manifest,authority['input']['seasons'],args.reports/'input-snapshot')
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
                if (row['source_id']!=source_id or row.get('cutoff')!=cutoff or row.get('name')!=target.name
                        or row.get('training_version')!=5 or row.get('engine_contract')!=5 or row.get('status')!='complete'
                        or row['sha256']!=digest(target)):raise ValueError('Invalid checkpoint '+str(target))
                state['jobs'][cutoff]={'status':'complete','receipt':receipt.name,'reused':True}
            else:
                if target.exists() or target.with_suffix('.partial').exists():raise ValueError('Unsealed partial model needs inspection: '+str(target))
                pending.append(cutoff);state['jobs'][cutoff]={'status':'pending'}
        atomic_json(args.reports/'progress.json',state)
        processes={}
        def launch(cutoff):
            command=[sys.executable,str(Path(__file__).resolve()),'--worker',cutoff,'--models',str(args.models),
                     '--reports',str(args.reports),'--source-id',source_id,'--threads',str(args.threads),
                     '--data-root',str(input_snapshot),'--source-manifest',str(frozen_manifest)]
            log=args.reports/(name(cutoff)+'.log')
            attempt=1
            while log.exists():
                log=args.reports/(name(cutoff)+f'.attempt-{attempt}.log');attempt+=1
            with log.open('xb') as stream:
                process=subprocess.Popen(command,cwd=ROOT,env={**os.environ,'PYTHONHASHSEED':'0'},stdout=stream,stderr=subprocess.STDOUT,
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
        if source_authority(args)[1]!=source_id:raise ValueError('Source changed while training; no complete batch published')
        verify_source(input_snapshot,frozen_manifest,authority['input']['seasons'])
        state['status']='complete' if all(r['status']=='complete' for r in state['jobs'].values()) else 'failed'
        atomic_json(args.reports/'progress.json',state)
        if state['status']!='complete':raise RuntimeError('Training failed; inspect per-cutoff logs')
        models=[json.loads((args.reports/(Path(name(c)).stem+'.json')).read_text(encoding='utf8')) for c in jobs]
        atomic_json(args.reports/('benchmark-manifest.json' if args.cutoff else 'training-manifest.json'),
                    {'schema_version':3,'training_version':5,'engine_contract':5,'source_id':source_id,'models':models,'status':'complete','runtime_id':fingerprint(authority['runtime'])})
        print(json.dumps({'status':'complete','models':len(models),'source_id':source_id}),flush=True)
    finally:
        lock.unlink(missing_ok=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--models',type=Path);ap.add_argument('--reports',type=Path)
    ap.add_argument('--data-root',type=Path,default=ROOT/'data');ap.add_argument('--source-manifest',type=Path,required=True)
    ap.add_argument('--prepare-source',action='store_true');ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--workers',type=int,default=6);ap.add_argument('--threads',type=int,default=2)
    ap.add_argument('--cutoff',choices=CUTOFFS);ap.add_argument('--resume',action='store_true')
    ap.add_argument('--worker',choices=CUTOFFS);ap.add_argument('--source-id')
    a=ap.parse_args()
    if a.prepare_source:
        if a.worker or a.dry_run:ap.error('prepare-source cannot be combined with worker or dry-run')
        manifest=create_manifest(a.data_root,[2024,2025],a.source_manifest)
        print(json.dumps({'status':'prepared_only','dataset_id':manifest['dataset_id'],'files':len(manifest['files'])}));sys.exit(0)
    if not a.models or not a.reports:ap.error('--models and --reports are required for dry-run or training')
    if a.worker and (not a.source_id or a.dry_run):ap.error('workers require a controller source-id and cannot dry-run')
    if not 1<=a.workers<=6 or not 1<=a.threads<=4:ap.error('workers 1..6; threads 1..4')
    if not a.worker and a.workers*a.threads>12:ap.error('Use at most 12 total worker threads to preserve desktop capacity')
    worker(a) if a.worker else controller(a)
