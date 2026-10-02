"""Export date-safe snapshots for GitHub Pages without training any models."""
import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from pitch_change import ROOT, SCHEMA, compare, observations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', type=int, default=2025)
    args = parser.parse_args()
    out = ROOT / 'docs/data/pitch-change' / str(args.season)
    out.mkdir(parents=True, exist_ok=True)
    index = dict(schema_version=SCHEMA, season=args.season, pitchers={})
    dataset = observations()
    if not dataset:
        raise SystemExit('Run python download_data.py first')
    for name, records in sorted(dataset.items()):
        days = sorted({a['date'] for a in records if a['date'][:4] == str(args.season)})
        if not days:
            continue
        key = hashlib.sha256(name.encode()).hexdigest()[:16] + '.json'
        snapshots = []
        for cutoff in [f'{args.season}-01-01'] + [(date.fromisoformat(d)+timedelta(days=1)).isoformat() for d in days]:
            snapshots.append(dict(effective_from=cutoff, hands={
                h: compare(records, name, args.season, cutoff, h) for h in ('ALL', 'L', 'R')}))
        (out / key).write_text(json.dumps(dict(schema_version=SCHEMA, snapshots=snapshots),
                               ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf8')
        index['pitchers'][name] = key
    (out / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf8')
    print(f"Exported {len(index['pitchers'])} pitchers to {out}")


if __name__ == '__main__':
    main()
