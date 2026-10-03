"""Identity from box-score IDs; never infer an ambiguous PA by name alone."""
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
import json


@lru_cache(maxsize=1)
def catalog():
    names = defaultdict(set)
    for path in sorted((Path(__file__).resolve().parents[1]/'data/rebas').glob('*/*.json')):
        game = json.loads(path.read_text(encoding='utf8'))
        for side in ('away', 'home'):
            for role in ('BatterBox', 'PitcherBox'):
                for row in game[side+role]:
                    if row.get('playerId'):
                        names[row['playerName']].add(row['playerId'])
    return dict(names)


def display(name, player_id):
    # Labels are identity metadata, not ability features or eligibility evidence.
    return f'{name}〔{player_id}〕' if player_id and len(catalog().get(name, ())) > 1 else name


def game_identity(game):
    by_team = {}
    for side in ('away', 'home'):
        names = defaultdict(set)
        for role in ('BatterBox', 'PitcherBox'):
            for row in game[side+role]:
                if row.get('playerId'):
                    names[row['playerName']].add(row['playerId'])
        by_team[side] = names
    return by_team


def resolve_game(names, name):
    ids = names.get(name, set())
    return next(iter(ids)) if len(ids) == 1 else None


def aliases(frame, id_column, name_column):
    pairs = frame[[id_column, name_column]].dropna().drop_duplicates()
    groups = pairs.groupby(name_column)[id_column].agg(set)
    return {name: next(iter(ids)) for name, ids in groups.items() if len(ids) == 1}


def key(value, mapping):
    # IDs are accepted directly. Unresolved names are not present in ID tables.
    return mapping.get(value, value)


def display_aliases(mapping, observed_ids):
    result = dict(mapping)
    for name, ids in catalog().items():
        if len(ids) > 1:
            result.pop(name, None)
            for player_id in ids & set(observed_ids):
                result[display(name, player_id)] = player_id
    return result
