"""Stable labels for the verified same-name collision in Rebas 2024–2025.

Box-score playerId is the identity. PA/event rows lack that ID, so resolve names
through their game's team box, never through later team membership.
"""
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
