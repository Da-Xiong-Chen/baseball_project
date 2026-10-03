"""Observed game facts only; no inferred roster, fielding position or capacity."""
import json
from functools import lru_cache
from pathlib import Path
from identity import game_identity, resolve_game


@lru_cache(maxsize=32)
def raw_game(game_id):
    year, seq = game_id.split('-')
    root = Path(__file__).resolve().parents[1] / 'data/rebas' / year
    expected = root / f'中職{year}年-G{int(seq):03d}.json'
    for path in ([expected] if expected.exists() else root.glob('*.json')):
        game = json.loads(path.read_text(encoding='utf8'))
        if int(game['seq']) == int(seq):
            return game
    raise ValueError(f'找不到原始比賽：{game_id}')


def observed_pitch_count(game, batting_side, sequence, pitcher_id):
    """Count actual prior PITCH events, including pitches excluded from training.

    Never include the selected PA or later events. A mid-PA change is attributed
    via the event pitcher and the fielding team's IDs, not the PA summary.
    """
    fielding_side = 'home' if batting_side == 'away' else 'away'
    identities = game_identity(game)[fielding_side]
    count = 0
    for pa in game[batting_side + 'PAList'][:sequence]:
        for event in pa['events']:
            if event['type'] == 'PITCH':
                name = event.get('pitcherName') or pa['pitcherName']
                if resolve_game(identities, name) == pitcher_id:
                    count += 1
    return count


def count_before(row):
    game = raw_game(row['game'])
    if not row.get('pitcher_id'):
        raise ValueError('無法辨識當場投手，不推估已投球數')
    n = observed_pitch_count(game, row['half'], int(row['seq']), row['pitcher_id'])
    side = 'home' if row['half'] == 'away' else 'away'
    first = game[side + 'PitcherBox'][0]
    return n, first.get('playerId') == row['pitcher_id']


@lru_cache(maxsize=1)
def pitch_offsets():
    """Within-game exposure; later games cannot alter earlier offsets."""
    from load import _game_files
    result = {}
    for path in _game_files():
        game = json.loads(Path(path).read_text(encoding='utf8'))
        gid = f"{game['date'][:4]}-{int(game['seq']):03d}"
        identities = game_identity(game)
        for batting in ('away', 'home'):
            fielding = 'home' if batting == 'away' else 'away'
            counts = {}
            for seq, pa in enumerate(game[batting+'PAList']):
                pid = f'{gid}-{batting[0]}{seq:03d}'
                for j, event in enumerate(e for e in pa['events'] if e['type']=='PITCH'):
                    pitcher = resolve_game(identities[fielding], event.get('pitcherName') or pa['pitcherName'])
                    if pitcher:
                        result[(pid,j)] = counts.get(pitcher,0)
                        counts[pitcher] = counts.get(pitcher,0)+1
    return result
