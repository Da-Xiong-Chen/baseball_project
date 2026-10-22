"""Seal new batches explicitly; read-only verification; journaled promotion."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from prepare_site import inspect_site,read_json

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def scoped(p):
    p=Path(p).resolve()
    if not p.is_relative_to(ROOT.resolve()) or p==ROOT.resolve():raise ValueError('Path escapes workspace')
    return p

def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.writing')
    with tmp.open('w',encoding='utf8') as f:
        json.dump(data,f,ensure_ascii=False,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
    tmp.replace(path)

def contract(r,label,expected=None):
    if r.get('training_version')!=4 or r.get('engine_contract')!=4 or not r.get('batch_id'):
        raise ValueError('Mixed or incomplete batch: '+label)
    if expected and r['batch_id']!=expected:raise ValueError('Different batch identity: '+label)

def context_identity(c):
    authority={k:v for k,v in c.items() if k!='batch_id'}
    expected=hashlib.sha256(json.dumps(authority,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if c.get('batch_id')!=expected:raise ValueError('Invalid training authority')
    contract(c,'training authority');return expected

def verify_weights(folder,c,active=False):
    context_identity(c)
    for row in c['models']:
        if Path(row['name']).name!=row['name']:raise ValueError('Invalid model name')
        if digest(Path(folder)/row['name'])!=row['sha256']:raise ValueError('Active weight checksum differs: '+row['name'])
    if active and read_json(Path(folder)/'active-batch.json')!=c:raise ValueError('Active model batch differs')

def validate_data(site,c):
    data=Path(site)/'data';identity=context_identity(c)
    for name in ('model.json','timing-2025.json','model-evaluation.json'):contract(read_json(data/name),name,identity)
    timing=read_json(data/'timing-2025.json');total=sum(map(len,timing['games'].values()))
    if timing['schema_version']!=2 or timing['coverage']!={'attempted':total,'successful':total,'errors':0}:
        raise ValueError('Timing population incomplete')
    for summary in timing['summary'].values():
        for row in summary.values():
            if row['n']+row['excluded']!=total or sum(row[k] for k in ('both','sys_only','actual_only','neither'))!=row['n']:
                raise ValueError('Invalid timing denominator')
    e=read_json(data/'model-evaluation.json')
    if e['status']!='evaluated' or e['adopted_config']!={'hierarchy_scale':1,'gbt_weight':.5,'tree_variant':'current'}:
        raise ValueError('Adopted configuration needs engine review')
    count=0
    for game in read_json(data/'replay/games.json'):
        payload=read_json(data/'replay'/f"{game['game']}.json");contract(payload,'game',identity)
        for pid,r in payload['results'].items():contract(r,pid,identity);count+=1
    if count!=498:raise ValueError('Incomplete original replay population')
    day=data/'replay/day-2025-09-20';index=read_json(day/'index.json');contract(index,'day index',identity)
    if index['pa_count']!=226 or len(index['files'])!=226 or len(index['games'])!=3:raise ValueError('Incomplete fixed day')
    for pid,name in index['files'].items():
        if Path(name).name!=name or digest(day/name)!=index['sha256'][pid]:raise ValueError('Changed daily replay')
        b=read_json(day/name);contract(b,pid,identity)
        for key in ('ph','pen'):
            if b[key] is not None:contract(b[key],pid+'/'+key,identity)
    for p in (data/'pitch-change').glob('*/index.json'):
        used=set(read_json(p)['pitchers'].values())|{'index.json'}
        if {f.name for f in p.parent.glob('*.json')}-used:raise ValueError('Unreferenced pitch data')
    inspect_site(Path(site));return {'timing_decisions':total,'replay_cases':count,'fixed_day_pa':226}

def source_hashes():
    files=[ROOT/'server.py']+[p for folder in ('src','docs','scripts') for p in (ROOT/folder).glob('*') if p.suffix in ('.py','.js','.css','.html')]
    return {p.relative_to(ROOT).as_posix():digest(p) for p in files}

def seal(site,c,weights,receipts):
    site=scoped(site);target=site/'data/batch-manifest.json'
    if target.exists():raise ValueError('Already sealed; use a new staging batch')
    verify_weights(weights,c);counts=validate_data(site,c)
    if set(receipts)!={'decisions','history_day','timing','calibration'}:raise ValueError('Missing numerical receipts')
    for key,path in receipts.items():
        r=read_json(path)
        if r.get('batch_id')!=c['batch_id'] or r.get('passed') is not True:raise ValueError('Unverified receipt: '+key)
    files={p.relative_to(site).as_posix():digest(p) for p in inspect_site(site) if p!=target}
    m={'schema_version':2,'training':c,'files':files,'source_sha256':source_hashes(),
       'verification':{k:read_json(v) for k,v in receipts.items()},**counts}
    atomic_json(target,m);return m

def verify_manifest(site,weights=None,active=False,verify_source=True):
    site=Path(site);m=read_json(site/'data/batch-manifest.json')
    if m.get('schema_version')!=2:raise ValueError('Unsealed or legacy manifest')
    context_identity(m['training']);expected=m['files']
    actual={p.relative_to(site).as_posix() for p in inspect_site(site) if p!=site/'data/batch-manifest.json'}
    if actual!=set(expected):raise ValueError('Batch file set changed')
    for name,sha in expected.items():
        p=(site/name).resolve()
        if not p.is_relative_to(site.resolve()) or digest(p)!=sha:raise ValueError('Batch checksum mismatch: '+name)
    if verify_source:
        if source_hashes()!=m['source_sha256']:raise ValueError('Source changed after sealing')
        for name,sha in m['source_sha256'].items():
            if digest(ROOT/name)!=sha:raise ValueError('Source changed after sealing: '+name)
    if weights is not None:verify_weights(weights,m['training'],active)
    validate_data(site,m['training']);return m

def recover(journal=None):
    journal=Path(journal or ROOT/'output/promotion-journal.json')
    if not journal.exists():return False
    r=read_json(journal);target,stage,backup=[scoped(r[k]) for k in ('target','stage','site_backup')]
    if r['phase']=='committed':
        verify_manifest(target,ROOT/'models',active=True);journal.unlink();return True
    # Restore every planned target: a process may die before recording progress.
    for row in r['weights']:
        dest,old=[scoped(row[k]) for k in ('target','backup')]
        partial=dest.with_suffix('.next')
        if partial.exists():
            held=scoped(Path(r['backup'])/'partial-weights'/partial.name);held.parent.mkdir(parents=True,exist_ok=True);partial.replace(held)
        if row['existed']:
            tmp=dest.with_suffix('.restore');shutil.copy2(old,tmp);tmp.replace(dest)
        elif dest.exists():
            failed=scoped(Path(r['backup'])/'failed-weights'/dest.name);failed.parent.mkdir(parents=True,exist_ok=True);dest.replace(failed)
    if backup.exists():
        if target.exists():
            if stage.exists():raise RuntimeError('Recovery stage conflict; journal preserved')
            target.rename(stage)
        backup.rename(target)
    journal.unlink();return True

def promote_revision(stage,weights,backup,hook=lambda _:None):
    stage,weights,backup=map(scoped,(stage,weights,backup));m=verify_manifest(stage,weights)
    target=scoped(ROOT/'docs');journal=ROOT/'output/promotion-journal.json'
    if journal.exists():raise ValueError('Recover unfinished promotion first')
    if backup.exists():raise ValueError('Backup already exists')
    backup.mkdir(parents=True);prepared=backup/'prepared';prepared.mkdir();rows=[]
    for row in m['training']['models']:
        name=row['name'];shutil.copy2(weights/name,prepared/name)
        if digest(prepared/name)!=row['sha256']:raise ValueError('Preparation checksum failed')
    atomic_json(prepared/'active-batch.json',m['training'])
    for source in sorted(prepared.iterdir()):
        dest=scoped(ROOT/'models'/source.name);old=backup/'weights'/source.name;old.parent.mkdir(exist_ok=True)
        if dest.exists():shutil.copy2(dest,old)
        rows.append({'source':str(source),'target':str(dest),'backup':str(old),'existed':dest.exists()})
    r={'phase':'pending','target':str(target),'stage':str(stage),'backup':str(backup),'site_backup':str(backup/'site'),'weights':rows}
    atomic_json(journal,r)
    try:
        hook('prepared')
        for i,row in enumerate(rows):
            dest=Path(row['target']);tmp=dest.with_suffix('.next');shutil.copy2(row['source'],tmp);tmp.replace(dest);hook('weight:'+str(i))
        target.rename(backup/'site');hook('site_backup');stage.rename(target);hook('site_installed')
        verify_manifest(target,ROOT/'models',active=True)
        atomic_json(journal,{**r,'phase':'committed'});journal.unlink()
    except BaseException:recover(journal);raise
    return m

def promote_data(stage,target,backup,fail_after_backup=False):
    for p in (stage,target,backup):scoped(p)
    if backup.exists():raise ValueError('Rollback destination already exists')
    target.rename(backup)
    try:
        if fail_after_backup:raise RuntimeError('Controlled interruption')
        stage.rename(target)
    except BaseException:backup.rename(target);raise

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--site',type=Path,default=ROOT/'output/revision-20261021/staging-site')
    ap.add_argument('--weights',type=Path,default=ROOT/'models/revision-20261021')
    ap.add_argument('--context',type=Path,default=ROOT/'output/revision-20261021/training-manifest.json')
    for flag in ('seal','verify-live','promote','recover'):ap.add_argument('--'+flag,action='store_true')
    a=ap.parse_args()
    if sum((a.seal,a.verify_live,a.promote,a.recover))!=1:ap.error('Choose one operation')
    if a.recover:print('Recovered:',recover());return
    if a.seal:
        m=seal(a.site,read_json(a.context),a.weights,{k:a.context.parent/(k+'-receipt.json') for k in ('decisions','history_day','timing','calibration')})
    elif a.promote:m=promote_revision(a.site,a.weights,a.context.parent/'promotion-backup')
    else:m=verify_manifest(ROOT/'docs',ROOT/'models',active=True)
    print(json.dumps({'verified':True,'batch_id':m['training']['batch_id']},indent=2))

if __name__=='__main__':main()
