"""Explicit v5 source manifests and verified private training snapshots."""
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def inventory(data_root, seasons):
    root = Path(data_root).resolve()
    result = {}
    for year in seasons:
        files = sorted((root / 'rebas' / str(year)).glob('*.json'))
        if not files:
            raise ValueError(f'Missing configured season: {year}')
        seen = set()
        for path in files:
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('Source must stay inside data root')
            row = json.loads(path.read_text(encoding='utf8'))
            seq = row.get('seq')
            if type(seq) is not int or seq < 1 or str(row.get('date', ''))[:4] != str(year) or seq in seen:
                raise ValueError('Invalid or duplicate game identity: ' + path.name)
            seen.add(seq)
            result[path.relative_to(root).as_posix()] = digest(path)
    for pattern in ('cpbl/*.csv', 'ldkrsi/*.csv'):
        for path in sorted(root.glob(pattern)):
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('Source must stay inside data root')
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def create_manifest(data_root, seasons, destination):
    files = inventory(data_root, seasons)
    manifest = {'schema': 'baseball.training-input.v1', 'seasons': list(seasons), 'files': files}
    manifest['dataset_id'] = fingerprint(files)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return manifest


def verify_source(data_root, manifest_path, seasons):
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf8'))
    if (manifest.get('schema') != 'baseball.training-input.v1' or manifest.get('seasons') != list(seasons)
            or not isinstance(manifest.get('files'), dict) or not manifest['files']
            or manifest.get('dataset_id') != fingerprint(manifest['files'])):
        raise ValueError('Invalid training input manifest')
    actual = inventory(data_root, seasons)
    if actual != manifest['files']:
        raise ValueError('Training input changed: file set or SHA differs from source manifest')
    return manifest


def snapshot(data_root, manifest_path, seasons, destination):
    """Never train from mutable caller inputs; retain interrupted copies for inspection."""
    manifest = verify_source(data_root, manifest_path, seasons)
    root, destination = Path(data_root).resolve(), Path(destination).resolve()
    if root == destination or root in destination.parents or destination in root.parents:
        raise ValueError('Snapshot must be separate from input data')
    if destination.exists():
        verify_source(destination, manifest_path, seasons)
        return destination
    temp = destination.with_name(destination.name + '.building')
    temp.mkdir()  # interrupted builds are not silently overwritten
    for rel, sha in manifest['files'].items():
        source, target = root / rel, temp / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if digest(target) != sha:
            raise ValueError('Input changed during snapshot: ' + rel)
    verify_source(temp, manifest_path, seasons)
    temp.rename(destination)
    return destination
