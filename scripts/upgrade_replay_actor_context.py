"""Audit old/new decision inputs and refresh known staging replay metadata.

The PA-opening fix does not change training rows. Only decisions whose actual
engine inputs changed are recalculated. Existing output is verified against its
export receipt first; this is not a way to approve arbitrary edited snapshots.
"""
import ast,hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
import engine,server
from historical_actors import decorate
from export_static import rnd
from export_history_day import details
from batch_contract import metadata
OUT=ROOT/'output/identity-integration-20261025'

def main():
    folder=Path(os.environ['BASEBALL_STATIC_OUT']);proof=OUT/'exports/model-replays.json'
    original=json.loads(proof.read_text(encoding='utf8'))
    paths=sorted((folder/'replay').glob('20*.json'))
    for path in paths:
        rel=path.relative_to(folder).as_posix()
        if hashlib.sha256(path.read_bytes()).hexdigest()!=original['files'].get(rel):raise ValueError('Unknown or changed original replay '+rel)
    source=subprocess.check_output(['git','show','HEAD:src/engine.py'],cwd=ROOT,text=True,encoding='utf8')
    tree=ast.parse(source);node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='situation')
    scope=vars(engine).copy();exec(compile(ast.Module(body=[node],type_ignores=[]),'<baseline-situation>','exec'),scope)
    previous=scope['situation'];pa=engine.load()[0];changes=[];hashes={};count=0
    def signature(s):
        row={k:str(s['row'][k]) for k in ('pitcher','phand','batter','bhand','catcher','inning','half','bases','outs','bat_score','fld_score')}
        return dict(row=row,**{k:sorted(s[k]) if isinstance(s[k],set) else s[k] for k in ('lineup','due','bench','positions','used_pitchers','pitch_count','starter')})
    for path in paths:
        payload=json.loads(path.read_text(encoding='utf8'))
        if payload.get('batch_id')!=metadata()['batch_id']:raise ValueError('Replay batch differs')
        game=path.stem;frame=decorate(pa[pa.game==game]);look=frame.set_index('pa_id')
        for row in payload['pas']:
            r=look.loc[row['pa_id']]
            for key in ('start_batter','start_pitcher','mid_pa_actor_change'):row[key]=r[key].item() if hasattr(r[key],'item') else r[key]
        for pid,before in list(payload['results'].items()):
            a=signature(previous(pid));b=signature(engine.situation(pid));count+=1
            if a!=b:
                date=before['situation']['date'];after=details(server.replay_result(pid,'ph'),server.model_for(date))
                payload['results'][pid]=after
                changes.append(dict(pa_id=pid,changed_fields=[key for key in a if a[key]!=b[key]],
                    old_candidates=[(r['球員'],r['相對現任']) for r in before['candidates']],
                    new_candidates=[(r['球員'],r['相對現任']) for r in after['candidates']]))
                server._models.pop(date,None)
        raw=json.dumps(rnd(server.clean(payload)),ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf8')
        temporary=path.with_suffix('.next');temporary.write_bytes(raw);temporary.replace(path)
        hashes[path.relative_to(folder).as_posix()]=hashlib.sha256(raw).hexdigest()
    report=dict(passed=True,checked=count,recalculated=len(changes),changes=changes,files=hashes,
        parent_receipt_sha256=hashlib.sha256(proof.read_bytes()).hexdigest(),
        baseline_situation_sha256=hashlib.sha256(ast.unparse(node).encode()).hexdigest(),
        current_engine_sha256=hashlib.sha256((ROOT/'src/engine.py').read_bytes()).hexdigest(),**metadata())
    target=OUT/'verification/replay-actor-upgrade.json';target.parent.mkdir(exist_ok=True,parents=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('files','changes')},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
