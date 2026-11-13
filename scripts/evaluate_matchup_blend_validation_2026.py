"""Confirm fixed and early-tuned RE24 blends in a later 2026 time window."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from evaluate_half_inning_2026 import paired_interval
from evaluate_rolling_recency import np, pd


SPLIT = pd.Timestamp('2026-07-01')
WEIGHTS = np.linspace(0, 1, 11)


def tuned_weight(train):
    def loss(weight):
        prediction = (1-weight)*train.chronological_prediction + weight*train.players_prediction
        return float((prediction-train.RE24).pow(2).mean())
    return float(min(WEIGHTS, key=loss))


def compare(rows, weight):
    result = {'pa':len(rows), 'games':int(rows.game.nunique())}
    if rows.empty:
        return result
    errors = {}
    for name, values in {
        'chronological': rows.chronological_prediction,
        'players': rows.players_prediction,
        'fixed_blend': (rows.chronological_prediction+rows.players_prediction)/2,
        'early_tuned_blend': (1-weight)*rows.chronological_prediction+weight*rows.players_prediction,
    }.items():
        errors[name] = (values-rows.RE24)**2
    baseline = errors['chronological']
    for name, error in errors.items():
        delta = error-baseline
        result[name] = {'mse':float(error.mean()), 'delta':float(delta.mean()),
                        'paired_game_ci':paired_interval(rows,delta) if result['games']>1 else None}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scores', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    rows = pd.read_csv(args.scores,parse_dates=['date']).set_index('pa_id',verify_integrity=True)
    fields = ['chronological_prediction','players_prediction','RE24']
    rows = rows.dropna(subset=fields)
    if not np.isfinite(rows[fields]).all().all():
        raise ValueError('Non-finite scores')
    train, later = rows[rows.date<SPLIT],rows[rows.date>=SPLIT]
    if train.empty or later.empty or set(train.game)&set(later.game):
        raise ValueError('Expected disjoint early and later games')
    weight = tuned_weight(train)
    groups = {'all':later, 'pinch_hit':later[later.is_ph],
              'actual_replacement':later[later.replacement],
              'late_close':later[later.inning.ge(8)&later.score_diff.abs().le(1)]}
    report = {'scope':'Internal temporal sensitivity on previously used 2026 data. No independent adoption holdout.',
              'split':str(SPLIT.date()), 'tuning_pa':len(train),'tuning_games':int(train.game.nunique()),
              'early_tuned_players_weight':weight, 'later':{k:compare(v,weight) for k,v in groups.items()},
              'scores_sha256':sha256(args.scores.read_bytes()).hexdigest()}
    with args.out.open('x',encoding='utf-8') as out:
        json.dump(report,out,indent=2,allow_nan=False)


if __name__=='__main__':
    main()
