"""Export personal observed depth only, strictly before each cutoff; no pooling."""
import json
from collections import defaultdict
from pathlib import Path
from identity import display

ROOT = Path(__file__).resolve().parents[1]
MIN_PA = 1  # Observation existence, not a statistical reliability threshold.
MIN_OUTS = 0  # A pitcher may record pitches without recording an out.


def profile(games, cutoff):
    hitters, pitchers = defaultdict(lambda: [0, None]), defaultdict(lambda: [0, None])
    identities = defaultdict(set)
    by_id = {'hitters': defaultdict(lambda: [0, None]), 'pitchers': defaultdict(lambda: [0, None, 0])}
    for game in games:
        date = game['date'][:10]
        if date >= cutoff:
            continue
        for side in ('away', 'home'):
            for role in ('BatterBox', 'PitcherBox'):
                for row in game[side+role]:
                    if row.get('playerId'):
                        identities[row['playerName']].add(row['playerId'])
            for row in game[side+'BatterBox']:
                rec = hitters[row['playerName']]
                rec[0] += int(row['PA'])
                rec[1] = max(rec[1] or date, date)
                if row.get('playerId'):
                    own = by_id['hitters'][row['playerId']]
                    own[0] += int(row['PA']); own[1] = max(own[1] or date, date)
            for row in game[side+'PitcherBox']:
                rec = pitchers[row['playerName']]
                if row.get('IPOuts') is None:
                    # Unknown outs cannot count toward qualification.
                    continue
                rec[0] += int(row['IPOuts'])
                rec[1] = max(rec[1] or date, date)
                if row.get('playerId'):
                    own = by_id['pitchers'][row['playerId']]
                    own[0] += int(row['IPOuts']); own[1] = max(own[1] or date, date)
                    own[2] += int(row.get('NP') or 0)
    ambiguous = sorted(n for n, ids in identities.items() if len(ids) > 1)
    # The model is still name-keyed: never qualify a merged identity for recommendations.
    for name in ambiguous:
        hitters.pop(name, None)
        pitchers.pop(name, None)
    for name, ids in identities.items():
        for player_id in ids:
            label = f'{name}〔{player_id}〕' if name in ambiguous else display(name, player_id)
            for table, legacy in (('hitters', hitters), ('pitchers', pitchers)):
                if player_id in by_id[table]:
                    legacy[label] = by_id[table][player_id]
    return dict(hitters=dict(hitters), pitchers=dict(pitchers), ambiguous=ambiguous,
                by_id={k: dict(v) for k, v in by_id.items()})


def main():
    files = sorted((ROOT/'data/rebas/2024').glob('*.json')) + sorted((ROOT/'data/rebas/2025').glob('*.json'))
    games = [json.loads(f.read_text(encoding='utf8')) for f in files]
    dates = sorted({g['date'][:10] for g in games if g['date'].startswith('2025')} | {'2026-01-01'})
    result = dict(version=2, policy=dict(min_pa=MIN_PA, min_outs=MIN_OUTS, min_np=1,
                  mode='observed-only', reliability_validated=False, decision_validated=False,
                  evidence='output/decision_v3/sample-depth-validation.json',
                  scope='Personal identity and nonzero observations only. PA for hitters; NP and integer outs for pitchers. No validated minimum depth or substitution ranking guarantee.'),
                  cutoffs={date: profile(games, date) for date in dates})
    out = ROOT/'docs/data/qualification.json'
    out.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')), encoding='utf8')
    print(f'{len(files)} games, {len(dates)} cutoffs; {out.stat().st_size} bytes')


if __name__ == '__main__':
    main()
