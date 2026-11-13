"""Fit an offline v5 candidate with date-separated tuning and calibration."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import pickle
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss

from historical_actors import decorate
from load import load
from mlmodel import MLModel, Simulator, TRAINING_VERSION, _load_weight, _pitches, make_gbt, oof_tendencies, training_pitches
from ml_compare import apply_tendencies, features, fit_tendencies
from model import fit
from runtime_config import settings

ITERATIONS = (50, 100, 150, 200, 300, 450, 600)
WINDOW_DAYS = 12  # distinct dates with games, never individual rows


def velocity_tables(rows):
    player = rows.groupby(['pitcher', 'ptype']).velo.mean()
    league = rows.groupby('ptype').velo.mean()
    league.attrs['training_global_mean'] = float(rows.velo.mean())
    return player, league


def fit_tree(rows, rounds):
    player, league = velocity_tables(rows)
    tree = make_gbt(max_iter=rounds, early_stopping=False)
    tree.fit(features(rows, oof_tendencies(rows), player, league), rows.cls)
    return tree, player, league


def score_tree(model, rows):
    keys = list(dict.fromkeys(rows[['batter', 'bhand', 'pitcher']].itertuples(index=False, name=None)))
    predictions = np.concatenate([model.abs_many(keys[i:i+128]) for i in range(0, len(keys), 128)])
    mapped = dict(zip(keys, predictions))
    return np.asarray([mapped[key] for key in rows[['batter','bhand','pitcher']].itertuples(index=False, name=None)])


def samples(pa):
    valid = pa.batter.eq(pa.start_batter) & pa.pitcher.eq(pa.start_pitcher)
    out = pa[valid].dropna(subset=['RE24', 'batter', 'pitcher']).copy()
    out['bhand'] = out['start_bhand'].fillna('U')
    return out


def train(cutoff):
    pa, _, _ = load()
    prepared = _pitches()
    past_days = sorted(pa.loc[pa.date < cutoff, 'date'].unique())
    if len(past_days) <= 2 * WINDOW_DAYS:
        raise ValueError('Insufficient distinct training dates')
    tune = str(pd.Timestamp(past_days[-2*WINDOW_DAYS]).date())
    calibrate = str(pd.Timestamp(past_days[-WINDOW_DAYS]).date())
    first = training_pitches(prepared, tune)
    valid = prepared[(prepared.date >= tune) & (prepared.date < calibrate)]
    probe, player, league = fit_tree(first, ITERATIONS[-1])
    vals = features(valid, apply_tendencies(fit_tendencies(first), valid), player, league)
    losses = {i: float(log_loss(valid.cls, pred, labels=probe.classes_))
              for i, pred in enumerate(probe.staged_predict_proba(vals), 1) if i in ITERATIONS}
    best = min(losses, key=losses.get)
    print(f'{cutoff}: {len(first)} training pitches, {len(valid)} tuning pitches, {best} iterations', flush=True)
    del probe, first, vals
    trained = training_pitches(prepared, calibrate)
    tree, player, league = fit_tree(trained, best)
    simulator = Simulator(trained, {'gbt': tree}, fit_tendencies(trained), player, league)
    model = MLModel(cutoff, simulator, 0.0)
    reference = samples(decorate(pa[(pa.date >= calibrate) & (pa.date < cutoff)]))
    predictions = score_tree(model, reference)
    model.offset = float(np.mean(predictions - reference.RE24.to_numpy()))
    model._abs_cache.clear()
    keys = list(reference[['batter','bhand','pitcher']].itertuples(index=False, name=None))
    model.calibrate(keys)
    model._abs_cache.clear()
    model._ref.clear()
    model.training_version = TRAINING_VERSION
    model.training_samples = {'pitches': len(trained), 'first_date': str(trained.date.min().date()),
                              'last_date': str(trained.date.max().date()), 'tuning_started': tune,
                              'selected_iterations': best, 'policy': 'chronological_whole_game_dates'}
    model.calibration_reference = {'policy': 'held_out_observed_RE24_mean_offset',
                                   'pa_ids': list(reference.pa_id),
                                   'first_date': str(reference.date.min().date()),
                                   'last_date': str(reference.date.max().date())}
    if not model.training_samples['last_date'] < model.calibration_reference['first_date'] <= model.calibration_reference['last_date'] < cutoff:
        raise ValueError('Chronological split crossed its cutoff')
    return model, losses


def validate(cutoff, candidate):
    pa, pitches, _ = load()
    stop = pd.Timestamp(cutoff) + pd.offsets.MonthBegin()
    rows = samples(decorate(pa[(pa.date >= cutoff) & (pa.date < stop)]))
    weight = ROOT / 'models/gbt_full_v5.pkl'
    manifest = json.loads((weight.parent / 'active-batch.json').read_bytes())
    reference = next(r for r in manifest['models'] if r['cutoff']=='2026-01-01' and r['name']==weight.name)
    if sha256(weight.read_bytes()).hexdigest() != reference['sha256']:
        raise ValueError('Published preseason reference hash does not match')
    previous = _load_weight(weight, reference['cutoff'])
    prior = pitches[pitches.date < cutoff]
    hierarchy = fit(cutoff)
    estimate = np.asarray([hierarchy.matchup(b, h, p)['per_pa'] for b,h,p in
                           rows[['batter','bhand','pitcher']].itertuples(index=False, name=None)])
    preseason = score_tree(previous, rows)
    updated = score_tree(candidate, rows)
    prior_pa = pa[pa.date < cutoff]
    predictions = {'league': np.full(len(rows), prior_pa.RE24.mean()), 'hierarchy': estimate,
                   'preseason_tree': preseason, 'chronological_tree': updated,
                   'reference_ensemble': (estimate+preseason)/2, 'candidate_ensemble': (estimate+updated)/2}
    rows = rows[['game','pa_id','inning','outs','bat_team','fld_team','RE24','batter','pitcher']].copy()
    rows['sparse'] = (rows.pitcher.map(prior.pitcher.value_counts()).fillna(0)<100) | (
        rows.batter.map(prior.batter.value_counts()).fillna(0)<100)
    for name, predicted in predictions.items():
        if not np.isfinite(predicted).all():
            raise ValueError(f'Nonfinite forecast: {name}')
        rows[name] = predicted
    return rows.drop(columns=['batter','pitcher'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cutoff', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    runtime = settings()
    if runtime.data_seasons != (2024,2025,2026) or args.cutoff not in (*runtime.replay_cutoffs, runtime.cutoff):
        parser.error('Use the explicit 2024–2026 runtime and a configured cutoff')
    args.out.mkdir(parents=True, exist_ok=False)
    model, losses = train(args.cutoff)
    target = args.out / 'model.pkl'
    with target.with_suffix('.partial').open('xb') as stream:
        pickle.dump(model, stream, pickle.HIGHEST_PROTOCOL)
    target.with_suffix('.partial').rename(target)
    if args.cutoff != runtime.cutoff:
        validate(args.cutoff, model).to_csv(args.out / 'predictions.csv', index=False)
    receipt = dict(cutoff=args.cutoff, sha256=sha256(target.read_bytes()).hexdigest(),
                   training=model.training_samples, calibration=model.calibration_reference,
                   validation_log_loss=losses)
    (args.out / 'receipt.json').write_text(json.dumps(receipt, indent=2, allow_nan=False), encoding='utf8')


if __name__ == '__main__':
    main()
