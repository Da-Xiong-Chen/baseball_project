"""Test six predeclared recency variants on 2026, with a shared 2025 tree."""
import argparse
import hashlib
import json
from pathlib import Path

from evaluate_rolling_recency import ROOT, PROTOCOL, load, mlmodel, month, summarize, write
from runtime_config import settings

TREE_CUTOFF = '2026-01-01'
CUTOFFS = [f'2026-{m:02d}-01' for m in range(3, 11)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if settings().data_seasons != (2024, 2025, 2026) or settings().season != 2026:
        parser.error('Use an explicit research runtime with the 2024–2026 source batch.')
    active = json.loads((ROOT/'models/active-batch.json').read_bytes())
    weight = ROOT/'models/gbt_full_v5.pkl'
    sha = hashlib.sha256(weight.read_bytes()).hexdigest()
    if not any(row['name'] == weight.name and row['cutoff'] == TREE_CUTOFF
               and row['sha256'] == sha for row in active['models']):
        raise ValueError('Published tree hash or cutoff differs from the active batch')
    args.out.mkdir(parents=True, exist_ok=False)
    protocol = {
        **PROTOCOL,
        'purpose': '2026_temporal_holdout_for_recency',
        'cutoffs': CUTOFFS,
        'independent_holdout_available': True,
        'tree_cutoff': TREE_CUTOFF,
        'tree_sha256': sha,
        'primary_metric': 'paired difference in MSE on observed PA RE24',
        'decision': 'difference <= -0.0005; both adjusted upper bounds < 0; no group over degradation limit; calibration gap no worse',
    }
    write(args.out/'frozen-protocol.json', protocol)
    tree = mlmodel._load_weight(weight, TREE_CUTOFF)
    pa, pitches, _ = load()
    months = []
    for cutoff in CUTOFFS:
        record = month(pa, pitches, cutoff, frozen_tree=tree)
        write(args.out/(cutoff+'.json'), record)
        months.append(record)
        print(cutoff, record['games'], record['pa'], flush=True)
    results = summarize(months)
    baseline = results['baseline']
    for name, value in results.items():
        value['eligible_for_followup'] = (
            name != 'baseline' and
            value['mse_delta'] <= -protocol['minimum_mse_improvement'] and
            all(i['bounds'][1] < 0 for i in value['adjusted_game_bootstrap']) and
            not value['groups_over_degradation_limit'] and
            value['calibration_gap'] <= baseline['calibration_gap']
        )
    write(args.out/'report.json', {
        'protocol': protocol,
        'games': sum(r['games'] for r in months),
        'plate_appearances': sum(r['pa'] for r in months),
        'results': results,
        'months': [{'cutoff': r['cutoff'], 'games': r['games'], 'pa': r['pa'],
                    'ranking': {k:v['ranking'] for k,v in r['results'].items()}} for r in months],
        'adopted': False,
        'scope': 'The tree is frozen across the season; hierarchical models use only games before each month.',
    })


if __name__ == '__main__':
    main()
