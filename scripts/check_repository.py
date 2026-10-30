"""Offline syntax and current-document link checks. Historical records stay historical."""
import argparse
import ast
import json
from pathlib import Path
import re
import subprocess
import unicodedata
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCS = ['README.md', '協作指南.md', 'docs/技術細節.md', 'docs/qa/README.md',
    'presentations/competition-2026/README.md', 'docs/training-v5.md', 'docs/ci-validation.md',
    'docs/qa/code-review-20261029/README.md', 'docs/qa/review-fixes-20261029/README.md',
    'docs/qa/release-readiness-20261029/README.md']


def prose(text):
    return re.sub(r'```.*?```', '', text, flags=re.S)


def anchors(path):
    used, result = {}, set()
    for text in re.findall(r'^#{1,6}\s+(.+)$', prose(Path(path).read_text(encoding='utf-8-sig')), re.M):
        text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
        text = re.sub('<[^>]+>', '', text).replace('`', '').lower()
        slug = ''.join(c for c in text if c.isspace() or c in '-_' or unicodedata.category(c)[0] in ('L', 'N', 'M')).replace(' ', '-')
        number = used.get(slug, 0); used[slug] = number + 1
        result.add(slug if not number else slug + '-' + str(number))
    return result


def check_links(root, names):
    root = Path(root).resolve(); errors = []; count = 0
    for name in names:
        path = root / name
        if not path.is_file():
            errors.append({'file': name, 'issue': 'missing current document'}); continue
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', prose(path.read_text(encoding='utf-8-sig'))):
            parts = urlsplit(target.split(' "')[0].strip('<>'))
            if parts.scheme or parts.netloc: continue
            count += 1
            dest = (path.parent / unquote(parts.path)).resolve() if parts.path else path.resolve()
            if not dest.is_relative_to(root) or not dest.exists():
                errors.append({'file': name, 'target': target, 'issue': 'missing or out-of-repository target'})
            elif parts.fragment and dest.suffix == '.md' and unquote(parts.fragment) not in anchors(dest):
                errors.append({'file': name, 'target': target, 'issue': 'missing heading'})
    return {'local_links': count, 'documents': len(names), 'errors': errors}


def check(root=ROOT, node='node'):
    root = Path(root); python_files = list(root.glob('*.py'))
    for directory in ('src', 'scripts', 'tests'): python_files.extend((root / directory).glob('*.py'))
    for path in python_files: ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    javascript = list((root / 'docs').glob('*.js'))
    for path in javascript: subprocess.run([node, '--check', str(path)], check=True, capture_output=True)
    links = check_links(root, CURRENT_DOCS)
    if links['errors']: raise ValueError(json.dumps(links, ensure_ascii=False))
    return {'python_syntax': len(python_files), 'javascript_syntax': len(javascript), **links}


if __name__ == '__main__':
    import os
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--node', default=os.environ.get('NODE_BINARY', 'node'))
    args = parser.parse_args()
    print(json.dumps(check(node=args.node), ensure_ascii=True, indent=2))
