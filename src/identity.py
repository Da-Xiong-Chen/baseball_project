"""Stable labels for the verified same-name collision in Rebas 2024–2025.

Box-score playerId is the identity. PA/event rows lack that ID, so resolve names
through their game's team box, never through later team membership.
"""
from collections import defaultdict
from functools import lru_cache

SOURCE_NAMESPACE = 'rebas:CPBL'


def source_key(value):
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    return SOURCE_NAMESPACE + ':' + value


def game_rosters(game):
    """Index one game's own boxes; never resolve against a global name list."""
    result = {}
    for side in ('away', 'home'):
        roles = {role: defaultdict(set) for role in ('batter', 'pitcher', 'catcher')}
        for suffix, role in (('BatterBox', 'batter'), ('PitcherBox', 'pitcher')):
            for player in game[side + suffix]:
                name = player.get('playerName')
                if isinstance(name, str) and name:
                    key = source_key(player.get('playerId'))
                    roles[role][name].add(key)
                    roles['catcher'][name].add(key)
        result[side] = roles
    return result


def participant_key(rosters, side, role, name):
    if not isinstance(name, str) or not name:
        return None
    candidates = rosters[side][role].get(name, set())
    return next(iter(candidates)) if len(candidates) == 1 and None not in candidates else None


@lru_cache(maxsize=128)
def labels(cutoff=None, inclusive=False):
    """Human labels from dated source observations, keyed by immutable IDs."""
    import pandas as pd
    from load import load
    boxes = load()[2]
    if cutoff:
        day = pd.Timestamp(cutoff)
        boxes = boxes[boxes.date <= day] if inclusive else boxes[boxes.date < day]
    boxes = boxes.sort_values(['date', 'game'], kind='stable')
    latest = boxes.drop_duplicates('name', keep='last')
    collisions = latest.groupby('raw_name')['name'].nunique()
    short = {'中信兄弟':'中信', '統一7-ELEVEn獅':'統一', '樂天桃猿':'樂天',
             '富邦悍將':'富邦', '味全龍':'味全', '台鋼雄鷹':'台鋼'}
    out = {}
    for row in latest.itertuples():
        label = row.raw_name
        if collisions.get(label, 0) > 1:
            label += '〔' + short.get(row.team, row.team) + '〕'
        out[row.name] = label
    return out


def display_name(player, cutoff=None, inclusive=False):
    if not isinstance(player, str) or not player.startswith(SOURCE_NAMESPACE + ':'):
        return player
    return labels(cutoff, inclusive).get(player, '未有姓名紀錄的球員')


def resolve_player(value, cutoff=None, team=None, role=None):
    """Compatibility input: accept names only when dated/team evidence is unique."""
    import pandas as pd
    from load import load
    rows = load()[2]
    if cutoff:
        rows = rows[rows.date < pd.Timestamp(cutoff)]
    if team:
        rows = rows[rows.team == team]
    if role:
        rows = rows[rows.role == role]
    if value in set(rows.name):
        return value
    candidates = set(rows.loc[rows.raw_name == value, 'name'])
    # Legacy disambiguated UI labels are presentation aliases, never model IDs.
    if not candidates:
        candidates = {key for key, label in labels(cutoff).items() if label == value and key in set(rows.name)}
    if len(candidates) != 1:
        raise ValueError('球員名稱無法唯一辨識，請重新選取球隊與球員')
    return next(iter(candidates))


IDENTITIES={'gdEku':('林子崴','林子崴〔統一〕'), 'yhCr':('林子崴','林子崴〔樂天〕')}


def normalize_game(game):
    # Mutates only the already-parsed in-memory game; raw files stay intact.
    aliases={}
    for side in ('away','home'):
        team=game.get(side+'Team')
        if not team:continue
        mapping={}
        for role in ('Batter','Pitcher'):
            for player in game.get(side+role+'Box',[]):
                ident=str(player.get('playerId',''))
                if ident in IDENTITIES:
                    original,canonical=IDENTITIES[ident]
                    if player.get('playerName') in (original,canonical):
                        mapping[original]=canonical
                        player['playerName']=canonical
        aliases[side]=mapping
    for side in ('away','home'):
        other='home' if side=='away' else 'away'
        for pa in game.get(side+'PAList',[]):
            for obj in [pa,*pa.get('events',[])]:
                for field,owner in [('batterName',side),('pitcherName',other),('catcherName',other)]:
                    value=obj.get(field)
                    if value in aliases.get(owner,{}):obj[field]=aliases[owner][value]
    return game
