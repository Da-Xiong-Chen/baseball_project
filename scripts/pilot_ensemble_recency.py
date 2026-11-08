"""Bounded v5 ensemble engineering pilot; never selects or promotes weights.

All observed May PAs; seven configurations, fixed tree and 0.5 ensemble.
Ranking is an offline score diagnostic on dated candidate pools, not registration.
"""
import argparse,copy,hashlib,json,os,sys,time
from pathlib import Path
for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[key]='2'
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import numpy as np
import pandas as pd
from load import load,pitches_before
from model import fit,_age_days,_mom_k,PRIOR_SEASON_WEIGHT
import mlmodel
from batch_contract import context
from roster import active_roster
from engine import bat_hand

SPEC={'schema_version':1,'purpose':'engineering_pilot_only','start':'2025-05-01','end':'2025-06-01',
 'half_lives':[90,180,365],'roles':['pitcher','batter'],'ensemble_gbt_weight':0.5,'tree_retrained':False,
 'target':'observed PA RE24','missing_target':'exclude','max_ranking_contexts':20,
 'ranking_contexts':'first PA per game after inning 6, chronological; dated 10-day hitter pool excluding incumbent; same pool across variants',
 'ranking_unit':'ensemble rel_pa; no defense/registration/causal recommendation claim',
 'seeds':[20261026,20261027],'bootstrap_resamples':2000,'resampling_unit':'game',
 'adoption':False,'min_mse_improvement':0.0005,'max_group_mse_degradation':0.001,
 'min_group_pa':200,'familywise_alpha':0.05,'comparisons':6,
 'full_adoption_requires':['locked later holdout','full monthly groups','calibration','recommendation and rule thresholds','new-game sensitivity'],
 'pilot_results_cannot_change_adoption_thresholds':True}

def write(path,data):
 tmp=path.with_suffix('.next');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8');tmp.replace(path)

def batter_variant(base,start,half):
 m=copy.deepcopy(base);p=pitches_before(start)
 p=p[p.cell.notna()&p.rv.notna()&p.platoon.notna()&p.batter.notna()&p.pitcher.notna()].copy()
 w=np.where(p.season<int(start[:4]),PRIOR_SEASON_WEIGHT,1.)*0.5**(_age_days(p)/half)
 residual=p.rv.to_numpy()-m.league.reindex(pd.MultiIndex.from_frame(p[['platoon','cell']])).to_numpy()
 s2=float(np.average(residual**2,weights=w))
 d=pd.DataFrame({'name':p.batter.to_numpy(),'sr':w*residual,'n':w,'w2':w*w}).groupby('name').sum()
 k=_mom_k(d.sr.to_numpy(),d.n.to_numpy(),s2,d.w2.to_numpy())
 d['effect']=d.sr/(d.n+k);d['var']=s2/(d.n+k)
 m.bat_all=d;m.k={**m.k,'bat':k};m.__dict__.pop('_lookup_cache',None)
 return m

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
 if args.out.exists():raise FileExistsError('Preserve prior pilot; choose a new output directory')
 args.out.mkdir(parents=True);started=time.monotonic()
 spec={**SPEC,'batch_id':context()['batch_id'],'raw_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'data/rebas').glob('*/*.json'))},
       'code_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),*(ROOT/'src'/n for n in ('model.py','mlmodel.py','load.py','identity.py','roster.py','runtime_config.py'))]}}
 write(args.out/'frozen-spec.json',spec)
 pa=load()[0];test=pa[(pa.date>=SPEC['start'])&(pa.date<SPEC['end'])].dropna(subset=['RE24']).sort_values(['date','game','seq','pa_id'])
 if test.empty or test.pa_id.duplicated().any():raise ValueError('Invalid target population')
 base=fit(SPEC['start']);tree=mlmodel.get(SPEC['start'])
 keys=list(dict.fromkeys(test[['batter','bhand','pitcher']].itertuples(index=False,name=None)))
 idx={q:i for i,q in enumerate(keys)};indices=np.array([idx[q] for q in test[['batter','bhand','pitcher']].itertuples(index=False,name=None)])
 g=[]
 for i in range(0,len(keys),128):g.extend(tree.abs_many(keys[i:i+128]))
 g=np.array(g)[indices];y=test.RE24.to_numpy()
 contexts=[]
 for row in test[test.inning>=6].drop_duplicates('game').head(SPEC['max_ranking_contexts']).itertuples():
  candidates,_=active_roster(row.bat_team,row.date,row.game)
  candidates=sorted(set(candidates)|{row.batter})
  if len(candidates)<2:continue
  triples=[(b,bat_hand(b,base.phand.get(row.pitcher,'U'),SPEC['start']),row.pitcher) for b in candidates]
  contexts.append({'pa_id':row.pa_id,'incumbent':row.batter,'candidates':candidates,'triples':triples,'g':tree.rel_many(triples)})
 configurations=[('baseline',base)]+[(f'{role}-{h}',fit(SPEC['start'],pitcher_half_life=h) if role=='pitcher' else batter_variant(base,SPEC['start'],h)) for role in SPEC['roles'] for h in SPEC['half_lives']]
 records=[];rankbase={};base_error=None;predictions=[]
 for label,m in configurations:
  pred=.5*np.array([m.matchup(*q)['per_pa'] for q in keys])[indices]+.5*g
  if not np.isfinite(pred).all():raise ValueError('Nonfinite predictions')
  err=(pred-y)**2;abs_err=np.abs(pred-y)
  if base_error is None:base_error=err
  diff=pd.DataFrame({'game':test.game.to_numpy(),'delta':err-base_error}).groupby('game').delta.agg(['sum','count'])
  intervals=[]
  for seed in SPEC['seeds']:
   rng=np.random.default_rng(seed);draw=rng.integers(0,len(diff),(SPEC['bootstrap_resamples'],len(diff)))
   boots=diff['sum'].to_numpy()[draw].sum(axis=1)/diff['count'].to_numpy()[draw].sum(axis=1)
   alpha=SPEC['familywise_alpha']/SPEC['comparisons'];intervals.append({'seed':seed,'mse_delta_ci':np.quantile(boots,[alpha/2,1-alpha/2]).tolist()})
  ranks=[]
  for c in contexts:
   scores=.5*np.array([m.matchup(*q)['rel_pa'] for q in c['triples']])+.5*np.asarray(c['g'])
   order=sorted(range(len(scores)),key=lambda i:(-scores[i],c['candidates'][i]));names=[c['candidates'][i] for i in order]
   top=scores[order[0]];inc=scores[c['candidates'].index(c['incumbent'])]
   r={'pa_id':c['pa_id'],'pool':c['candidates'],'top3':names[:3],'gap_vs_incumbent':float(top-inc),'top_gap':float(top-scores[order[1]])}
   if label=='baseline':rankbase[c['pa_id']]=r
   b=rankbase[c['pa_id']];r.update(top1_changed=names[0]!=b['top3'][0],top3_overlap=len(set(names[:3])&set(b['top3']))/min(3,len(names)),baseline_gap=b['top_gap'])
   ranks.append(r)
  groups=[]
  for team in sorted(test.bat_team.unique()):
   mask=test.bat_team.eq(team).to_numpy();groups.append({'team':team,'pa':int(mask.sum()),'mse':float(err[mask].mean()),'mse_delta':float((err-base_error)[mask].mean())})
  records.append({'configuration':label,'pa':len(test),'games':int(test.game.nunique()),'mse':float(err.mean()),'mae':float(abs_err.mean()),'mean_error':float((pred-y).mean()),'mse_delta':float((err-base_error).mean()),'intervals':intervals,'teams':groups,'ranking':ranks})
  predictions.append(pd.DataFrame({'pa_id':test.pa_id.to_numpy(),'game':test.game.to_numpy(),'configuration':label,'target':y,'prediction':pred}))
  write(args.out/'progress.json',{'completed':len(records),'total':7,'latest':label,'elapsed_seconds':time.monotonic()-started});print(label,'completed',len(test),'PAs',flush=True)
 pd.concat(predictions).to_csv(args.out/'predictions.csv',index=False)
 write(args.out/'report.json',{'status':'engineering_pilot_complete','adopted':False,'active_model_changed':False,'results':records,'elapsed_seconds':time.monotonic()-started,'limitations':SPEC['full_adoption_requires']})

if __name__=='__main__':main()
