"""Exercise existing bullpen capacity accounting with dated workloads and explicit assumptions."""

import argparse
import json
from pathlib import Path
import subprocess

from evaluate_rolling_recency import ROOT, load, pd
from runtime_config import settings
from simulate_bullpen_two_halves import observed_halves


def workload(pitches, player, date):
    own = pitches[pitches.pitcher==player]
    return [int((own.date==date-pd.Timedelta(days=days)).sum()) for days in (1,2,3)]


def browser_plans(cases):
    code = """
const {plan}=require('./docs/bullpen-plan.js');
const cases=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
for(const item of cases) {
  item.results={};
  for(const [label,order] of Object.entries(item.orders)) {
    try {item.results[label]=plan({target:item.target,pitchers:item.pitchers,order});}
    catch(error) {item.results[label]={rejected:error.message};}
  }
}
process.stdout.write(JSON.stringify(cases));
"""
    result = subprocess.run(['node','-e',code],input=json.dumps(cases),text=True,encoding='utf-8',
                            capture_output=True,check=True,cwd=ROOT)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    if settings().season!=2026 or args.out.exists():
        parser.error('Use the explicit 2026 runtime and a new report')
    pas,pitches,boxes = load()
    pas = pas[pas.season==2026].sort_values(['date','game','half','seq'])
    pitches = pitches[pitches.season==2026]
    relievers = boxes[(boxes.role=='P')&(boxes.order>1)]
    swaps = set(pitches.loc[pitches.pitcher.ne(pitches.pa_pitcher),'pa_id'])
    cases = []
    for (game,half),rows in pas.groupby(['game','half'],sort=False):
        today,team = rows.date.iat[0], rows.fld_team.iat[0]
        target_halves,reason = observed_halves(rows)
        if reason or any(r.pa_id in swaps for inning in target_halves for r in inning):
            continue
        before = pitches[(pitches.fld_team==team)&(pitches.date<today)]
        prior = relievers[(relievers.team==team)&(relievers.date<today)&
                          (relievers.date>=today-pd.Timedelta(days=30))]
        if len(prior.name.unique())<4:
            continue
        earlier_pitches = pitches[(pitches.game==game)&(pitches.half==half)&(pitches.inning<7)]
        active = set(rows[rows.inning<7].pitcher) | set(earlier_pitches.pitcher)
        names = sorted(set(prior.name)-active)
        if len(names)<4:
            continue
        counts = {name:workload(before,name,today) for name in names}
        loaded = sorted((n for n in names if counts[n][0] and counts[n][1]))
        rest = sorted((n for n in names if sum(counts[n])==0))
        if not loaded or len(rest)<3:
            continue
        names = [loaded[0],*rest[:3]]
        target = sum(map(len,target_halves))
        pitchers = [
            {'id':n,'pitches_d_minus_1_2_3':counts[n],
             'remaining':max(0,5-counts[n][0]//10-counts[n][1]//20),
             'available':counts[n][0]<30,'retired':False} for n in names]
        usable = [p['id'] for p in pitchers if p['available']]
        if len(usable)<3:
            continue
        cases.append({'game':game,'date':str(today.date()),'fielding_team':team,
                      'source':'historical consecutive dates and observed innings 7–8 demand',
                      'target':target,'pitchers':pitchers,
                      'orders':{'limited':usable[:1],'alternate':usable[1:]+usable[:1]}})
        if len({c['fielding_team'] for c in cases})>=3:
            break
    if not cases:
        raise ValueError('No qualifying multi-day game')
    same_day = {**cases[0], 'source':'synthetic second-game capacity applied to a historical demand'}
    same_day['pitchers'] = [{**p,'available':False,'remaining':0} if i==1 else dict(p)
                            for i,p in enumerate(same_day['pitchers'])]
    unavailable = same_day['pitchers'][1]['id']
    retired = same_day['pitchers'][2]['id']
    same_day['pitchers'][2]['retired'] = True
    same_day['orders'] = {'unavailable':[unavailable],'retired':[retired],
                          'alternate':[p['id'] for p in same_day['pitchers'] if p['available'] and not p['retired']]}
    results = browser_plans([*cases,same_day])
    for case in results:
        for result in case['results'].values():
            if 'covered' in result and result['covered']+result['uncovered']!=case['target']:
                raise ValueError('Capacity conservation failed')
    if not any(c['results']['limited']['uncovered'] for c in results[:-1]):
        raise ValueError('Expected historical workloads to exercise capacity exhaustion')
    if not all('rejected' in results[-1]['results'][k] for k in ('unavailable','retired')):
        raise ValueError('Invalid second-game plans were accepted')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x',encoding='utf-8') as stream:
        json.dump({'capacity_policy':'Hypothetical: base 5 PA, minus 1 per 10 pitches yesterday and per 20 the day before; unavailable at 30 yesterday.',
                   'scope':'Prior game workload and historical observed demand. Capacity accounting only. No win estimate or legal certification.',
                   'cases':results},stream,ensure_ascii=False,indent=2,allow_nan=False)
    print(len(results)-1,'historical cases and one synthetic second-game case passed',flush=True)


if __name__=='__main__':
    main()
