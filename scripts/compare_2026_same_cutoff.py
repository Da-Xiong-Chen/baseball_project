"""Compare v5 and chronological weights on the same 2026 monthly PA windows."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from evaluate_half_inning_2026 import paired_interval
from evaluate_rolling_recency import load, mlmodel, np, pd
from historical_actors import decorate
from engine import evaluate_bullpen, evaluate_pinch_hit, model_at, situation
from runtime_config import settings
from timing_backtest import THRESHOLD, decision_points, incumbent_situation
from train_2026_chronological import samples, score_tree
from summarize_2026_training import verified_model


PREDICTIONS = ('reference', 'chronological')
CALIBRATION_EDGES = [-.30, -.15, -.08, -.03, 0, .03, .08, .15, .30]


def metrics(rows):
    report = {'games': int(rows.game.nunique()), 'pa': len(rows)}
    for name in PREDICTIONS:
        error = rows[name] - rows.RE24
        grouped = rows.groupby(np.searchsorted(CALIBRATION_EDGES, rows[name]))
        bins = [{'bin': int(i), 'pa': len(group), 'predicted': float(group[name].mean()),
                 'observed': float(group.RE24.mean())} for i, group in grouped]
        report[name] = {
            'mse': float(error.pow(2).mean()), 'mae': float(error.abs().mean()),
            'bias': float(error.mean()), 'calibration': bins,
        }
    delta = (rows.chronological-rows.RE24)**2 - (rows.reference-rows.RE24)**2
    report.update(paired_mse_delta=float(delta.mean()),
                  paired_game_ci=paired_interval(rows,delta) if report['games']>1 else None)
    return report


def ranked(rows, name, gain, eligible):
    usable = rows[eligible & rows[gain].notna()]
    return {
        'eligible': sorted(usable[name].tolist()),
        'top': usable[name].head(3).tolist(),
        'gain': float(usable[gain].iat[0]) if len(usable) else None,
    }


def rank_case(row, weights):
    scene = situation(row.pa_id)
    bullpen_scene = incumbent_situation(scene, row)
    hierarchy = model_at(str(row.date.date()))
    reports, unknown, fatigue = {}, False, False
    for label, weight in zip(PREDICTIONS, weights):
        batting, _, _ = evaluate_pinch_hit(scene, model=hierarchy, ml=weight, scores=False)
        bullpen, _ = evaluate_bullpen(bullpen_scene, model=hierarchy, ml=weight, scores=False)
        unknown |= bool((batting['守備']=='unknown').any())
        fatigue |= bool(bullpen['疲勞調整'].iat[0] >= .01)
        reports[label] = {
            'ph': ranked(batting, '球員', '相對現任', (batting['角色']=='代打') & batting['守備'].isin(['ok','warn'])),
            'pen': ranked(bullpen, '投手', '守方勝率增減', bullpen['角色']=='牛棚'),
        }
    return {'pa_id':row.pa_id, 'game':row.game, 'date':str(row.date.date()),
            'unconfirmed_fielding_candidate':unknown, 'incumbent_fatigue_adjustment_ge_0_01':fatigue,
            **reports}


def ranking_summary(cases):
    result = {}
    for role in ('ph','pen'):
        pairs = [(case,case['reference'][role],case['chronological'][role]) for case in cases]
        compared = [(case,a,b) for case,a,b in pairs if a['gain'] is not None and b['gain'] is not None]
        if any(a['eligible']!=b['eligible'] for _,a,b in pairs):
            raise ValueError('Decision comparison must use identical eligible candidate pools')
        groups = {'all':compared, 'near_threshold':[p for p in compared if abs(p[1]['gain']-THRESHOLD)<=.25],
                  'unconfirmed_fielding':[p for p in compared if p[0]['unconfirmed_fielding_candidate']],
                  'fatigue':[p for p in compared if p[0]['incumbent_fatigue_adjustment_ge_0_01']]}
        result[role] = {label:{
            'n':len(group),
            'top1_changed':sum(a['top'][0]!=b['top'][0] for _,a,b in group),
            'top3_set_changed':sum(set(a['top'])!=set(b['top']) for _,a,b in group),
            'threshold_flips':sum((a['gain']>=THRESHOLD)!=(b['gain']>=THRESHOLD) for _,a,b in group),
        } for label,group in groups.items()}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--chronological', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    runtime = settings()
    if runtime.data_seasons!=(2024,2025,2026) or args.out.exists():
        parser.error('Use the explicit three-season runtime and a fresh output folder')
    args.out.mkdir(parents=True)
    pa = load()[0]
    points = decision_points().sort_values(['date','game','inning','h','seq'])
    frames, cases, receipts = [], [], {}
    for cutoff in runtime.replay_cutoffs:
        stop = pd.Timestamp(cutoff)+pd.offsets.MonthBegin()
        ref_file = args.reference / f'gbt_{cutoff[:7]}_v{mlmodel.TRAINING_VERSION}.pkl'
        cand_dir = args.chronological / cutoff
        reference = mlmodel._load_weight(ref_file,cutoff)
        candidate = verified_model(cand_dir,cutoff)
        for weight in (reference,candidate):
            if not weight.training_samples['last_date'] < cutoff or not weight.calibration_reference['last_date'] < cutoff:
                raise ValueError(f'Found data on or after cutoff {cutoff}')
        available = pa[(pa.date>=cutoff)&(pa.date<stop)]
        target = samples(decorate(available))
        stored = pd.read_csv(cand_dir/'predictions.csv').set_index('pa_id',verify_integrity=True)
        if set(stored.index)!=set(target.pa_id) or not np.allclose(stored.loc[target.pa_id].RE24,target.RE24):
            raise ValueError(f'Existing candidate predictions do not match source rows at {cutoff}')
        common = stored.loc[target.pa_id]
        out = target[['pa_id','game','RE24','bat_team','fld_team','inning','half','bat_score','fld_score','bhand','start_phand']].copy()
        out['reference'] = (common.hierarchy.to_numpy()+score_tree(reference,target))/2
        out['chronological'] = common.candidate_ensemble.to_numpy()
        out['low_history'] = common['sparse'].to_numpy()
        out['month'] = cutoff
        frames.append(out)
        eligible = points[(points.date>=cutoff)&(points.date<stop)]
        # Three fixed windows per game, sampled evenly through each test month.
        games = eligible.game.unique()
        for game in games[np.linspace(0,len(games)-1,min(4,len(games)),dtype=int)]:
            game_points = eligible[eligible.game==game]
            selected = game_points.iloc[np.unique(np.linspace(0,len(game_points)-1,min(3,len(game_points)),dtype=int))]
            cases.extend(rank_case(row,(reference,candidate)) for _,row in selected.iterrows())
        receipts[cutoff] = {'reference_sha256':sha256(ref_file.read_bytes()).hexdigest(),
                            'candidate_sha256':sha256((cand_dir/'model.pkl').read_bytes()).hexdigest(),
                            'source_pa':len(available),'evaluated_pa':len(out)}
        print(cutoff,len(out),'plate appearances',flush=True)
    whole = pd.concat(frames,ignore_index=True)
    if whole.pa_id.duplicated().any() or not np.isfinite(whole[list(PREDICTIONS)].to_numpy()).all():
        raise ValueError('Invalid pooled evaluation predictions')
    groups = {'low_history':whole[whole.low_history], 'established':whole[~whole.low_history],
              'late_close':whole[(whole.inning>=8)&((whole.bat_score-whole.fld_score).abs()<=2)]}
    for field in ('bat_team','fld_team','bhand','start_phand'):
        groups.update({f'{field}:{key}':rows for key,rows in whole.groupby(field,dropna=False)})
    whole.to_csv(args.out/'predictions.csv',index=False)
    report = {'scope':'Previously inspected 2026 development data. No model adoption decision.',
              'all':metrics(whole),'monthly':{month:metrics(group) for month,group in whole.groupby('month')},
              'groups':{name:metrics(group) for name,group in groups.items() if len(group)},
              'receipts':receipts,'ranking_summary':ranking_summary(cases),'ranking_cases':cases,
              'calibration_bin_edges':CALIBRATION_EDGES}
    with (args.out/'report.json').open('x',encoding='utf8') as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2,allow_nan=False)


if __name__=='__main__':
    main()
