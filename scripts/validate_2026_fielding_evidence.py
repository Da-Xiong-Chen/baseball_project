"""Measure recognition of observed post-pinch-hit defensive roles without lookahead."""

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

from audit_2026_fielding_coverage import opening_fielders

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from identity import source_key
from roster import CATCHER_MIN_PITCHES, MIN_GAMES, catcher_pitches, position_games
from runtime_config import settings


def identities(game, side):
    names = defaultdict(set)
    for role in ('BatterBox','PitcherBox'):
        for row in game[f'{side}{role}']:
            names[row['playerName']].add(source_key(row['playerId']))
    return {name:next(iter(ids)) for name,ids in names.items() if len(ids)==1}


def observations(source):
    history, positives, movement = defaultdict(set), [], []
    totals = Counter()
    for file in sorted(source.glob('*.json')):
        game = json.loads(file.read_bytes())
        date = game['date'][:10]
        game_id = f'{date[:4]}-{file.stem}'
        for own, other, next_inning in (('away','home',0),('home','away',1)):
            ids = identities(game,own)
            fielding = defaultdict(list)
            for pa in game[other+'PAList']:
                lineup = opening_fielders(pa)
                fielding[pa['inning']].append(lineup)
                for name,pos in (lineup or {}).items():
                    if name in ids:
                        history[ids[name],pos].add((date,game_id))
            prior_batters = {}
            for i,pa in enumerate(game[own+'PAList']):
                name, slot = pa['batterName'], pa['paOrder']
                previous_batter = prior_batters.get(slot)
                prior_batters[slot] = name
                if not pa.get('isPH'):
                    continue
                actors = {e.get('batterName') for e in pa['events'] if e.get('type')=='PITCH'}
                upcoming = fielding[pa['inning']+next_inning]
                if name not in ids or actors!={name} or not upcoming or not upcoming[0]:
                    continue
                totals['traceable_following_half'] += 1
                after = upcoming[0]
                old_half = fielding[pa['inning']+next_inning-1]
                before = old_half[-1] if old_half else None
                changed = {ids[n]:[before[n],after[n]] for n in before.keys() & after.keys()
                           if n in ids and before[n]!=after[n]} if before else {}
                if changed:
                    movement.append({'game':game_id,'date':date,'half':own,'pa_index':i,'changed':changed})
                if before and previous_batter and previous_batter in ids:
                    totals['previous_batter_observed_in_prior_defense' if previous_batter in before
                           else 'previous_batter_absent_from_prior_defense'] += 1
                if name in after:
                    positives.append({'date':date,'game':game_id,'half':own,'pa_index':i,
                                      'player':ids[name],'position':after[name]})
                else:
                    totals['pinch_hitter_absent_at_opening'] += 1
    return history, positives, movement, totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--preseason-fielders',type=Path,help='Verified re-export with prior-season defensive snapshots')
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    if settings().season!=2026 or args.out.exists():
        parser.error('Use the explicit 2026 runtime and a new output file')
    history, positives, movement, totals = observations(args.source)
    if len(positives)==0:
        raise ValueError('No observed defensive positives')
    dates = {key:sorted(day for day,_ in games) for key,games in history.items()}
    cutoff = '2026-01-01'
    preseason_observations = None
    if args.preseason_fielders:
        preseason_observations = observations(args.preseason_fielders)[0]
        if not preseason_observations or any(day>=cutoff for games in preseason_observations.values() for day,_ in games):
            raise ValueError('Preseason fielders must only contain prior-season observations')
    past_positions = position_games(cutoff)
    past_catcher_pitches = catcher_pitches(cutoff)
    roles = defaultdict(Counter)
    for case in positives:
        player,pos = case['player'],case['position']
        earlier = bisect_left(dates.get((player,pos),[]),case['date'])
        old_games = float(past_positions.get((player,pos),0))
        catching = pos=='C' and past_catcher_pitches.get(player,0)>=CATCHER_MIN_PITCHES
        # A frozen seasonal baseline isolates the effect of new observed positions.
        baseline = old_games>=MIN_GAMES or catching
        augmented = old_games+earlier>=MIN_GAMES or catching
        case.update(prior_2026_games_at_position=earlier,preseason_recognized=bool(baseline),
                    augmented_recognized=bool(augmented))
        roles[pos].update({'observed':1,'preseason_recognized':int(baseline),'augmented_recognized':int(augmented)})
        if preseason_observations is not None:
            # These observations overlap the official annual summary. Use the
            # stronger evidence source rather than double counting the same games.
            prior_observed = len(preseason_observations.get((player,pos),set()))
            supplement = max(old_games,prior_observed)+earlier>=MIN_GAMES or catching
            case.update(prior_observed_games_at_position=prior_observed,supplemented_recognized=bool(supplement))
            roles[pos]['supplemented_recognized'] += int(supplement)
    report = {'scope':'Observed positives, one opening snapshot per qualifying pinch hit. No DH or true-negative labels.',
              'preseason_cutoff':cutoff, 'totals':dict(totals),'positions':{k:dict(v) for k,v in sorted(roles.items())},
              'cases':positives,'retained_players_changed_positions_between_snapshots':movement}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps({'totals':report['totals'],'positions':report['positions'],'position_change_cases':len(movement)},indent=2))


if __name__=='__main__':
    main()
