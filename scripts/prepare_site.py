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
    for game in read_json(site / 'data/replay/games.json'):
        local_asset(site, f'data/replay/{game["game"]}.json')
    for index in (site / 'data/replay').glob('day-*/index.json'):
        manifest=read_json(index)
        if manifest.get('schema_version')!=1 or manifest.get('pa_count')!=len(manifest.get('files',{})):
            raise ValueError(f'Invalid daily replay index: {index}')
        for pid,filename in manifest['files'].items():
            target=local_asset(site,str((index.parent / filename).relative_to(site)))
            bundle=read_json(target)
            if bundle.get('pa_id')!=pid or bundle.get('date')!=manifest.get('date'):
                raise ValueError(f'Daily replay identity mismatch: {pid}')
            for result in [bundle.get('ph'),bundle.get('pen')]:
                if result is not None and not (result['ml_cutoff']<=result['model_cutoff']<=bundle['date']):
                    raise ValueError(f'Daily replay future data: {pid}')
            if hashlib.sha256(target.read_bytes()).hexdigest()!=manifest.get('sha256',{}).get(pid):
                raise ValueError(f'Daily replay checksum mismatch: {pid}')
    for index in (site / 'data/pitch-change').glob('*/index.json'):
        for filename in read_json(index)['pitchers'].values():
            local_asset(site, str((index.parent / filename).relative_to(site)))
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
