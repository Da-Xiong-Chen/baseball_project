"""Read-only numeric/unit consistency audit of every sealed website JSON asset."""
from pathlib import Path
import argparse
import json
import math
import os

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--unsealed-context',type=Path);args=parser.parse_args()
    site=Path(os.environ.get('BASEBALL_WEB_ROOT',ROOT/'docs')).resolve()
    if args.unsealed_context:
        import sys
        sys.path.insert(0,str(ROOT/'scripts'))
        from closeout_batch import context_identity
        from prepare_site import inspect_site
        context=json.loads(args.unsealed_context.read_text(encoding='utf8'));context_identity(context)
        manifest={'training':context,'files':{p.relative_to(site).as_posix():None for p in inspect_site(site)}}
    else:manifest=json.loads((site/'data/batch-manifest.json').read_text(encoding='utf8'))
    counts=dict(json_files=0,numeric_values=0,pitch_rows=0,pitch_snapshots=0,replay_views=0,candidate_rows=0,pitcher_rows=0,detail_cells=0,model_metrics=0)
    errors=[];max_errors=dict(candidate_delta_pp=0.,pitcher_delta_pp=0.,pitcher_runs_sum=0.,pitch_delta_pp=0.,mse_difference=0.)
    def check(condition,label):
        if not condition:errors.append(label)
    def finite(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
    # export_static.rnd retains fifteen significant digits in the v5 contract.
    def rounding_bound(v):return 0. if v==0 else .5*10**(math.floor(math.log10(abs(v)))-14)
    def close(actual,expected,tolerance,key,label):
        if not finite(actual) or not finite(expected):check(False,label);return
        difference=abs(actual-expected);max_errors[key]=max(max_errors[key],difference);check(difference<=tolerance,label)
    def walk(value,label):
        if isinstance(value,dict):
            if {'baseline_mse','mse','mae','mse_reduction','mse_reduction_ci'}<=value.keys():
                counts['model_metrics']+=1
                check(value['mse']>=0 and value['mae']>=0 and value['baseline_mse']>0,label+' error bounds')
                close(value['mse_reduction'],value['baseline_mse']-value['mse'],2e-6,'mse_difference',label+' absolute MSE difference')
                check(value['mse_reduction_ci'][0]<=value['mse_reduction_ci'][1],label+' interval order')
            for key,v in value.items():walk(v,label+'/'+key)
        elif isinstance(value,list):
            for i,v in enumerate(value):walk(v,label+'/'+str(i))
        elif isinstance(value,(int,float)) and not isinstance(value,bool):
            counts['numeric_values']+=1;check(math.isfinite(value),label+' nonfinite')
    def replay(r,label):
        counts['replay_views']+=1
        leverage=r['leverage'];check(finite(leverage) and leverage>=0,label+' leverage')
        wpa=r.get('actual',{}).get('WPA');check(wpa is None or finite(wpa) and -1<=wpa<=1,label+' WPA fraction')
        check(r['model_cutoff']<=r['situation']['date'] and r['ml_cutoff']<=r['model_cutoff'],label+' cutoff')
        candidates=r['candidates'];current=next(x for x in candidates if x['角色']=='現任')
        for row in candidates:
            counts['candidate_rows']+=1
            tolerance=sum(rounding_bound(v) for v in [row['相對現任'],row['預估勝率'],current['預估勝率']])+1e-12
            close(row['相對現任'],row['預估勝率']-current['預估勝率'],tolerance,'candidate_delta_pp',label+' hitter relative percentage points')
        rows=r['bullpen']['rows'];baseline=next(x for x in rows if x['角色']=='場上')
        for row in rows:
            counts['pitcher_rows']+=1
            tolerance=rounding_bound(row['預估失分'])+sum(rounding_bound(d[k]) for d in row['對決明細'] for k in ['runs','fatigue'])+1e-12
            close(row['預估失分'],sum(d['runs']+d['fatigue'] for d in row['對決明細']),tolerance,'pitcher_runs_sum',label+' next batters sum including fatigue')
            run_error=rounding_bound(baseline['預估失分'])+rounding_bound(row['預估失分'])
            tolerance=run_error*(abs(leverage)+rounding_bound(leverage))+abs(baseline['預估失分']-row['預估失分'])*rounding_bound(leverage)+rounding_bound(row['守方勝率增減'])+1e-12
            close(row['守方勝率增減'],(baseline['預估失分']-row['預估失分'])*leverage,tolerance,'pitcher_delta_pp',label+' defensive benefit direction/unit')
        for row in candidates+rows:
            score=row.get('價值分數');check(score is None or isinstance(score,int) and 1<=score<=100,label+' percentile is 1..100')
            check(finite(row['樣本球數']) and row['樣本球數']>=0,label+' effective sample')
        for detail in r.get('details',{}).values():
            cells=detail['cells'];check(abs(sum(c['usage'] for c in cells)-1)<1e-5,label+' mix sums to 1')
            for cell in cells:
                counts['detail_cells']+=1
                check(0<=cell['usage']<=1 and cell['n']>=0,label+' detail ratio/sample bounds')
    for name in [*manifest['files'],*(['data/batch-manifest.json'] if not args.unsealed_context else [])]:
        if not name.endswith('.json'):continue
        counts['json_files']+=1
        value=json.loads((site/name).read_text(encoding='utf8'));walk(value,name)
        if name.startswith('data/pitch-change/') and 'snapshots' in value:
            for snapshot in value['snapshots']:
                for hand,data in snapshot['hands'].items():
                    counts['pitch_snapshots']+=1;label=f'{name}/{snapshot["effective_from"]}/{hand}'
                    for window in data['windows'].values():
                        check(window['selected_games']==len(window['games']),label+' game count')
                        check(all(g['date']<snapshot['effective_from'] for g in window['games']),label+' no future games')
                    for v in data['coverage']:check(v is None or finite(v) and 0<=v<=1,label+' coverage')
                    for row in data['rows']:
                        counts['pitch_rows']+=1;a,b=row['adjusted']
                        for v in [a,b]:check(v is None or finite(v) and 0<=v<=1,label+' adjusted proportion')
                        if a is not None and b is not None:close(row['delta_pp'],100*(b-a),1e-9,'pitch_delta_pp',label+' percentage point change')
                        if row['interval'] is not None:check(row['interval'][0]<=row['interval'][1],label+' interval order')
        if name.startswith('data/replay/day-') and 'pa_id' in value:
            for decision in ['ph','pen']:replay(value[decision] or value['ph'],name+'/'+decision)
    report=dict(passed=not errors,sealed_source=not bool(args.unsealed_context),batch_id=manifest['training']['batch_id'],counts=counts,max_rounding_residual=max_errors,errors=errors,
                units={'candidate_benefit':'percentage points; candidate minus incumbent','pitcher_benefit':'percentage points; incumbent runs minus candidate runs, multiplied by leverage','wpa':'fraction in data, multiplied by 100 once for percentage points','pitch_mix':'fraction times 100 for percent; recent minus baseline times 100 for percentage points','mse':'absolute baseline minus model; relative percent divides by baseline MSE','value_score':'comparison-pool percentile 1..100; not probability'})
    args.out.parent.mkdir(exist_ok=True,parents=True);args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if errors:raise SystemExit(1)

if __name__=='__main__':main()
