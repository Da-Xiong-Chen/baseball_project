"""Compare fixed-pool rankings in a dated September 2026 diagnostic."""
import argparse
import json
from pathlib import Path

from evaluate_matchup_horizons_2026 import dated_hands, kernels, load, np, pa_model, pd, predict_short, prepare, sides
from engine import bat_hand, situation

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    CUTOFF=pd.Timestamp('2026-09-01')
    pa,_,boxes=load()
    frame,edges,_,_=prepare(pa,boxes)
    train=frame[frame.date<CUTOFF]
    m=pa_model(train,'players')
    league,classes,pitchers=kernels(edges[edges.date<CUTOFF],m.classes_)
    hands=dated_hands(train)
    phands=train.groupby('pitcher').phand.agg(lambda s:s.value_counts().index[0])
    reference=json.loads(args.reference.read_bytes())
    out=[]
    for case in reference['ranking_cases']:
        if not case['date'].startswith('2026-09'):
            continue
        # v5 candidate eligibility and ordering are taken from the earlier dated
        # comparison; verify equal eligible sets before using them.
        row=frame.loc[case['pa_id']] if case['pa_id'] in frame.index else None
        if row is None:
            continue
        scene=situation(row.pa_id)
        day=str(CUTOFF.date())
        state=int(row.outs)*8+int(row.bases)
        base={'state':state,'inning':row.inning,'half':row.half,'score_diff':row.score_diff,
              'outs':row.outs,'bases':row.bases,'inning_group':min(row.inning,10)}
        for role in ('ph','pen'):
            ref,alt=[case[key][role] for key in ('reference','chronological')]
            if not ref['top'] or ref['eligible']!=alt['eligible']:
                continue
            if role=='ph':
                candidates=ref['eligible']
                table=sides(pd.DataFrame([{**base,'batter':b,'pitcher':row.pitcher,
                      'bhand':bat_hand(b,row.phand,day),'phand':row.phand} for b in candidates]))
                expected=train[train.outs.eq(row.outs)&train.bases.eq(row.bases)].groupby('outcome').RE24.mean()
                expected=expected.reindex(m.classes_).fillna(train.groupby('outcome').RE24.mean())
                values=m.predict_proba(table)@expected.to_numpy()
                order=np.argsort(-values,kind='stable')
            else:
                candidates=ref['eligible']
                lineup=scene['lineup']
                order_no=sorted(lineup)
                if row.pa_order not in order_no:
                    continue
                i=order_no.index(row.pa_order)
                batters=[scene['due']]+[lineup[order_no[(i+k)%len(order_no)]] for k in (1,2)]
                table=pd.DataFrame([{**base,'pitcher':p,'phand':phands.get(p,'U'),
                                     **dict(zip(('b1','b2','b3'),batters))} for p in candidates])
                values=predict_short(table,m,league,classes,pitchers,hands)[:,2]@np.arange(13)
                order=np.argsort(values,kind='stable')
            top=[candidates[i] for i in order[:3]]
            out.append({'pa_id':row.pa_id,'role':role,'pool':len(candidates),'v5':ref['top'],
                        'chronological':alt['top'],'new':top,'new_score':float(values[order[0]])})
    assert out
    report={'cutoff':str(CUTOFF.date()),'scope':'Ranking agreement, no correctness labels. Identical estimated eligible pool per role. New three-batter run scores do not include fatigue adjustment.',
            'summary':{role:{'n':sum(r['role']==role for r in out),
                             'top1_changed_from_v5':sum(r['role']==role and r['new'][0]!=r['v5'][0] for r in out)}
                       for role in ('ph','pen')},'cases':out}
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(report['summary'],flush=True)


if __name__ == '__main__':
    main()
