"""Summarize month-by-month held-out performance and operational ranking stability."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from evaluate_half_inning_2026 import paired_interval
from evaluate_rolling_recency import calibration, fit, load, mlmodel, np, pd
from historical_actors import decorate
from runtime_config import settings
from timing_backtest import THRESHOLD, decision_points, evaluate
from train_2026_chronological import ROOT, samples, score_tree

MODELS = ('league','hierarchy','preseason_tree','chronological_tree','reference_ensemble','candidate_ensemble')


def metrics(rows, models=MODELS):
    observed = rows.RE24.to_numpy()
    result = {}
    for name in models:
        predicted = rows[name].to_numpy()
        error = predicted-observed
        bins = calibration(predicted,observed)
        result[name] = {'mse':float((error**2).mean()),'mae':float(np.abs(error).mean()),
                        'bias':float(error.mean()),
                        'calibration_gap':sum(b['pa']*abs(b['prediction']-b['observed']) for b in bins)/len(rows)}
    delta = (rows[models[-1]]-rows.RE24)**2-(rows[models[-2]]-rows.RE24)**2
    return {'pa':len(rows),'games':int(rows.game.nunique()),'metrics':result,
            'paired_mse_delta':float(delta.mean()),'paired_game_ci':paired_interval(rows,delta)}


def verified_model(directory, cutoff):
    receipt = json.loads((directory/'receipt.json').read_bytes())
    model = directory/'model.pkl'
    if receipt['cutoff']!=cutoff or receipt['sha256']!=sha256(model.read_bytes()).hexdigest():
        raise ValueError(f'Model receipt mismatch: {cutoff}')
    return mlmodel._load_weight(model,cutoff)


def compare_rankings(rows, cutoff, previous, current):
    first = rows.sort_values(['date','game','inning','h','seq']).drop_duplicates('game')
    selected = first.iloc[np.linspace(0,len(first)-1,min(len(first),8),dtype=int)]
    hierarchy = fit(cutoff)
    out = []
    for _, row in selected.iterrows():
        ref, cand = (evaluate(row,hierarchy,tree) for tree in (previous,current))
        out.append({'game':row.game,'pa_id':row.pa_id,'arms':[
            {'role':kind, 'reference_top':ref[kind+'_best'], 'candidate_top':cand[kind+'_best'],
             'reference_gain':ref[kind+'_gain'], 'candidate_gain':cand[kind+'_gain']}
            for kind in ('ph','pen')]})
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--monthly', required=True, type=Path)
    parser.add_argument('--legacy-october', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Choose a new report')
    runtime = settings()
    if runtime.season!=2026:
        parser.error('Use the explicit 2026 runtime')
    weight = ROOT/'models/gbt_full_v5.pkl'
    active = json.loads((weight.parent/'active-batch.json').read_bytes())
    record = next(r for r in active['models'] if r['name']==weight.name)
    if sha256(weight.read_bytes()).hexdigest()!=record['sha256']:
        raise ValueError('Preseason reference hash differs')
    preseason = mlmodel._load_weight(weight,record['cutoff'])
    context = json.loads((args.legacy_october.parent.parent/'batch-context.json').read_bytes())
    legacy_record = next(r for r in context['models'] if r['cutoff']=='2026-10-01')
    if sha256(args.legacy_october.read_bytes()).hexdigest()!=legacy_record['sha256']:
        raise ValueError('October reference hash differs')
    legacy = mlmodel._load_weight(args.legacy_october,'2026-10-01')
    pa = load()[0]
    points = decision_points()
    months, ranking = [], []
    for cutoff in runtime.replay_cutoffs:
        folder = args.monthly/cutoff
        rows = pd.read_csv(folder/'predictions.csv')
        candidate = verified_model(folder,cutoff)
        end = pd.Timestamp(cutoff)+pd.offsets.MonthBegin()
        if rows.pa_id.duplicated().any() or not set(rows.pa_id)<=set(pa[(pa.date>=cutoff)&(pa.date<end)].pa_id):
            raise ValueError(f'Forecast sample crosses the month: {cutoff}')
        if cutoff=='2026-10-01':
            matched = samples(decorate(pa[(pa.date>=cutoff)&(pa.date<end)])).set_index('pa_id').loc[rows.pa_id]
            rows['legacy_october_ensemble'] = (rows.hierarchy+score_tree(legacy,matched))/2
        months.append(rows.assign(month=cutoff))
        ranking.extend(compare_rankings(points[(points.date>=cutoff)&(points.date<end)],cutoff,preseason,candidate))
        print(cutoff,len(rows),'PA; rankings recorded',flush=True)
    all_rows = pd.concat(months,ignore_index=True)
    evaluated = len(pa[pa.season==runtime.season])
    if all_rows.pa_id.duplicated().any() or all_rows.game.nunique()!=360:
        raise ValueError('Incomplete or duplicate full-season held-out coverage')
    low_history = all_rows['sparse']
    groups = {'low_history':all_rows[low_history], 'established':all_rows[~low_history],
              'late_two_out':all_rows[(all_rows.inning>=6)&(all_rows.outs==2)]}
    groups.update({f'bat:{t}':rows for t,rows in all_rows.groupby('bat_team')})
    rank_summary = {}
    for role in ('ph','pen'):
        values = [arm for row in ranking for arm in row['arms']
                  if arm['role']==role and arm['reference_top'] is not None and arm['candidate_top'] is not None]
        rank_summary[role] = {'comparable':len(values),'different_top':sum(v['reference_top']!=v['candidate_top'] for v in values),
            'threshold_changes':sum((v['reference_gain']>=THRESHOLD)!=(v['candidate_gain']>=THRESHOLD) for v in values)}
    report = {'total_source_pa':evaluated,'excluded_source_pa':evaluated-len(all_rows),
              'all':metrics(all_rows),'monthly':{m:metrics(d) for m,d in all_rows.groupby('month')},
              'groups':{name:metrics(rows) for name,rows in groups.items() if len(rows)},
              'same_cutoff_october':metrics(months[-1],('legacy_october_ensemble','candidate_ensemble')),
              'ranking':rank_summary,'ranking_cases':ranking,
              'scope':'Observed RE24 on monthly test windows; rank changes on up to eight sampled games per month are descriptive. Season data already seen in prior studies.'}
    with args.out.open('x',encoding='utf8') as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps({'all':report['all'],'same_cutoff_october':report['same_cutoff_october'],'ranking':rank_summary},indent=2))


if __name__ == '__main__':
    main()
