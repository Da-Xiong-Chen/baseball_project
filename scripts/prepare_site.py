"""Check the static site, optionally copy a clean hosting bundle. No network or Git writes.

Run from any directory: python scripts/prepare_site.py [--output output/site-release]
The output must be a new directory inside this repository's output/. Nothing is deleted.
"""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    def reject_constant(value):
        raise ValueError(f'Invalid JSON number {value}: {path}')
    return json.loads(path.read_text(encoding='utf8'), parse_constant=reject_constant)


class Entry(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs, self.ids, self.duplicates = [], set(), []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            if attrs['id'] in self.ids:
                self.duplicates.append(attrs['id'])
            self.ids.add(attrs['id'])
        for key in ('href', 'src'):
            if attrs.get(key):
                self.refs.append(attrs[key])


def local_asset(site, url):
    parts = urlsplit(url)
    if parts.scheme or parts.netloc or not parts.path:
        return None
    if parts.path.startswith('/'):
        raise ValueError(f'Root-relative asset breaks project subpaths: {url}')
    path = (site / unquote(parts.path)).resolve()
    if not path.is_relative_to(site.resolve()) or not path.is_file():
        raise ValueError(f'Missing or out-of-site asset: {url}')
    return path


def inspect_site(site):
    site = site.resolve()
    entry = Entry()
    entry.feed((site / 'index.html').read_text(encoding='utf8'))
    if entry.duplicates:
        raise ValueError(f'Duplicate HTML IDs: {entry.duplicates}')
    assets = {site / 'index.html', site / '.nojekyll'}
    for ref in entry.refs:
        path = local_asset(site, ref)
        if path:
            assets.add(path)
    # CSS URLs, if introduced later, must also work without a domain-root mount.
    for css in tuple(p for p in assets if p.suffix == '.css'):
        for url in re.findall(r'url\(\s*[\'"]?([^\'"\)]+)', css.read_text(encoding='utf8')):
            path = local_asset(css.parent, url.strip())
            if path:
                if not path.is_relative_to(site):
                    raise ValueError(f'CSS asset outside site: {url}')
                assets.add(path)
    data = list((site / 'data').rglob('*.json'))
    if not data:
        raise ValueError('No exported data found')
    for path in data:
        if not path.resolve().is_relative_to(site):
            raise ValueError(f'Data symlink outside site: {path}')
        read_json(path)
    assets.update(data)
    # Check dynamic replay and pitch-change references, not just the HTML shell.
    # 舊版整季回放清單只在存在時檢查；網站目前只發布單日回放（day-*）
    games = site / 'data/replay/games.json'
    for game in (read_json(games) if games.exists() else []):
        local_asset(site, f'data/replay/{game["game"]}.json')
    day_indexes = {p.parent.name.removeprefix('day-'): p for p in (site / 'data/replay').glob('day-*/index.json')}
    catalog = site / 'data/replay/dates.json'
    evidence_required = False
    if catalog.exists():
        listing = read_json(catalog)
        evidence_required = listing.get('evidence_schema') == 1
        dates = [row['date'] for row in listing['days']]
        if (listing['schema_version'] != 1 or len(set(dates)) != len(dates)
                or listing['default_date'] not in dates or set(dates) != set(day_indexes)):
            raise ValueError('Replay date catalog disagrees with released days')
        for row in listing['days']:
            manifest = read_json(day_indexes[row['date']])
            if (row['games'] != len(manifest['games']) or row['pa'] != manifest['pa_count']
                    or row['batch_id'] != manifest['batch_id']):
                raise ValueError(f"Replay date catalog metadata disagrees: {row['date']}")
            for case in (row.get('case'), row.get('observed_case')):
                if case and (case['decision'] not in ('ph','pen')
                             or case['pa'] not in manifest['games'].get(case['game'], [])):
                    raise ValueError(f"Replay featured case is unavailable: {row['date']}")
    for index in day_indexes.values():
        manifest=read_json(index)
        if manifest.get('schema_version')!=1 or manifest.get('pa_count')!=len(manifest.get('files',{})):
            raise ValueError(f'Invalid daily replay index: {index}')
        if 'schedule' in manifest:
            batch=manifest['batch_id']
            day=manifest['date']
            if (index.parent.name!='day-'+day or manifest['season']!=int(day[:4])
                    or manifest['model_cutoff']!=day
                    or manifest['ml_cutoff']!=day[:7]+'-01'
                    or not manifest['training_last_date']<manifest['ml_cutoff']<=day
                    or not manifest['calibration_last_date']<manifest['ml_cutoff']):
                raise ValueError(f'Daily replay has inconsistent cutoffs: {index}')

            def day_asset(filename):
                target=local_asset(site, str((index.parent / filename).relative_to(site)))
                payload=read_json(target)
                if payload.get('batch_id')!=batch:
                    raise ValueError(f'Mixed daily replay batch: {target}')
                return payload

            ids={g['game'] for g in manifest['schedule'] if g['date']==manifest['date']}
            if ids!=set(manifest['games']) or len(ids)!=len(manifest['schedule']):
                raise ValueError(f'Daily schedule and index disagree: {index}')
            indexed_ids=[pid for game in manifest['games'].values() for pid in game]
            if len(indexed_ids)!=len(manifest['files']) or set(indexed_ids)!=set(manifest['files']):
                raise ValueError(f'Daily PA coverage disagrees: {index}')
            replay_pas = {}
            for game in sorted(ids):
                payload=day_asset(game+'.json')
                if payload['date']!=manifest['date'] or [r['pa_id'] for r in payload['pas']]!=manifest['games'][game]:
                    raise ValueError(f'Daily game and index disagree: {game}')
                replay_pas.update((r['pa_id'], r) for r in payload['pas'])
            supporting={name:day_asset(name) for name in ('context.json','timing.json','fielding-plans.json')}
            for name, payload in supporting.items():
                if payload['date']!=day:
                    raise ValueError(f'Daily asset has wrong date: {name}')
            if supporting['fielding-plans.json']['replay_index_sha256']!=hashlib.sha256(index.read_bytes()).hexdigest():
                raise ValueError(f'Daily fielding plans are for a different index: {index}')
            timing=supporting['timing.json']
            if timing['season']!=manifest['season'] or set(timing['games'])!=ids:
                raise ValueError(f'Daily timing coverage disagrees: {index}')
            if evidence_required:
                evidence=day_asset('evidence.json')
                fielding, availability=evidence['fielding'], evidence['availability']
                actual_pinch_hits={pa for pa, row in replay_pas.items() if row.get('is_ph')}
                if (evidence['schema_version']!=1 or evidence['date']!=day
                        or set(fielding)!=actual_pinch_hits or set(availability)-set(indexed_ids)):
                    raise ValueError(f'Daily observation coverage disagrees: {index}')
                positions={'P','C','1B','2B','3B','SS','LF','CF','RF'}
                for pa, row in fielding.items():
                    game, _=pa.rsplit('-',1)
                    status=row['status']
                    observed=row.get('observed_pa')
                    actual=status in {'pinch_hitter_fielded','other_player_fielded'}
                    initial=replay_pas[pa]
                    following=replay_pas.get(observed,{})
                    next_inning=initial['inning']+int(initial['half']=='home')
                    if (status not in {'pinch_hitter_fielded','other_player_fielded','unconfirmed','no_defensive_half'}
                            or (actual and (observed not in manifest['games'][game] or following['half']==initial['half']
                                or following['inning']!=next_inning))
                            or (not actual and observed is not None)
                            or (status=='pinch_hitter_fielded' and row.get('position') not in positions)
                            or ('opening_fielder' in row and (status!='other_player_fielded'
                                or row.get('original_position') not in positions or not row['opening_fielder']))):
                        raise ValueError(f'Invalid observed fielding: {pa}')
                for pa, reasons in availability.items():
                    if replay_pas[pa]['inning']<6 or not reasons or any(kind not in {'ph','pen'} or reason not in (
                        {'no_prior_pool','all_used','fielding_unconfirmed'} if kind=='ph' else {'no_prior_pool','all_used'}
                    ) for kind, reason in reasons.items()):
                        raise ValueError(f'Invalid replay candidate evidence: {pa}')
            pitch=day_asset('pitch/index.json')
            if pitch['season']!=manifest['season']:
                raise ValueError(f'Daily pitch index has wrong season: {index}')
            for filename in pitch['pitchers'].values():
                for snap in day_asset('pitch/'+filename)['snapshots']:
                    if snap['effective_from']!=manifest['date']:
                        raise ValueError(f'Daily pitch cutoff disagrees: {filename}')
        for pid,filename in manifest['files'].items():
            target=local_asset(site,str((index.parent / filename).relative_to(site)))
            bundle=read_json(target)
            if bundle.get('pa_id')!=pid or bundle.get('date')!=manifest.get('date'):
                raise ValueError(f'Daily replay identity mismatch: {pid}')
            if bundle.get('batch_id')!=manifest.get('batch_id'):
                raise ValueError(f'Daily replay batch mismatch: {pid}')
            for result in [bundle.get('ph'),bundle.get('pen')]:
                if result is not None and not (result['ml_cutoff']<=result['model_cutoff']<=bundle['date']):
                    raise ValueError(f'Daily replay future data: {pid}')
                if result is not None and 'schedule' in manifest and (
                        result.get('batch_id')!=batch or result['ml_cutoff']!=manifest['ml_cutoff']
                        or result['model_cutoff']!=manifest['model_cutoff']):
                    raise ValueError(f'Daily replay decision disagrees with the index: {pid}')
            if hashlib.sha256(target.read_bytes()).hexdigest()!=manifest.get('sha256',{}).get(pid):
                raise ValueError(f'Daily replay checksum mismatch: {pid}')
    for index in (site / 'data/pitch-change').glob('*/index.json'):
        for filename in read_json(index)['pitchers'].values():
            local_asset(site, str((index.parent / filename).relative_to(site)))
    if not games.exists() and not any((site / 'data/replay').glob('day-*/index.json')):
        raise ValueError('No replay index found')
    for path in assets:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'Not a regular release file: {path}')
        if path.suffix.lower() in {'.pkl', '.csv', '.pem', '.key', '.env'}:
            raise ValueError(f'Private/source artifact in release: {path}')
    return sorted(assets)


def prepare(site, output=None):
    site = site.resolve()
    files = inspect_site(site)
    manifest = {str(p.relative_to(site)).replace('\\', '/'): {
        'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()
    } for p in files}
    if output:
        output = output.resolve()
        parent = (ROOT / 'output').resolve()
        if not output.is_relative_to(parent) or output == parent:
            raise ValueError('Output must be a new subdirectory of this repository output/')
        if output.exists():
            raise ValueError('Output already exists; choose a new directory (no files overwritten)')
        output.mkdir(parents=True)
        for source in files:
            target = output / source.relative_to(site)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        (output / 'release-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
    return {'files': len(files), 'json_files': sum(p.suffix == '.json' for p in files),
            'bytes': sum(p.stat().st_size for p in files),
            'output': str(output) if output else None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(ROOT / 'docs', args.output), indent=2))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'Release check failed: {error}\n')
