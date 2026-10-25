"""Real-data Python/JS parity for every roster player with unknown handedness."""
import json,os,sys,subprocess,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
import server
from batch_contract import metadata

def main():
    rosters=server.rosters();teams=sorted(rosters);cases=[]
    def case(bat,fld,batter,pitcher):
        hitters=[p['name'] for p in rosters[bat]['hitters'] if p['name']!=batter]
        pen=[p['name'] for p in rosters[fld]['pitchers'] if p['name']!=pitcher][:3]
        return dict(inning=8,half='away',outs=1,bases=6,bat_score=2,fld_score=3,
            bat_team=bat,fld_team=fld,due=batter,pitcher=pitcher,due_pos='DH',bench=hitters[:3],
            next_batters=[batter,*hitters[:2]],pen=pen,pitch_count=85,starter=True)
    for i,team in enumerate(teams):
        other=teams[(i+1)%len(teams)]
        for player in rosters[team]['pitchers']:
            if player['hand'] not in ('L','R'):
                cases.append(case(other,team,rosters[other]['hitters'][0]['name'],player['name']))
                switch=next((p for p in rosters[other]['hitters'] if p['hand']=='S'),None)
                if switch:cases.append(case(other,team,switch['name'],player['name']))
        for player in rosters[team]['hitters']:
            if player['hand'] not in ('L','R','S'):
                cases.append(case(team,other,player['name'],rosters[other]['pitchers'][0]['name']))
    assert cases,'Expected actual missing-hand cases'
    out=Path(os.environ.get('BASEBALL_REPORT_OUT',ROOT/'output/identity-integration-20261025/verification'))
    out.mkdir(parents=True,exist_ok=True);requests=out/'edge-cases.json';results=out/'edge-static.json'
    requests.write_text(json.dumps(cases,ensure_ascii=False),encoding='utf8')
    subprocess.run([os.environ.get('NODE_BINARY','node'),'tests/compute_static.js',str(requests),str(results)],cwd=ROOT,check=True)
    maximum=0;warnings=0
    for request,js in zip(cases,json.loads(results.read_text(encoding='utf8'))):
        py=server.api('/api/evaluate',{},request)
        assert js['engine_contract']==py['engine_contract']==5
        for key,ident in [('candidates','球員'),('bullpen','投手')]:
            a=py[key] if key=='candidates' else py[key]['rows'];b=js[key] if key=='candidates' else js[key]['rows']
            assert [r[ident] for r in a]==[r[ident] for r in b]
            for x,y in zip(a,b):
                for metric in ('價值分數','預估勝率','相對現任','誤差','預估失分','守方勝率增減','階層式','機器學習','疲勞調整','樣本球數','投手對此側樣本'):
                    if isinstance(x.get(metric),(int,float)):
                        error=abs(x[metric]-y[metric]);maximum=max(maximum,error)
                        assert math.isfinite(y[metric]) and error<=1e-8+1e-7*abs(x[metric]),(request,metric,x,y)
                if '手別未記錄' in x.get('資料警示',''):
                    assert '手別未記錄' in y.get('資料警示','');warnings+=1
    report=dict(passed=True,cases=len(cases),max_numeric_error=maximum,missing_hand_warnings_checked=warnings,**metadata())
    (out/'identity-edge-parity.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
