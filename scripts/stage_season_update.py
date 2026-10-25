"""Build an immutable, audited incremental dataset. Never edits live data.

Same game IDs with different bytes require --accept-corrections. Each accepted
measurement exception is exact-file SHA + issue, preserving raw bytes. This
does not certify models, current registration, or unknown fielding eligibility.
"""
import argparse,hashlib,json,os,shutil,sys
from pathlib import Path
from audit_season_intake import audit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from identity import game_rosters,participant_key

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def validate_event_identities(path):
    """Validate PA and event actors in their own team/role, including mid-PA swaps."""
    game=json.loads(path.read_text(encoding='utf8'));rosters=game_rosters(game)
    for side in ('away','home'):
        other='home' if side=='away' else 'away'
        for pa in game[side+'PAList']:
            for role,owner in (('batter',side),('pitcher',other)):
                field=role+'Name'
                if participant_key(rosters,owner,role,pa.get(field)) is None:
                    raise ValueError(f'Unresolved PA {role} identity: {path.name}')
                for event in pa['events']:
                    if event.get('type')=='PITCH' and participant_key(rosters,owner,role,event[field] if field in event else pa.get(field)) is None:
                        raise ValueError(f'Unresolved event {role} identity: {path.name}')

def inventory(root,seasons):
    found={}
    for year in seasons:
        for p in sorted((root/str(year)).glob('*.json')):
            g=json.loads(p.read_text(encoding='utf8'));seq=g.get('seq')
            if type(seq) is not int or seq<1 or str(g.get('date',''))[:4]!=str(year):
                raise ValueError('Invalid game identity: '+str(p))
            key=f'{year}/{seq:03d}.json'
            if key in found:raise ValueError('Duplicate source game: '+key)
            found[key]=(p,digest(p))
    return found

def stage(base,incoming,dest,seasons,accept_corrections=False,accepted=()):
    base,incoming,dest=map(lambda p:Path(p).resolve(),(base,incoming,dest))
    if not base.is_dir() or not incoming.is_dir():raise ValueError('Both source directories must exist')
    if len(set(seasons))!=len(seasons) or not seasons:raise ValueError('Explicit unique seasons required')
    if dest.exists() or any(dest==p or dest in p.parents or p in dest.parents for p in (base,incoming)):
        raise ValueError('Use a new, separate dataset destination')
    dest.parent.mkdir(parents=True,exist_ok=True)
    temp=dest.with_name(dest.name+'.building');lock=dest.with_name(dest.name+'.lock')
    if temp.exists():raise FileExistsError('Inspect an interrupted build before retrying: '+str(temp))
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
    try:
        previous,new=inventory(base,seasons),inventory(incoming,seasons)
        changes={'added':[],'corrected':[],'unchanged':[],'retained':[]};chosen=dict(previous)
        for key,item in new.items():
            kind='added' if key not in previous else 'unchanged' if item[1]==previous[key][1] else 'corrected'
            changes[kind].append({'file':key,'sha256':item[1],'previous_sha256':previous.get(key,(None,None))[1]})
            if kind=='corrected' and not accept_corrections:raise ValueError('Source correction needs explicit acceptance: '+key)
            chosen[key]=item
        changes['retained']=sorted(set(previous)-set(new))
        temp.mkdir();raw=temp/'rebas';raw.mkdir()
        for rel,(source,sha) in sorted(chosen.items()):
            target=raw/rel;target.parent.mkdir(exist_ok=True);shutil.copy2(source,target)
            if digest(target)!=sha:raise ValueError('Source changed during copy: '+rel)
        report=audit(raw,seasons)
        exceptions={(r['file'],r['sha256'],r['issue']) for r in accepted}
        allowed=[];errors=[]
        for issue in report['errors']:
            rel=issue.get('file');sha=chosen.get(rel,(None,None))[1]
            if issue.get('issue')=='invalid_pitch_velocity' and (rel,sha,issue['issue']) in exceptions:
                allowed.append(issue)
            else:errors.append(issue)
        unresolved=[s for s in report['seasons'] if s['unresolved_pa_names']]
        if errors or unresolved:
            raise ValueError('Dataset audit failed: '+json.dumps({'errors':errors,'unresolved':unresolved},ensure_ascii=False)[:1800])
        for target in sorted(raw.glob('*/*.json')):validate_event_identities(target)
        manifest={'schema':'baseball.dataset.v1','seasons':sorted(seasons),'source_manifest':report['source_manifest'],
                  'changes':changes,'accepted_measurement_issues':allowed,'raw_values_unchanged':True,
                  'event_actor_identity_checked':True,'models_validated':False,'registration_verified':False}
        manifest['dataset_id']=hashlib.sha256(json.dumps(manifest['source_manifest'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        (temp/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        (temp/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        temp.rename(dest)
        return manifest
    finally:
        # Failed staging is retained for diagnosis; no live data was changed.
        lock.unlink(missing_ok=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('base','incoming','out'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--seasons',type=int,nargs='+',required=True);ap.add_argument('--accept-corrections',action='store_true')
    ap.add_argument('--accepted-measurements',type=Path)
    a=ap.parse_args();accepted=json.loads(a.accepted_measurements.read_text(encoding='utf8')) if a.accepted_measurements else []
    result=stage(a.base,a.incoming,a.out,a.seasons,a.accept_corrections,accepted)
    print(json.dumps({'dataset_id':result['dataset_id'],'changes':{k:len(v) for k,v in result['changes'].items()}},indent=2))
