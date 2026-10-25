"""Read-only intake gate for explicitly selected Rebas seasons; no model adoption."""
import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def audit(root, seasons):
    errors, warnings, reports, manifest = [], [], [], []
    names, identities = defaultdict(set), defaultdict(set)
    registry = {}
    game_ids = set()
    for season in sorted(set(seasons)):
        files = sorted((Path(root) / str(season)).glob('*.json'))
        row = dict(season=season, files=len(files), games=0, plate_appearances=0,
                   pitches=0, dates=[], teams=set(), missing_pitch_values=Counter(),
                   invalid_pitch_values=Counter(),unresolved_pa_names=Counter())
        if not files:
            errors.append(dict(season=season, issue='missing_season_files'))
        for path in files:
            label = f'{season}/{path.name}'
            raw = path.read_bytes()
            manifest.append(dict(file=label, sha256=hashlib.sha256(raw).hexdigest()))
            try:
                def reject_constant(value):
                    raise ValueError('nonfinite JSON number: '+value)
                g = json.loads(raw,parse_constant=reject_constant)
                day = date.fromisoformat(g['date'][:10])
                seq = g['seq']
                if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
                    raise ValueError('invalid game sequence')
                if day.year != season:
                    raise ValueError('date does not match selected season')
                gid = f'{season}-{seq:03d}'
                if gid in game_ids:
                    raise ValueError('duplicate season/game identity')
                game_ids.add(gid)
                for side in ('away', 'home'):
                    if not isinstance(g[side+'Team'], str) or not g[side+'Team']:
                        raise ValueError('missing team name')
                    for suffix in ('BatterBox', 'PitcherBox', 'PAList'):
                        if not isinstance(g[side+suffix], list):
                            raise ValueError('invalid '+side+suffix)
                if g['awayTeam'] == g['homeTeam']:
                    raise ValueError('identical opponents')
                boxes = {}
                for side in ('away', 'home'):
                    row['teams'].add(g[side+'Team'])
                    boxes[side] = defaultdict(set)
                    for role in ('Batter', 'Pitcher'):
                        for player in g[side+role+'Box']:
                            if not isinstance(player,dict):raise ValueError('invalid box player')
                            name, pid = player.get('playerName'), player.get('playerId')
                            if not name or not pid:
                                raise ValueError('box player missing name or identity')
                            pid = str(pid)
                            boxes[side][name].add(pid)
                            names[name].add(pid)
                            identities[pid].add(name)
                            entry=registry.setdefault(pid,dict(player_id=pid,names={},seasons=set(),teams=set()))
                            entry['seasons'].add(season);entry['teams'].add(g[side+'Team'])
                            history=entry['names'].setdefault(name,dict(first_seen=day.isoformat(),last_seen=day.isoformat()))
                            history['first_seen']=min(history['first_seen'],day.isoformat())
                            history['last_seen']=max(history['last_seen'],day.isoformat())
                for side in ('away', 'home'):
                    other = 'home' if side == 'away' else 'away'
                    for pa_index,pa in enumerate(g[side+'PAList']):
                        if not isinstance(pa,dict):raise ValueError('invalid PA object')
                        for key in ('inning','outs','bases','batterName','pitcherName','events',
                                    'awayScores','homeScores','endAwayScores','endHomeScores',
                                    'endOuts','endBases','batterHand','pitcherHand','catcherName',
                                    'isPH','paOrder','WPA','RE24','homeWE'):
                            if key not in pa:
                                raise ValueError('PA missing '+key)
                        if not isinstance(pa['events'], list):
                            raise ValueError('PA events must be a list')
                        for key, lo, hi in [('inning',1,30),('outs',0,2),('bases',0,7)]:
                            value = pa[key]
                            if isinstance(value,bool) or not isinstance(value,int) or not lo <= value <= hi:
                                raise ValueError('invalid PA '+key)
                        for field, owner in [('batterName',side),('pitcherName',other)]:
                            if len(boxes[owner].get(pa[field],set())) != 1:
                                row['unresolved_pa_names'][field] += 1
                        row['plate_appearances'] += 1
                        for event_index,event in enumerate(pa['events']):
                            if not isinstance(event,dict):raise ValueError('invalid event object')
                            if event.get('type') != 'PITCH':
                                continue
                            for key in ('pitchCode','pitchType','coordX','coordY','catcherName'):
                                if key not in event:raise ValueError('pitch missing '+key)
                            for key in ('coordX','coordY','velocity'):
                                value=event.get(key)
                                if value not in (None,''):
                                    try:
                                        if isinstance(value,bool) or not math.isfinite(float(value)):
                                            raise ValueError('nonfinite or boolean')
                                    except (ValueError,TypeError):
                                        row['invalid_pitch_values'][key]+=1
                                        errors.append(dict(file=label,issue='invalid_pitch_'+key,half=side,
                                            pa_index=pa_index,event_index=event_index,raw_value=value))
                            row['pitches'] += 1
                            for key in ('pitchType','coordX','coordY','velocity'):
                                if event.get(key) in (None,''):
                                    row['missing_pitch_values'][key] += 1
                row['games'] += 1
                row['dates'].append(day.isoformat())
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(dict(file=label, issue=str(exc)))
        dates = row.pop('dates')
        row['date_start'] = min(dates) if dates else None
        row['date_end'] = max(dates) if dates else None
        row['teams'] = sorted(row['teams'])
        for key in ('missing_pitch_values','invalid_pitch_values','unresolved_pa_names'):
            row[key] = dict(row[key])
            if row[key]: warnings.append(dict(season=season, issue=key, counts=row[key]))
        reports.append(row)
    collisions = {n:sorted(ids) for n,ids in sorted(names.items()) if len(ids)>1}
    aliases = {pid:sorted(ns) for pid,ns in sorted(identities.items()) if len(ns)>1}
    for entry in registry.values():
        entry['seasons']=sorted(entry['seasons']);entry['teams']=sorted(entry['teams'])
    if collisions: warnings.append(dict(issue='same_name_multiple_ids',players=len(collisions)))
    if aliases: warnings.append(dict(issue='same_id_multiple_names',players=len(aliases)))
    return dict(schema='baseball.season-intake.v1', structural_passed=not errors,
                model_ready=False, model_ready_note='Structural audit is not model, fielding, hand or temporal validation.',
                seasons=reports, same_name_multiple_ids=collisions, same_id_multiple_names=aliases,
                identity_registry=registry, identity_policy='Join by box playerId within game/team; retain dated aliases; never merge on name alone.',
                errors=errors, warnings=warnings, source_manifest=manifest)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=ROOT/'data/rebas')
    p.add_argument('--seasons',nargs='+',type=int,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args(); result=audit(args.root,args.seasons)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_manifest','same_name_multiple_ids','same_id_multiple_names','identity_registry')},ensure_ascii=False,indent=2))
    if not result['structural_passed']:raise SystemExit(1)


if __name__=='__main__':main()
