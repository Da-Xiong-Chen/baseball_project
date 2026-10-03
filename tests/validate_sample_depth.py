"""Retrospective monthly out-of-time outcome evaluation, not causal substitution validation."""
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from load import load
from model import fit
import mlmodel


def summary(frame):
    if frame.empty:
        return {'n': 0}
    loss = frame.assign(base_loss=(frame.y-frame.baseline)**2,
                        h_loss=(frame.y-frame.h)**2, e_loss=(frame.y-frame.ensemble)**2)
    grouped = loss.groupby('game')[['base_loss', 'h_loss', 'e_loss']].sum()
    rng = np.random.default_rng(20261003)
    sums = grouped.to_numpy()[rng.integers(0, len(grouped), size=(1000, len(grouped)))].sum(1)
    gains = 100*(1-sums[:, 2]/sums[:, 0])
    return dict(n=len(frame), games=frame.game.nunique(), batter_ids=frame.batter_id.nunique(),
                pitcher_ids=frame.pitcher_id.nunique(), baseline_mse=float(loss.base_loss.mean()),
                hierarchy_mse=float(loss.h_loss.mean()), ensemble_mse=float(loss.e_loss.mean()),
                ensemble_gain_percent=float(100*(1-loss.e_loss.sum()/loss.base_loss.sum())),
                gain_ci95_percent=np.quantile(gains, [.025, .975]).tolist())


def main():
    pa, _, boxes = load()
    rows = []
    months = [f'2025-{m:02d}-01' for m in range(5, 12)]
    for cutoff, end in zip(months, months[1:]):
        train = pa[pa.date < cutoff]
        test = pa[(pa.date >= cutoff) & (pa.date < end)].dropna(subset=['RE24', 'batter_id', 'pitcher_id'])
        m, ml = fit(cutoff), mlmodel.get(cutoff)
        past = boxes[boxes.date < cutoff]
        bat_pa = past[past.role == 'B'].groupby('player_id').PA.sum()
        pit = past[past.role == 'P'].groupby('player_id')[['NP', 'IPOuts']].sum()
        queries = list(test[['batter_id', 'bhand', 'pitcher_id']].itertuples(index=False, name=None))
        # Bounded batches avoid expanding a full month's PA x 150 historical pitches at once.
        g = np.concatenate([ml.abs_many(queries[i:i+150]) for i in range(0, len(queries), 150)])
        h = [m.matchup(b, bh, p)['per_pa'] for b, bh, p in queries]
        for (_, r), hp, gp in zip(test.iterrows(), h, g):
            rows.append(dict(game=r.game, date=str(r.date.date()), month=cutoff, batter_id=r.batter_id,
                pitcher_id=r.pitcher_id, y=float(r.RE24), baseline=float(train.RE24.mean()),
                h=float(hp), ensemble=float((hp+gp)/2), bat_pa=float(bat_pa.get(r.batter_id, 0)),
                pit_np=float(pit.NP.get(r.pitcher_id, 0)), pit_outs=float(pit.IPOuts.get(r.pitcher_id, 0))))
        print(cutoff, len(test), flush=True)
    frame = pd.DataFrame(rows)
    out = ROOT/'output/decision_v3'; out.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out/'sample-depth-predictions.csv', index=False, encoding='utf-8')
    report = dict(training_version=mlmodel.TRAINING_VERSION,
        interpretation='Retrospective out-of-time actual-PA outcomes. May-July exploration; Aug-Oct confirmation already historically examined, not untouched prospective test. Gates select different populations. Gains compare model vs baseline on the same subset, not causal gain from gating or evidence of counterfactual candidate rankings. Game-cluster bootstrap 1000; repeat-player dependence remains a limitation.',
        periods={}, gates=[], strata={})
    for label, subset in [('all', frame), ('exploration', frame[frame.month < '2025-08-01']),
                          ('confirmation', frame[frame.month >= '2025-08-01'])]:
        report['periods'][label] = summary(subset)
        for min_pa in (0, 20, 50, 100, 200):
            for min_outs, min_np in ((0,0), (15,100), (30,300), (60,0), (60,600), (90,900)):
                eligible = subset[(subset.bat_pa >= min_pa) & (subset.pit_outs >= min_outs) & (subset.pit_np >= min_np)]
                report['gates'].append(dict(period=label, min_pa=min_pa, min_outs=min_outs, min_np=min_np,
                                            coverage=len(eligible)/len(subset), **summary(eligible)))
        report['strata'][label] = {}
        for column, bins in [('bat_pa', [0,20,50,100,200,np.inf]),
                             ('pit_outs', [0,15,30,60,90,np.inf]), ('pit_np', [0,100,300,600,900,np.inf])]:
            report['strata'][label][column] = [dict(lower=lo, upper=None if np.isinf(hi) else hi,
                **summary(subset[(subset[column] >= lo) & (subset[column] < hi)])) for lo,hi in zip(bins,bins[1:])]
    assert frame.date.ge(frame.month).all()
    assert np.isfinite(frame[['y','h','ensemble','baseline']].to_numpy()).all()
    for period, stats in report['periods'].items():
        for strata in report['strata'][period].values():
            assert sum(s['n'] for s in strata) == stats['n']
    (out/'sample-depth-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report['periods'], indent=2))


if __name__ == '__main__':
    main()
