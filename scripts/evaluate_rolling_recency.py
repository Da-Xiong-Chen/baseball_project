"""Exploratory monthly replay of v5 recency variants with frozen active trees."""
import argparse
import hashlib
import json
from pathlib import Path

from pilot_ensemble_recency import (
    ROOT, SPEC as PILOT, active_roster, bat_hand, batter_variant, context, fit, load,
    mlmodel, np, pd, write,
)

# Fix this protocol before scoring. All available months are retrospective.
PROTOCOL = {
    'purpose': 'exploratory_monthly_replay',
    'cutoffs': [f'2025-{month:02d}-01' for month in range(3, 11)],
    'variants': {role: PILOT['half_lives'] for role in PILOT['roles']},
    'ensemble_tree_weight': 0.5,
    'ranking': 'first PA from inning 6 per game, prior 10-day pools plus observed incumbent',
    'minimum_group_pa': 200,
    'minimum_mse_improvement': 0.0005,
    'maximum_group_mse_degradation': 0.001,
    'calibration': 'weighted absolute gap across five prediction quantile bins',
    'small_sample': 'either actor has less than 100 prior unweighted pitches',
    'sensitivity': 'range of aggregate MSE deltas when omitting one game',
    'bootstrap': {'unit': 'game within month', 'seeds': [20261106, 20261107],
                  'draws': 2000, 'familywise_alpha': 0.05, 'comparisons': 6},
    'independent_holdout_available': False,
    'adoption': False,
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprints():
    inputs = [*sorted((ROOT/'data/rebas').glob('*/*.json')),
              *sorted((ROOT/'src').glob('*.py')), Path(__file__),
              ROOT/'scripts/pilot_ensemble_recency.py',
              *(Path(mlmodel.path_for(cutoff)) for cutoff in PROTOCOL['cutoffs'])]
    return {Path(path).relative_to(ROOT).as_posix(): sha(path) for path in inputs}


def calibration(prediction, target):
    cuts = np.unique(np.quantile(prediction, [.2, .4, .6, .8]))
    bins = np.searchsorted(cuts, prediction, side='right')
    return [
        {'pa': int(mask.sum()), 'prediction': float(prediction[mask].mean()),
         'observed': float(target[mask].mean())}
        for index in np.unique(bins) if (mask := bins == index).any()
    ]


def ranking_contexts(sample, base, tree, cutoff):
    for row in sample[sample.inning >= 6].drop_duplicates('game').itertuples():
        hitters, _ = active_roster(row.bat_team, row.date, row.game)
        _, bullpen = active_roster(row.fld_team, row.date, row.game)
        for role, pool, incumbent in (('batter', hitters, row.batter),
                                       ('pitcher', bullpen, row.pitcher)):
            candidates = sorted(set(pool) | {incumbent})
            if len(candidates) < 2:
                continue
            pairs = ((candidate, row.pitcher) if role == 'batter' else (row.batter, candidate)
                     for candidate in candidates)
            triples = [(batter, bat_hand(batter, base.phand.get(pitcher, 'U'), cutoff), pitcher)
                       for batter, pitcher in pairs]
            yield role, triples, np.asarray(tree.rel_many(triples))


def ranking(model, cases):
    ranks = []
    for role, triples, tree in cases:
        scores = .5 * np.asarray([model.matchup(*key)['rel_pa'] for key in triples]) + .5 * tree
        if not np.isfinite(scores).all():
            raise ValueError('Nonfinite ranking scores')
        order = np.argsort(scores if role == 'pitcher' else -scores, kind='stable')
        ranks.append((role, order[:3].tolist()))
    return ranks


def month(pa, pitches, cutoff, *, frozen_tree=None):
    start = pd.Timestamp(cutoff)
    sample = pa[(pa.date >= start) & (pa.date < start + pd.offsets.MonthBegin())]
    sample = sample.dropna(subset=['RE24', 'batter', 'bhand', 'pitcher']).sort_values(['date', 'game', 'seq', 'pa_id'])
    if sample.empty or sample.pa_id.duplicated().any():
        raise ValueError(f'Invalid target population: {cutoff}')
    base = fit(cutoff)
    tree = mlmodel.get(cutoff) if frozen_tree is None else frozen_tree
    if (frozen_tree is None and tree.cutoff != cutoff) or tree.cutoff > cutoff:
        raise ValueError(f'Wrong cutoff: {cutoff}')
    triples = list(sample[['batter', 'bhand', 'pitcher']].itertuples(index=False, name=None))
    keys = list(dict.fromkeys(triples))
    indices = {key: index for index, key in enumerate(keys)}
    positions = np.asarray([indices[key] for key in triples])
    tree_predictions = np.concatenate([tree.abs_many(keys[i:i+128]) for i in range(0, len(keys), 128)])
    targets = sample.RE24.to_numpy()
    cases = list(ranking_contexts(sample, base, tree, cutoff))
    reference_ranks = ranking(base, cases)
    prior = pitches[pitches.date < start]
    sparse = np.zeros(len(sample), dtype=bool)
    for role in ('batter', 'pitcher'):
        counts = prior[role].value_counts()
        sparse |= sample[role].map(counts).fillna(0).to_numpy() < 100
    groups = {f'bat:{team}': sample.bat_team.eq(team).to_numpy() for team in sorted(sample.bat_team.unique())}
    groups['sparse'] = sparse
    groups['established'] = ~sparse
    variants = [('baseline', None, None)]
    variants += [(f'{role}-{half}', role, half) for role, halves in PROTOCOL['variants'].items() for half in halves]
    results, baseline_errors = {}, None
    for name, role, half in variants:
        if role == 'pitcher':
            model = fit(cutoff, pitcher_half_life=half)
        elif role == 'batter':
            model = batter_variant(base, cutoff, half)
        else:
            model = base
        hierarchy = np.asarray([model.matchup(*key)['per_pa'] for key in keys])
        prediction = (.5 * hierarchy + .5 * tree_predictions)[positions]
        if not np.isfinite(prediction).all():
            raise ValueError(f'Nonfinite predictions: {cutoff} {name}')
        residual = prediction - targets
        errors = residual ** 2
        if baseline_errors is None:
            baseline_errors = errors
        delta = errors - baseline_errors
        grouped = pd.DataFrame({'game': sample.game.to_numpy(), 'delta': delta}).groupby('game').delta.agg(['sum','count'])
        bins = calibration(prediction, targets)
        ranks = ranking(model, cases) if role else reference_ranks
        results[name] = {
            'mse': float(errors.mean()), 'mse_delta': float(delta.mean()),
            'mae': float(np.abs(residual).mean()), 'mean_error': float(residual.mean()),
            'calibration_bins': bins,
            'calibration_gap': sum(b['pa'] * abs(b['prediction'] - b['observed']) for b in bins) / len(sample),
            'groups': {key: {'pa': int(mask.sum()), 'mse_delta': float(delta[mask].mean())}
                       for key, mask in groups.items() if mask.any()},
            'ranking': {role: {
                'contexts': sum(current == role for current, _ in ranks),
                'top1_changes': sum(current == role and picked[0] != original[0]
                                    for (current, picked), (_, original) in zip(ranks, reference_ranks)),
                'mean_top3_overlap': float(np.mean([len(set(picked) & set(original))/len(original)
                    for (current, picked), (_, original) in zip(ranks, reference_ranks) if current == role]))
                    if any(current == role for current, _ in ranks) else None,
            } for role in ('batter', 'pitcher')},
            'game_delta': grouped.to_numpy().tolist(),
        }
    return {'cutoff': cutoff, 'pa': len(sample), 'games': int(sample.game.nunique()), 'results': results}


def summarize(months):
    total_pa = sum(record['pa'] for record in months)
    spec = PROTOCOL['bootstrap']
    summaries = {}
    for name in months[0]['results']:
        results = [m['results'][name] for m in months]
        blocks = [np.asarray(r['game_delta']) for r in results]
        games = np.concatenate(blocks)
        delta, count = games.sum(axis=0)
        if count != total_pa:
            raise ValueError('Per-game denominators must cover every evaluated plate appearance')
        omitted = (delta - games[:,0]) / (count - games[:,1])
        intervals = []
        for seed in spec['seeds']:
            rng = np.random.default_rng(seed)
            sampled = np.zeros((spec['draws'], 2))
            for block in blocks:
                draw = rng.integers(0, len(block), (spec['draws'], len(block)))
                sampled += block[draw].sum(axis=1)
            tail = spec['familywise_alpha'] / (2 * spec['comparisons'])
            intervals.append({'seed': seed, 'bounds': np.quantile(sampled[:,0]/sampled[:,1], [tail, 1-tail]).tolist()})
        summaries[name] = {
            'mse': sum(m['pa'] * r['mse'] for m, r in zip(months, results)) / total_pa,
            'mse_delta': float(delta/count),
            'calibration_gap': sum(m['pa'] * r['calibration_gap'] for m, r in zip(months, results)) / total_pa,
            'adjusted_game_bootstrap': intervals,
            'leave_one_game_delta': [float(omitted.min()), float(omitted.max())],
            'months_improved': sum(r['mse_delta'] < 0 for r in results),
            'groups_over_degradation_limit': [
                {'cutoff': m['cutoff'], 'group': group, **g}
                for m, r in zip(months, results) for group, g in r['groups'].items()
                if g['pa'] >= PROTOCOL['minimum_group_pa'] and g['mse_delta'] > PROTOCOL['maximum_group_mse_degradation']],
        }
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    frozen = {'protocol': PROTOCOL, 'batch_id': context()['batch_id'], 'input_sha256': fingerprints()}
    write(args.out/'frozen-spec.json', frozen)
    pa, pitches, _ = load()
    months = []
    for cutoff in PROTOCOL['cutoffs']:
        result = month(pa, pitches, cutoff)
        write(args.out/f'{cutoff}.json', result)
        months.append(result)
        mlmodel.get.cache_clear()
        print(cutoff, result['games'], 'games', result['pa'], 'PA', flush=True)
    if fingerprints() != frozen['input_sha256']:
        raise ValueError('Evaluation inputs changed during execution')
    summary = summarize(months)
    write(args.out/'report.json', {'protocol': PROTOCOL, 'batch_id': frozen['batch_id'],
         'months': [{k:v for k,v in m.items() if k != 'results'} for m in months],
         'summary': summary, 'adopted': False,
         'limitations': ['Retrospective seasons already inspected', 'Candidate pools inferred from prior appearances',
                         'RE24 error and ranking diagnostics do not estimate actual substitution benefit']})


if __name__ == '__main__':
    main()
