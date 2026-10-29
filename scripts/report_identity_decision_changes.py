"""Describe v4/v5 decision shifts on identical retrospective decision points."""
import hashlib,json,sys
from functools import lru_cache
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from load import load
from identity import labels
from player_input import legacy_aliases
from batch_contract import metadata
OUT=ROOT/'output/identity-integration-20261025'

def main():
    oldroot=OUT/'baseline-site/data';newroot=OUT/'staging-site/data'
    before=json.loads((oldroot/'timing-2025.json').read_text(encoding='utf8'))
    after=json.loads((newroot/'timing-2025.json').read_text(encoding='utf8'))
    pa,_,boxes=load();lookup=pa.set_index('pa_id');unresolved=[]
    @lru_cache(maxsize=2048)
    def dictionary(day,team,role):
        rows=boxes[(boxes.date<=pd.Timestamp(day))&(boxes.team==team)&(boxes.role==role)]
        result={}
        for row in rows[['name','raw_name']].drop_duplicates().itertuples(index=False):result.setdefault(row.raw_name,set()).add(row.name)
        keys=set(rows.name)
        for key,label in labels(day,True).items():
            if key in keys:result.setdefault(label,set()).add(key)
        for label,key in legacy_aliases(rows).items():result.setdefault(label,set()).add(key)
        return result
    def resolve(name,row,role):
        if not name:return None
        if name.startswith('rebas:CPBL:'):return name
        team=row.fld_team if role=='P' else row.bat_team;values=dictionary(str(row.date.date()),team,role).get(name,set())
        if len(values)!=1:
            unresolved.append(dict(name=name,team=team,date=str(row.date.date()),role=role));return None
        return next(iter(values))
    a={pid:r for game in before['games'].values() for pid,r in game.items()};b={pid:r for game in after['games'].values() for pid,r in game.items()}
    if set(a)!=set(b):raise ValueError('Decision populations differ')
    result={};largest=[]
    for kind,idx,role in [('pen',0,'P'),('ph',3,'B')]:
        shifts=[];top=0;eligible_changed=0;thresholds={str(t):0 for t in (.5,1.,2.)}
        for pid,x in a.items():
            y=b[pid];row=lookup.loc[pid];old=resolve(x[idx+1],row,role)
            eligible_changed+=int((x[idx] is None)!=(y[idx] is None))
            if x[idx] is None or y[idx] is None:continue
            delta=y[idx]-x[idx];shifts.append(delta);top+=int(old!=y[idx+1])
            for t in (.5,1.,2.):thresholds[str(t)]+=int((x[idx]>=t)!=(y[idx]>=t))
            largest.append(dict(pa_id=pid,kind=kind,before=x[idx],after=y[idx],shift=delta,old_best=old,new_best=y[idx+1]))
        result[kind]=dict(total=len(a),comparable=len(shifts),eligible_status_changes=eligible_changed,
            top1_changes=top,threshold_crossings=thresholds,
            mean_absolute_gain_shift=float(np.mean(abs(np.array(shifts)))),max_absolute_gain_shift=float(max(map(abs,shifts))))
    rankings=[]
    day='replay/day-2025-09-20'
    for path in sorted((newroot/day).glob('2025-*.json')):
        old=json.loads((oldroot/day/path.name).read_text(encoding='utf8'));new=json.loads(path.read_text(encoding='utf8'));row=lookup.loc[new['pa_id']]
        for decision in ('ph','pen'):
            x=old[decision] or old['ph'];y=new[decision] or new['ph'];key='球員' if decision=='ph' else '投手';field='candidates' if decision=='ph' else 'bullpen'
            left=x[field] if field=='candidates' else x[field]['rows'];right=y[field] if field=='candidates' else y[field]['rows']
            ids=[resolve(r[key],row,'B' if decision=='ph' else 'P') for r in left]
            current=[r[key] for r in right];common=set(ids)&set(current);positions={v:i for i,v in enumerate(current)}
            reordered=[v for v in ids if v in common]!=[v for v in current if v in common]
            rankings.append(dict(pa_id=new['pa_id'],decision=decision,reordered=reordered,
                removed=sorted(set(ids)-set(current),key=str),added=sorted(set(current)-set(ids),key=str),
                max_rank_shift=max((abs(i-positions[v]) for i,v in enumerate(ids) if v in common),default=0)))
    report=dict(passed=not unresolved,evaluation='retrospective_sensitivity_not_causal_benefit',
        gain_unit='percentage_points',timing=result,daily_views=len(rankings),daily_reordered=sum(r['reordered'] for r in rankings),
        daily_pool_changed=sum(bool(r['removed'] or r['added']) for r in rankings),
        daily_changed_rankings=[r for r in rankings if r['reordered'] or r['removed'] or r['added']],
        largest_gain_shifts=sorted(largest,key=lambda r:abs(r['shift']),reverse=True)[:20],
        unresolved_legacy_labels=unresolved,**metadata())
    (OUT/'decision-change-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('daily_changed_rankings','largest_gain_shifts','unresolved_legacy_labels')},ensure_ascii=False,indent=2),flush=True)
    if unresolved:raise ValueError('Unresolved legacy labels; inspect report')

if __name__=='__main__':main()
