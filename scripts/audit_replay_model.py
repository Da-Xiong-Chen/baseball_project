"""Compare the new monthly tree with the verified preseason tree on unseen October games."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from evaluate_rolling_recency import ROOT, fit, load, mlmodel, np, pd, write
from runtime_config import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Choose a new output file')
    cutoff = settings().month_for(settings().history_date)
    if settings().season != 2026:
        parser.error('This comparison requires the 2026 runtime')
    baseline_cutoff = '2026-01-01'
    weight = ROOT / 'models/gbt_full_v5.pkl'
    expected = next(r['sha256'] for r in json.loads((weight.parent/'active-batch.json').read_bytes())['models']
                    if r['cutoff'] == baseline_cutoff and r['name'] == weight.name)
    if sha256(weight.read_bytes()).hexdigest() != expected:
        raise ValueError('Preseason weight is not the published model')
    baseline = mlmodel._load_weight(weight, baseline_cutoff)
    current = mlmodel.get(cutoff)
    pa, _, _ = load()
    sample = pa[(pa.season == settings().season) & (pa.date >= pd.Timestamp(cutoff))]
    sample = sample.dropna(subset=['RE24', 'batter', 'bhand', 'pitcher']).copy()
    keys = list(dict.fromkeys(sample[['batter','bhand','pitcher']].itertuples(index=False, name=None)))
    hierarchy = fit(cutoff)
    estimate = np.asarray([hierarchy.matchup(*key)['per_pa'] for key in keys])
    idx = {key: i for i, key in enumerate(keys)}
    positions = [idx[key] for key in sample[['batter','bhand','pitcher']].itertuples(index=False, name=None)]
    actual = sample.RE24.to_numpy()
    metrics, losses = {}, {}
    for name, tree in [('preseason_tree', baseline), ('october_tree', current)]:
        tree_estimate = np.concatenate([tree.abs_many(keys[i:i+128]) for i in range(0,len(keys),128)])
        error = ((estimate+tree_estimate)*.5)[positions] - actual
        if not np.isfinite(error).all():
            raise ValueError('Nonfinite prediction in October audit')
        losses[name] = error**2
        metrics[name] = {'mse': float(np.mean(error**2)), 'mae': float(np.mean(np.abs(error))),
                         'mean_signed_error': float(np.mean(error))}
    delta = losses['october_tree'] - losses['preseason_tree']
    games = pd.DataFrame({'game': sample.game, 'delta': delta}).groupby('game').delta.agg(['sum','count'])
    n = len(games)
    draws = np.random.default_rng(20261112).integers(n, size=(5000,n))
    boot = games['sum'].to_numpy()[draws].sum(axis=1)/games['count'].to_numpy()[draws].sum(axis=1)
    write(args.out, {'cutoff': cutoff, 'games': n, 'pa': len(sample),
          'first_date': str(sample.date.min().date()), 'last_date': str(sample.date.max().date()),
          'metrics': metrics, 'paired_mse_delta': float(delta.mean()),
          'exploratory_game_bootstrap_95': np.quantile(boot,[.025,.975]).tolist(),
          'scope': 'Both use the same October-cutoff hierarchy, unchanged blend and October RE24 observations. Small October subset; descriptive check, not a promotion gate.'})


if __name__ == '__main__':
    main()
