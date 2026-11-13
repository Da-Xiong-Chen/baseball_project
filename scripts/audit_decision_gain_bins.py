"""Check historical score-gap bands using only observed incumbents' outcomes."""
import argparse
import json
from pathlib import Path

from evaluate_rolling_recency import load, np, pd
from historical_actors import decorate

BANDS = ('<0.5','0.5–1','1–2','≥2')
SEED = 20261112
DRAWS = 2000


def summarize(frame):
    means = {}
    games = sorted(frame.game.unique())
    if not games:
        return means
    positions = np.random.default_rng(SEED).integers(len(games),size=(DRAWS,len(games)))
    bins = list(frame.groupby('band',observed=False))
    for band, rows in bins:
        means[band] = {'pa':len(rows),'games':int(rows.game.nunique())}
        for metric in ('RE24','WPA'):
            group = rows.groupby('game')[metric].agg(['sum','count']).reindex(games,fill_value=0)
            n = group['count'].to_numpy()[positions].sum(axis=1)
            totals = group['sum'].to_numpy()[positions].sum(axis=1)
            ok = n>0
            means[band][metric] = {'mean':float(rows[metric].mean()) if rows[metric].notna().any() else None,
                'game_cluster_ci':np.quantile(totals[ok]/n[ok],[.025,.975]).tolist() if ok.any() else None}
    return means


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timing',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args()
    raw=args.timing.read_bytes()
    timing=json.loads(raw)
    pa=load()[0]
    day=decorate(pa[pa.season==timing['season']]).set_index('pa_id')
    records=[]
    for game, rows in timing['games'].items():
        for pid, marker in rows.items():
            row=day.loc[pid]
            if row.game!=game:
                raise ValueError(f'Timing and observed game differ: {pid}')
            if row.start_batter!=row.batter or row.start_pitcher!=row.pitcher:
                continue
            for role,gain,stayed in (('pitching',marker[0],row.start_pitcher==marker[2]),
                                     ('batting',marker[3],not row.is_ph)):
                if stayed and gain is not None:
                    records.append((game,role,gain,row.RE24,row.WPA))
    frame=pd.DataFrame(records,columns=['game','role','gain','RE24','WPA'])
    frame['band']=pd.cut(frame.gain,[-np.inf,.5,1,2,np.inf],labels=BANDS,right=False)
    from hashlib import sha256
    result={'season':timing['season'],'timing_sha256':sha256(raw).hexdigest(),
            'bootstrap_seed':SEED,'bootstrap_draws':DRAWS,
            'cohorts':{role:summarize(rows) for role,rows in frame.groupby('role')},
            'scope':'Observational incumbent outcomes conditional on not changing. Higher bands do not imply a counterfactual benefit.'}
    with args.out.open('x',encoding='utf8') as stream:
        json.dump(result,stream,indent=2,allow_nan=False)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
