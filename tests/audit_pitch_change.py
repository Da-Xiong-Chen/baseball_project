"""Full exported-data invariants AND recomputation; produces reproducible evidence."""
import json
import sys
import time
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pitch_change import ROOT, observations, compare


def main():
    start = time.perf_counter()
    root = ROOT / 'docs/data/pitch-change/2025'
    index = json.loads((root/'index.json').read_text(encoding='utf8'))
    records = observations()
    totals = Counter()
    sizes = []
    for name, key in index['pitchers'].items():
        assert Path(key).name == key
        p = root/key
        sizes.append(p.stat().st_size)
        snapshots = json.loads(p.read_text(encoding='utf8'))['snapshots']
        assert len({s['effective_from'] for s in snapshots}) == len(snapshots)
        assert [s['effective_from'] for s in snapshots] == sorted(s['effective_from'] for s in snapshots)
        for snap in snapshots:
            for hand, d in snap['hands'].items():
                actual = compare(records[name], name, 2025, snap['effective_from'], hand)
                assert actual == d, (name, snap['effective_from'], hand)
                b, r = d['windows']['baseline'], d['windows']['recent']
                assert not {g['game'] for g in b['games']} & {g['game'] for g in r['games']}
                for w, cap in ((b,10),(r,5)):
                    assert w['selected_games'] <= cap
                    assert w['effective_games'] <= w['selected_games']
                    assert all(g['date'] < d['cutoff'] and g['date'].startswith('2025') for g in w['games'])
                for i in range(2):
                    values=[row['adjusted'][i] for row in d['rows']]
                    if values[0] is not None:
                        assert all(0 <= v <= 1+1e-12 for v in values)
                        assert abs(sum(values)-1)<1e-10
                    raw=[row['raw'][i] for row in d['rows']]
                    if raw[0] is not None: assert abs(sum(raw)-1)<1e-10
                weights=[s['weight'] for s in d['strata'] if s['included']]
                if weights: assert abs(sum(weights)-1)<1e-10
                for row in d['rows']:
                    if row['interval']:
                        assert -100 <= row['interval'][0] <= row['interval'][1] <= 100
                assert (d['status']=='ready') == (len(d['reasons'])==0)
                totals[d['status']]+=1
                totals['recomputed']+=1
                json.dumps(d,allow_nan=False)
    report=dict(pitchers=len(index['pitchers']), totals=dict(totals), elapsed_seconds=time.perf_counter()-start,
                total_bytes=sum(sizes), maximum_pitcher_bytes=max(sizes), median_pitcher_bytes=sorted(sizes)[len(sizes)//2],
                errors=0, scope='all exported snapshots and all three hands; exact Python recomputation')
    out=ROOT/'output/qa';out.mkdir(parents=True,exist_ok=True)
    (out/'data_audit.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
