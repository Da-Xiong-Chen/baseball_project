"""Scan conversion states and reproduce the original negative-error scenario."""
import json
import os
from pathlib import Path
import subprocess
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
import server
from batch_contract import metadata as batch_metadata
from model import fit


def main():
    static=Path(os.environ.get('BASEBALL_STATIC_OUT',ROOT/'docs/data'))
    exported=json.loads((static/'model.json').read_text(encoding='utf-8'))
    for key in ('slope_fine','slope_coarse'):
        assert all(np.isfinite(v) and v>=0 for v in exported[key].values()),key
    assert all(exported[k]==v for k,v in batch_metadata().items())
    m=fit(server.FULL,season=2025);n=0
    for inning in range(1,13):
        for half in ('away','home'):
            for diff in range(-6,7):
                for bases in range(8):
                    for outs in range(3):
                        value=m.run_to_win(inning,half,max(diff,0),max(-diff,0),bases,outs)
                        assert np.isfinite(value) and value>=0
                        n+=1
    roster=server.rosters()
    bat=next(t for t,r in roster.items() if any(h.get('display_name')=='林佳緯' for h in r['hitters']))
    fld=next(t for t,r in roster.items() if any(p.get('display_name')=='魔力藍' for p in r['pitchers']))
    body=dict(inning=9,half='away',outs=1,bases=6,bat_score=2,fld_score=1,
              pitcher='魔力藍',due='林佳緯',due_pos='DH',bench=['胡金龍','陳鏞基','楊竣翔'],
              bat_team=bat,fld_team=fld,next_batters=['林佳緯']+[h['name'] for h in roster[bat]['hitters'] if h.get('display_name')!='林佳緯'][:2],pen=[],pitch_count=10,starter=False)
    body=server.validate_evaluation(body)
    out=Path(os.environ.get('BASEBALL_REPORT_OUT',ROOT/'output/closeout'));out.mkdir(parents=True,exist_ok=True)
    cases=out/'calibration-cases.json';cases.write_text(json.dumps([body],ensure_ascii=False),encoding='utf-8')
    subprocess.run([os.environ.get('NODE_BINARY','node'),'tests/compute_static.js',str(cases),str(out/'calibration-static.json')],cwd=ROOT,check=True)
    js=json.loads((out/'calibration-static.json').read_text(encoding='utf-8'))[0]
    py=server.api('/api/evaluate',{},body)
    assert py['leverage']>=0 and js['leverage']>=0
    max_error=0
    for a,b in zip(py['candidates'],js['candidates']):
        assert a['球員']==b['球員']
        assert a['誤差']>=0 and b['誤差']>=0
        for key in ('相對現任','預估勝率','誤差'):
            max_error=max(max_error,abs(a[key]-b[key]));assert abs(a[key]-b[key])<=1e-8+1e-7*abs(a[key]),(key,a,b)
    report={'states_scanned':n,'calibration':m.calibration_audit,'known_failure_reproduced_then_fixed':True,
            'leverage':py['leverage'],'max_python_js_error':max_error,
            'candidates':[{'name':r['球員'],'difference':r['相對現任'],'error':r['誤差']} for r in py['candidates']]}
    (out/'calibration-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    receipt=Path(os.environ.get('BASEBALL_REPORT_OUT',ROOT/'output/closeout'))/'calibration-receipt.json'
    receipt.parent.mkdir(parents=True,exist_ok=True)
    receipt.write_text(json.dumps(dict(report,passed=True,**batch_metadata()),ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':main()
