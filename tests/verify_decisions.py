"""Independent real-data parity and replay invariants; run after exporting v2 snapshots."""
import json
import math
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'src'))
import server
import mlmodel
from engine import custom_situation
from load import load

def main():
    out=ROOT/'output'/'decision_v2';out.mkdir(parents=True,exist_ok=True)
    roster=server.rosters();teams=sorted(roster)
    cases=[]
    for i,bat in enumerate(teams):
        fld=teams[(i+1)%len(teams)];b=roster[bat];p=roster[fld]
        for pc,starter,empty in [(0,False,True),(30,False,False),(105,True,False)]:
            cases.append(dict(inning=7,half='home',outs=1,bases=3,bat_score=2,fld_score=3,
                              pitcher=p['pitchers'][0]['name'],due=b['hitters'][0]['name'],due_pos='DH',
                              bench=[] if empty else [h['name'] for h in b['hitters'][1:4]],
                              bat_team=bat,fld_team=fld,next_batters=[h['name'] for h in b['hitters'][:3]],
                              pen=[] if empty else [h['name'] for h in p['pitchers'][1:3]],pitch_count=pc,starter=starter))
    (out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False),encoding='utf8')
    subprocess.run(['node','tests/compute_static.js',str(out/'cases.json'),str(out/'static.json')],cwd=ROOT,check=True)
    static=json.loads((out/'static.json').read_text(encoding='utf8'))
    m=server.model_for(server.FULL);ml=mlmodel.get(server.FULL);max_error=0.0
    for body,result in zip(cases,static):
        sit=custom_situation(**body,date=server.FULL)
        local=server.build_result(sit,m,ml)
        for key,identity in [('candidates','球員'),('bullpen','投手')]:
            a=local[key] if key=='candidates' else local[key]['rows'];b=result[key] if key=='candidates' else result[key]['rows']
            assert [x[identity] for x in a]==[x[identity] for x in b]
            for x,y in zip(a,b):
                for metric in ['價值分數','預估勝率','相對現任','預估失分','守方勝率增減','階層式','機器學習','疲勞調整']:
                    if metric not in x or x[metric] is None:continue
                    error=abs(x[metric]-y[metric]);max_error=max(max_error,error)
                    assert error<0.0001,(identity,x[identity],metric,error)
                if '對決明細' in x:
                    assert abs(sum(d['runs']+d['fatigue'] for d in x['對決明細'])-x['預估失分'])<1e-9
        assert local['schema_version']==result['schema_version']==2
    pa=load()[0];expected=set(pa.loc[(pa.season==2025)&pa.is_ph,'pa_id'])
    seen=set();games=0
    for file in (ROOT/'docs/data/replay').glob('*.json'):
        if file.name=='games.json':continue
        payload=json.loads(file.read_text(encoding='utf8'));games+=1
        for pid,r in payload['results'].items():
            assert r['schema_version']==2,(pid,'stale schema')
            assert r['ml_cutoff']<=r['model_cutoff']<=r['situation']['date'],pid
            assert all(math.isfinite(c['預估勝率']) for c in r['candidates']),pid
            for p in r['bullpen']['rows']:
                assert abs(sum(d['runs']+d['fatigue'] for d in p['對決明細'])-p['預估失分'])<0.00002,pid
            seen.add(pid)
    assert seen==expected,{'missing':sorted(expected-seen),'extra':sorted(seen-expected)}
    report=dict(custom_scenarios=len(cases),max_numeric_error=max_error,replay_games=games,
                replay_cases=len(seen),missing_cases=0,stale_snapshots=0,version=2)
    (out/'parity.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
