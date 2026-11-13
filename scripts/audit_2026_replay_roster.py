"""Reconcile replay participants and candidate availability with dated source data."""

import argparse
from collections import Counter
import json
from pathlib import Path

from evaluate_rolling_recency import load
from historical_actors import decorate
from roster import active_roster
from runtime_config import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    if settings().season!=2026 or args.out.exists():
        parser.error('Use the explicit 2026 runtime and a new output file')
    root = args.site
    index = json.loads((root/'index.json').read_bytes())
    raw, _, boxes = load()
    cutoff = index['date']
    day = decorate(raw[raw.date.astype(str)==cutoff]).set_index('pa_id',verify_integrity=True)
    actual = boxes[boxes.game.isin(index['games'])]
    prior = boxes[boxes.date.astype(str)<cutoff]
    aliases = prior.groupby('name').raw_name.nunique()
    teams = prior.groupby('name').team.nunique()
    totals, games = Counter(), {}
    for game, ids in index['games'].items():
        recorded = json.loads((root/f'{game}.json').read_bytes())['pas']
        if {p['pa_id'] for p in recorded}!=set(ids):
            raise ValueError(f'Index mismatch: {game}')
        game_box = actual[actual.game==game]
        game_counts = Counter()
        for team in game_box.team.unique():
            for role, pool in zip(('B','P'), active_roster(team, day.loc[ids[0]].date, game)):
                box_rows = game_box[(game_box.team==team)&(game_box.role==role)]
                if role=='P':
                    box_rows = box_rows[box_rows.order>1]
                known = set(box_rows.name)
                estimate = set(pool)
                label = 'hitter' if role=='B' else 'pitcher'
                game_counts.update({f'{label}_appeared':len(known),f'{label}_estimated':len(estimate),
                                    f'{label}_appeared_and_estimated':len(known & estimate),
                                    f'{label}_appeared_missing_from_estimate':len(known-estimate)})
        used = {}
        for entry in recorded:
            pid = entry['pa_id']
            source = day.loc[pid]
            roles = ('batter','pitcher','start_batter','start_pitcher')
            if any(entry[name]!=source[name] for name in roles):
                raise ValueError(f'Source actor mismatch: {pid}')
            game_counts['pa'] += 1
            game_counts['mid_pa_actor_changes'] += int(entry['mid_pa_actor_change'])
            for name in roles:
                player = entry[name]
                team = source.bat_team if name.endswith('batter') else source.fld_team
                if not ((game_box.name==player)&(game_box.team==team)).any():
                    raise ValueError(f'Actor missing from same-team box: {pid} {name}')
                game_counts['actors_with_historical_aliases'] += int(aliases.get(player,0)>1)
                game_counts['actors_with_historical_team_changes'] += int(teams.get(player,0)>1)
            bullpen = used.setdefault(source.fld_team,set())
            bundle = json.loads((root/index['files'][pid]).read_bytes())
            if bundle.get('pen'):
                rows = bundle['pen']['bullpen']['rows']
                incumbent = bundle['pen']['situation']['pitcher']
                candidates = {r['投手'] for r in rows if r['角色']=='牛棚'}
                if candidates & (bullpen | {incumbent}):
                    raise ValueError(f'Used pitcher included in candidates: {pid}')
                game_counts['bullpen_candidate_checks'] += len(candidates)
            bullpen.update((entry['start_pitcher'],entry['pitcher']))
        totals.update(game_counts)
        games[game]=dict(game_counts)
    report = {'date':cutoff,'batch_id':index['batch_id'],'totals':dict(totals),'games':games,
              'scope':'Compared prior appearance estimates with actual box-score hitters and relievers. No official registration or eligibility labels.'}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps(report['totals'],indent=2))


if __name__=='__main__':
    main()
