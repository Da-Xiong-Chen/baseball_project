"""Descriptive depth/coverage audit. Does NOT select or validate a reliability gate."""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def quantile(values, p):
    values = sorted(values)
    if not values:
        return None
    index = (len(values)-1)*p
    lo = int(index)
    hi = min(lo+1, len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(index-lo)


def main():
    files = sorted((ROOT/'data/rebas/2024').glob('*.json')) + sorted((ROOT/'data/rebas/2025').glob('*.json'))
    games = [json.loads(p.read_text(encoding='utf8')) for p in files]
    distributions = {}
    for cutoff in ('2025-04-01', '2025-07-01', '2026-01-01'):
        totals = {'hitters': defaultdict(int), 'pitchers': defaultdict(int)}
        missing = 0
        for game in games:
            if game['date'][:10] >= cutoff:
                continue
            for side in ('away', 'home'):
                for role, box, field in (('hitters', 'BatterBox', 'PA'), ('pitchers', 'PitcherBox', 'IPOuts')):
                    for row in game[side+box]:
                        if not row.get('playerId') or row.get(field) is None:
                            missing += 1
                            continue
                        totals[role][row['playerId']] += int(row[field])
        distributions[cutoff] = {'missing_identity_or_depth_rows': missing}
        for role, by_id in totals.items():
            positive = [v for v in by_id.values() if v > 0]
            gates = (20, 50, 100, 200) if role == 'hitters' else (15, 30, 60, 90)
            distributions[cutoff][role] = dict(positive_ids=len(positive), recorded_ids=len(by_id),
                unit='PA' if role == 'hitters' else 'outs',
                quantiles={str(p): quantile(positive, p) for p in (.25, .5, .75)},
                passes={str(g): sum(v >= g for v in positive) for g in gates})
    depth = json.loads((ROOT/'docs/data/qualification.json').read_text(encoding='utf8'))
    results = []
    for file in sorted((ROOT/'docs/data/replay').glob('*.json')):
        if file.name != 'games.json':
            results.extend(json.loads(file.read_text(encoding='utf8'))['results'].values())
    assert all(r['ml_cutoff'] <= r['model_cutoff'] <= r['situation']['date'] for r in results)
    coverage = []
    baseline = {'offense': 0, 'defense': 0}
    for min_pa in (20, 50, 100, 200):
        for min_outs in (15, 30, 60, 90):
            counts = {'offense': 0, 'defense': 0}
            for r in results:
                own = depth['cutoffs'][r['model_cutoff']]
                for mode in counts:
                    pen = mode == 'defense'
                    rows = r['bullpen']['rows'] if pen else r['candidates']
                    usable = [x for x in rows if pen or x.get('守備') != 'bad']
                    current = next(x for x in rows if x['角色'] == ('場上' if pen else '現任'))
                    if len(usable) < 2 or current not in usable or any(x.get('機器學習') is None for x in usable):
                        continue
                    if min_pa == 20 and min_outs == 15:
                        baseline[mode] += 1
                    table, key, minimum = ('pitchers', '投手', min_outs) if pen else ('hitters', '球員', min_pa)
                    eligible = [x for x in usable if own[table].get(x[key], [0])[0] >= minimum]
                    other_ok = all(own['hitters'].get(n, [0])[0] >= min_pa for n in r['bullpen']['next']) if pen else own['pitchers'].get(r['situation']['pitcher'], [0])[0] >= min_outs
                    if len(eligible) >= 2 and current in eligible and other_ok:
                        counts[mode] += 1
            coverage.append(dict(min_pa=min_pa, min_outs=min_outs, **counts))
    for row in coverage:
        assert all(0 <= row[k] <= baseline[k] for k in baseline)
        for stricter in coverage:
            if stricter['min_pa'] >= row['min_pa'] and stricter['min_outs'] >= row['min_outs']:
                assert all(stricter[k] <= row[k] for k in baseline)
    report = dict(raw_games=len(games), replay_snapshots=len(results), distributions=distributions,
        no_depth_gate_comparable=baseline, coverage=coverage,
        interpretation='Descriptive only. ID-grouped positive exposure distributions include all recorded roles (including emergency pitchers), not current roster. Replay cases are selected historical substitution snapshots, not a representative sample of all games. Coverage uses unique ID display labels and strictly pre-cutoff depth. This script does not evaluate outcome error or select a gate.')
    target = ROOT/'output/decision_v3/sample-threshold-audit.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
