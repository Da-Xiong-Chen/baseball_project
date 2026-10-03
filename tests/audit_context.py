"""All exported replay context versus raw within-game observations."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from load import load
from game_context import count_before, pitch_offsets


def main():
    pa,p,_=load()
    lookup=pa.set_index('pa_id')
    cases=0
    corrected=0
    for file in (ROOT/'docs/data/replay').glob('*.json'):
        if file.name=='games.json':continue
        for pid,result in json.loads(file.read_text(encoding='utf8'))['results'].items():
            row=lookup.loc[pid]
            n,starter=count_before(row)
            assert result['situation']['pitch_count']==n,(pid,n)
            assert result['situation']['starter']==starter
            ctx=result['context']
            assert not ctx['positions_confirmed'] and not ctx['roster_confirmed']
            assert ctx['roster_source']=='prior-10-days'
            assert not ctx['pitcher_capacity_known'] and not ctx['defensive_quality_measured']
            assert ctx['horizon_batters']==len(result['bullpen']['next'])<=3
            assert all(c['守備']=='warn' and '當場守位未確認' in c['守備說明'] for c in result['candidates'])
            prior=pa[(pa.game==row.game)&(pa.half==row.half)&(pa.seq<row.seq)]
            old=int(((p.pa_id.isin(prior.pa_id))&(p.pitcher==row.pitcher)).sum())
            corrected+=old!=n
            cases+=1
    offsets=pitch_offsets()
    assert all((pid,int(j)) in offsets for pid,j in zip(p.pa_id,p.j))
    report=dict(cases=cases,raw_event_count_matches=cases,training_filtered_count_differences=corrected,
                offsets_covered=len(p),all_historical_positions_marked_unconfirmed=True,errors=0)
    out=ROOT/'output/decision_v4';out.mkdir(parents=True,exist_ok=True)
    (out/'context-audit.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
