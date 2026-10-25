"""Compare the production adapter with the independently verified source-ID store."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from load import load, pitches_before


def short_pa(key):
    return key.removeprefix('rebas:CPBL:').replace(':','-')


def audit(db, baseline):
    pa,p,boxes = load()
    errors=[]
    with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        expected_pa=pd.read_sql_query('SELECT pa_key,batter_player_key AS batter,pitcher_player_key AS pitcher,catcher_player_key AS catcher FROM plate_appearances',conn)
        expected_pa['pa_id']=expected_pa.pa_key.map(short_pa)
        expected_p=pd.read_sql_query('SELECT pa_key,pitch_index AS j,event_index,batter_player_key AS batter,pitcher_player_key AS pitcher,catcher_player_key AS catcher,velocity_raw_json FROM pitch_events',conn)
        expected_p['pa_id']=expected_p.pa_key.map(short_pa)
    for name,actual,expected,keys in [('pa',pa,expected_pa,['pa_id']),('pitch',p,expected_p,['pa_id','j'])]:
        combined=actual.merge(expected,on=keys,suffixes=('_actual','_expected'),how='outer',indicator=True,validate='one_to_one')
        if (combined._merge!='both').any():errors.append({'scope':name,'issue':'missing_or_extra_keys','n':int((combined._merge!='both').sum())})
        for role in ('batter','pitcher','catcher'):
            bad=combined[role+'_actual']!=combined[role+'_expected']
            if bad.any():errors.append({'scope':name,'issue':role+'_identity','n':int(bad.sum())})
        if name=='pitch':
            bad=combined.event_index_actual!=combined.event_index_expected
            if bad.any(): errors.append({'scope':name,'issue':'event_index','n':int(bad.sum())})
            def velocity(raw):
                value=json.loads(raw)
                try: value=float(value) if not isinstance(value,bool) else np.nan
                except (ValueError,TypeError): value=np.nan
                return value if np.isfinite(value) and 80<=value<=170 else np.nan
            velocities=combined.velocity_raw_json.map(velocity)
            if not np.allclose(combined.velo,velocities,equal_nan=True):errors.append({'scope':'pitch','issue':'velocity_alignment'})
    future={}
    for hand in ('bhand','phand'):
        n=int((p[hand+'_evidence_date']>p.date).sum());future[hand]=n
        if n:errors.append({'issue':'future_hand_evidence','hand':hand,'n':n})
    hashes=json.loads(baseline.read_text(encoding='utf8'))['raw']
    for rel,expected in hashes.items():
        if hashlib.sha256((ROOT/'data/rebas'/rel).read_bytes()).hexdigest()!=expected: errors.append({'issue':'changed_raw','file':rel})
    prior=pitches_before('2025-09-01')
    if not (prior.date<pd.Timestamp('2025-09-01')).all():errors.append({'issue':'training_cutoff'})
    if pa.pa_id.duplicated().any() or p.duplicated(['pa_id','j']).any():errors.append({'issue':'duplicated_keys'})
    if not boxes.name.str.startswith('rebas:CPBL:').all():errors.append({'issue':'non_id_box_key'})
    return {'passed':not errors,'errors':errors,'raw_files_checked':len(hashes),
            'pa':len(pa),'pitches':len(p),'box_observations':len(boxes),'player_ids':boxes.name.nunique(),
            'participant_differences':{r:int((p[r]!=p['pa_'+r]).sum()) for r in ('batter','pitcher','catcher')},
            'unknown_hands':{h:int((~p[h].isin(['L','R'])).sum()) for h in ('bhand','phand')},
            'hand_evidence':{h:p[h+'_source'].value_counts().to_dict() for h in ('bhand','phand')},
            'future_hand_evidence':future,'training_cutoff':'strictly_before_2025-09-01',
            'unknown_hand_policy':'retain raw rows; exclude unresolved hand-conditioned training rows; average supported L/R scenarios at query time',
            'nonterminal_inplay_pitch_count':int((p.code.eq('H') & ~p['last']).sum())}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity-db',type=Path,required=True)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():raise FileExistsError(args.out)
    result=audit(args.identity_db,args.baseline)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=True,indent=2))
    if not result['passed']:raise SystemExit(1)
