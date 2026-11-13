"""Export season fielding appearances from Rebas opening and in-play snapshots."""

import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path

from audit_2026_fielding_coverage import POSITIONS
from validate_2026_fielding_evidence import identities


def collect(source, season):
    appearances = defaultdict(set)
    games = set()
    opening = observed = unresolved = 0
    for path in sorted(source.glob('*.json')):
        game = json.loads(path.read_bytes())
        if not game['date'].startswith(f'{season}-') or game['seq'] in games:
            raise ValueError(f'Wrong season or duplicate game: {path}')
        games.add(game['seq'])
        for fielding, batting in (('away','home'),('home','away')):
            roster = identities(game,fielding)
            team = game[fielding+'Team']
            for pa in game[batting+'PAList']:
                snapshots = [pa.get('fielderNames'), *(e.get('fielderNames') for e in pa['events'])]
                opening += 1
                for index, names in enumerate(snapshots):
                    if names is None:
                        continue
                    if not isinstance(names,list) or len(names)!=len(POSITIONS):
                        raise ValueError(f'Invalid defensive snapshot: {path}')
                    observed += int(index==0)
                    for pos,name in zip(POSITIONS,names):
                        if name is None:
                            continue
                        player = roster.get(name)
                        if player is None:
                            unresolved += 1
                            continue
                        appearances[player,team,pos].add(game['seq'])
    if not games or not appearances:
        raise ValueError('No fielding snapshots in this input season')
    return appearances, {'games':len(games),'pa_records':opening,'opening_arrays':observed,
                         'unresolved_observations':unresolved,'rows':len(appearances)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--season',type=int,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    rows,counts = collect(args.source,args.season)
    args.out.mkdir(parents=True,exist_ok=False)
    with (args.out/'positions.csv').open('x',encoding='utf-8-sig',newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(('season','player_id','team','position','observed_games'))
        writer.writerows((args.season,*key,len(games)) for key,games in sorted(rows.items()))
    with (args.out/'receipt.json').open('x',encoding='utf-8') as stream:
        json.dump({'season':args.season,**counts,
                   'scope':'Distinct games observed at each defensive position; excludes DH and does not measure defensive opportunities.',
                   'source':'https://github.com/rebas-tw/rebas.tw-open-data/releases/tag/v0.1.1-2026'},
                  stream,ensure_ascii=False,indent=2)
    print(json.dumps(counts))


if __name__=='__main__':
    main()
