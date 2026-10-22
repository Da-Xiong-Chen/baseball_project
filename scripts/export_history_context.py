import os
"""Export descriptive player context strictly before the fixed historical date."""
import json,sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from load import load
from fatigue import starter_curve
DATE='2025-09-20'
def build(pa,pitches,boxes,date=DATE):
 cutoff=pd.Timestamp(date);prior=boxes[(boxes.date<cutoff)&(boxes.date.dt.year==2025)]
 prior=prior.drop_duplicates(['game','team','name','role']);recent=prior[prior.date>=cutoff-pd.Timedelta(days=14)]
 pp=pitches[(pitches.date<cutoff)&(pitches.date>=cutoff-pd.Timedelta(days=14))];past=pa[(pa.date<cutoff)&(pa.date>=cutoff-pd.Timedelta(days=14))]
 teams={}
 for (team,name,role),g in prior.groupby(['team','name','role']):
  dates=sorted({d.strftime('%Y-%m-%d') for d in g.date});streak=0;cursor=cutoff-pd.Timedelta(days=1)
  while cursor.strftime('%Y-%m-%d') in dates:streak+=1;cursor-=pd.Timedelta(days=1)
  r=recent[(recent.team==team)&(recent.name==name)&(recent.role==role)]
  record={'name':name,'role':role,'consecutive_days_before':streak,'last_date':dates[-1],'rest_days':(cutoff-pd.Timestamp(dates[-1])).days-1,'games14':int(r.game.nunique()),'workload3':int(g[g.date>=cutoff-pd.Timedelta(days=3)]['NP' if role=='P' else 'PA'].fillna(0).sum()),'log': [{'date':x.date.strftime('%Y-%m-%d'),'count':int(getattr(x,'NP' if role=='P' else 'PA') or 0)} for x in r.sort_values('date',ascending=False).itertuples() if pd.notna(getattr(x,'NP' if role=='P' else 'PA'))]}
  if role=='P':
   balls=pp[pp.pitcher==name];bf=past[past.pitcher==name];record.update(pitches14=len(balls),bf14=len(bf),so14=int((bf.result=='SO').sum()),bb14=int(bf.result.isin(['BB','uBB','iBB']).sum()),whiff14=round(float(balls.whiff.mean()),4) if len(balls) else None)
  else:
   ab=past[past.batter==name];record.update(pa14=len(ab),hits14=int(ab.result.isin(['1B','2B','3B','HR']).sum()),so14=int((ab.result=='SO').sum()))
  teams.setdefault(team,{'pitchers':[],'hitters':[]})['pitchers' if role=='P' else 'hitters'].append(record)
 return {'date':date,'window_days':14,'teams':teams}
if __name__=='__main__':
 pa,p,b=load();out=build(pa,p,b);out['fatigue_curve']=starter_curve(DATE);out['source']='Rebas 2025，日期嚴格早於 2025-09-20；先發疲勞曲線以截止日前2024–2025資料估計'
 (Path(os.environ.get('BASEBALL_STATIC_OUT', ROOT/'docs/data'))/'history-context-2025-09-20.json').write_text(json.dumps(out,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8')
 print('Exported pregame player context')
