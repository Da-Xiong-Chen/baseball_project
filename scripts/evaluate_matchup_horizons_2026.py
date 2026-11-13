"""Train and compare CPBL plate-appearance and three-batter run forecasts."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import pickle

from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder

from evaluate_half_inning_2026 import paired_interval
from evaluate_pa_outcomes_2026 import CONTEXT, dataset
from evaluate_rolling_recency import load, np, pd
from simulate_bullpen_two_halves import transition

STATES = 25
RUN_LEVELS = 13
NAMES = ('league', 'pitcher', 'matchup', 'direct')
CLASSES = ('context', 'players', 'platoon')


def pa_model(train, name):
    fields = CONTEXT.copy()
    if name != 'context':
        fields += ['batter', 'pitcher']
    if name == 'platoon':
        fields += ['batter_side', 'pitcher_side']
    encoder = ColumnTransformer([('cats', OneHotEncoder(handle_unknown='ignore'), fields)])
    return make_pipeline(encoder, LogisticRegression(C=.1, max_iter=1000, tol=.001)).fit(train, train.outcome)


def sides(frame):
    return frame.assign(batter_side=frame.batter+':'+frame.phand, pitcher_side=frame.pitcher+':'+frame.bhand)


def prepare(pa, boxes):
    full, clean = dataset(pa)
    clean = sides(clean.dropna(subset=['RE24'])).set_index('pa_id', drop=False, verify_integrity=True)
    ends = []
    windows, skip = [], Counter()
    starters = {(g, t): group.drop_duplicates('order').set_index('order').name.to_dict()
                for (g,t),group in boxes[boxes.role=='B'].groupby(['game','team'],sort=False)}
    for (game, half), side in full.groupby(['game','half'],sort=False):
        lineup = starters.get((game,side.bat_team.iat[0]),{}).copy()
        for _, group in side.groupby('inning',sort=False):
            entries = list(group.sort_values('seq').itertuples())
            transitions = {}
            for row in entries:
                try:
                    if row.pa_id not in clean.index or row.outs not in range(3) or row.bases not in range(8):
                        continue
                    outs,bases,runs = transition(row)
                    if runs > 4:
                        continue
                    transitions[row.pa_id] = (24 if outs==3 else outs*8+bases,runs)
                    ends.append((row.pa_id,row.outs*8+row.bases,*transitions[row.pa_id]))
                except (ValueError, TypeError, OverflowError):
                    continue
            for i,row in enumerate(entries):
                if row.inning >= 6 and row.pa_id in transitions:
                    order = row.pa_order
                    batters = [row.start_batter] + [lineup.get((order+k-1)%9+1) for k in (1,2)] if order in range(1,10) else []
                    seen = []
                    runs = 0
                    stop = 'incomplete'
                    for following in entries[i:i+3]:
                        if following.pa_id not in transitions or following.start_pitcher!=row.start_pitcher:
                            break
                        if seen:
                            previous, end = seen[-1]
                            if (following.outs*8+following.bases,following.bat_score)!=(end,previous.bat_score+int(previous.runs)):
                                break
                        end, value = transitions[following.pa_id]
                        runs += value
                        seen.append((following,end))
                        if end==24 or len(seen)==3:
                            stop = 'complete'
                            break
                    if stop!='complete':
                        skip[stop]+=1
                    elif len(batters)!=3 or any(not isinstance(b,str) for b in batters):
                        skip['unknown_lineup']+=1
                    elif any(batters[k]!=actual.start_batter for k,(actual,_) in enumerate(seen)):
                        skip['lineup_mismatch']+=1
                    else:
                        windows.append((row.pa_id,game,row.date,row.inning,row.score_diff,row.outs*8+row.bases,row.start_pitcher,
                                        row.phand,row.half,*batters,runs))
                if row.pa_order in range(1,10) and isinstance(row.batter,str):
                    lineup[row.pa_order]=row.batter
    edges = pd.DataFrame(ends,columns=['pa_id','state','end','runs']).set_index('pa_id')
    edges = edges.join(clean[['date','pitcher','outcome']])
    short = pd.DataFrame(windows,columns=['pa_id','game','date','inning','score_diff','state','pitcher','phand','half','b1','b2','b3','runs'])
    prior = full.groupby(['game','half'],sort=False).pitcher.shift()
    replacements = full.loc[prior.notna() & prior.ne(full.start_pitcher),'pa_id']
    short['replacement'] = short.pa_id.isin(replacements)
    return clean,edges,short,dict(skip)


def kernels(edges, classes):
    counts = np.zeros((len(classes),STATES,STATES,5))
    totals = np.zeros((STATES,STATES,5))
    personal = {}
    mapping = {name:i for i,name in enumerate(classes)}
    for state,end,runs,outcome,pitcher in edges[['state','end','runs','outcome','pitcher']].itertuples(index=False,name=None):
        totals[state,end,runs] += 1
        counts[mapping[outcome],state,end,runs] += 1
        personal.setdefault((pitcher,state),Counter())[end,runs] += 1
    if np.any(totals[:24].sum(axis=(1,2))==0):
        raise ValueError('Missing league state')
    totals[24,24,0] = 1
    league = totals/totals.sum(axis=(1,2),keepdims=True)
    # A weak same-state prior backs off when an outcome is rare in a base/out state.
    counts += 2*league[None]
    counts[:,24,24,0] = 1
    by_class = counts/counts.sum(axis=(2,3),keepdims=True)
    pitchers = {}
    for (pitcher,state), observations in personal.items():
        matrix = pitchers.setdefault(pitcher,league.copy())
        row = 60*league[state]
        for (end,runs), n in observations.items():
            row[end,runs] += n
        matrix[state] = row/row.sum()
    return league, by_class, pitchers


def propagate(states, step_matrices):
    dist = np.zeros((len(states),STATES,RUN_LEVELS))
    dist[np.arange(len(states)),states,0] = 1
    for matrix in step_matrices:
        next_dist = np.zeros_like(dist)
        for runs in range(5):
            next_dist[:,:,runs:] += np.einsum('nij,nik->njk',matrix[:,:,:,runs],dist[:,:,:RUN_LEVELS-runs])
        dist = next_dist
    values = dist.sum(axis=1)
    np.testing.assert_allclose(values.sum(axis=1),1,atol=1e-10)
    if (values < -1e-12).any():
        raise ValueError('Negative mass')
    return values


def dated_hands(train):
    return train[train.bhand.isin(['L','R','S'])].groupby('batter').bhand.agg(lambda s:s.value_counts().index[0])


def predict_short(target, model, league, by_class, pitchers, hands):
    pieces = []
    for start in range(0,len(target),96):
        t = target.iloc[start:start+96]
        n = len(t)
        states = t.state.to_numpy()
        state_index = np.tile(np.arange(24),n)
        repeated = t.loc[t.index.repeat(24)].reset_index(drop=True)
        repeated['outs'] = state_index//8
        repeated['bases'] = state_index%8
        repeated['inning_group'] = repeated.inning.clip(upper=10)
        matrices = []
        for k in ('b1','b2','b3'):
            repeated['batter'] = repeated[k]
            hand = repeated.batter.map(hands).fillna('U')
            repeated['bhand'] = hand.where(hand.ne('S'),repeated.phand.map({'R':'L','L':'R'}).fillna('U'))
            probabilities = model.predict_proba(sides(repeated)).reshape(n,24,-1)
            matrix = np.empty((n,25,25,5))
            matrix[:,:24] = np.einsum('nsc,cser->nser',probabilities,by_class[:,:24])
            matrix[:,24] = league[24]
            matrices.append(matrix)
        neutral = np.broadcast_to(league,(n,*league.shape))
        personal = np.stack([pitchers.get(p,league) for p in t.pitcher])
        pieces.append(np.stack([propagate(states,[neutral]*3),propagate(states,[personal]*3),
                                propagate(states,matrices)],axis=1))
    return np.concatenate(pieces,axis=0)


def interval(rows,delta):
    return paired_interval(rows,delta) if rows.game.nunique()>1 else None


def pa_report(rows):
    out={'pa':len(rows),'games':int(rows.game.nunique())}
    for c in CLASSES:
        out[c]={'log_loss':float(rows[c+'_loss'].mean()),'mse':float(rows[c+'_mse'].mean())}
        out[c]['log_loss_delta_ci']=interval(rows,rows[c+'_loss']-rows.context_loss)
    aligned = rows.dropna(subset=['reference_mse','chronological_mse','blend_mse'])
    out['same_pa_re24']={'pa':len(aligned)}
    for c in ('reference','chronological','blend'):
        out['same_pa_re24'][c]={'mse':float(aligned[c+'_mse'].mean()),
                              'delta_vs_chronological_ci':interval(aligned,aligned[c+'_mse']-aligned.chronological_mse)}
    return out


def short_report(rows):
    out={'pa':len(rows),'games':int(rows.game.nunique()),'observed_zero':float(rows.runs.eq(0).mean())}
    for name in NAMES:
        out[name]={'mse':float(rows[name+'_mse'].mean()),'bias':float(rows[name+'_error'].mean()),
                   'mse_delta_ci':interval(rows,rows[name+'_mse']-rows.league_mse)}
        if name!='direct':
            out[name].update(zero_brier=float(rows[name+'_brier'].mean()),rps=float(rows[name+'_rps'].mean()),
                             rps_delta_ci=interval(rows,rows[name+'_rps']-rows.league_rps))
    return out


def direct_model(train):
    fields = ['state','pitcher','phand','half','b1','b2','b3','inning','score_diff']
    encoder=ColumnTransformer([('cats',OneHotEncoder(handle_unknown='ignore'),fields)])
    return make_pipeline(encoder,Ridge(alpha=60,solver='lsqr')).fit(train,train.runs)


def pa_forecasts(train,target,models,benchmark):
    rows = target[['game','date','inning','score_diff','is_ph','replacement']].copy()
    y=target.RE24.to_numpy()
    tables=train.groupby(['outs','bases','outcome']).RE24.agg(['sum','count'])
    avg=train.groupby('outcome').RE24.mean()
    for name,m in models.items():
        p=m.predict_proba(target)
        code={c:k for k,c in enumerate(m.classes_)}
        y_index=np.array([code[c] for c in target.outcome])
        rows[name+'_loss']=-np.log(np.clip(p[np.arange(len(target)),y_index],1e-15,1))
        values=np.empty((24,len(code)))
        for state in range(24):
            for c,j in code.items():
                key=(state//8,state%8,c)
                count=tables.loc[key] if key in tables.index else {'sum':0,'count':0}
                values[state,j]=(count['sum']+12*avg[c])/(count['count']+12)
        pred=(p*values[target.outs.astype(int)*8+target.bases.astype(int)]).sum(axis=1)
        rows[name+'_prediction']=pred
        rows[name+'_mse']=(pred-y)**2
        if name=='players':
            rows['blend_mse']=((pred+benchmark.chronological.reindex(rows.index).to_numpy())/2-y)**2
    for ref in ('reference','chronological'):
        rows[ref+'_prediction']=benchmark[ref].reindex(rows.index)
        rows[ref+'_mse']=(rows[ref+'_prediction']-y)**2
    rows['RE24']=y
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    args.out.mkdir(exist_ok=False,parents=True)
    pa,_,boxes=load()
    if set(pa.season)!={2024,2025,2026}:
        raise ValueError('Three regular seasons required')
    frame,edges,short,excluded=prepare(pa,boxes)
    benchmark=pd.read_csv(args.reference).set_index('pa_id',verify_integrity=True)
    match=frame.index.intersection(benchmark.index)
    if len(match) != len(benchmark) or not frame.loc[match,'game'].equals(benchmark.loc[match,'game']):
        raise ValueError('Benchmark must match every PA identifier and game')
    np.testing.assert_allclose(frame.loc[match,'RE24'],benchmark.loc[match,'RE24'])
    prior = pa.sort_values(['game','half','seq']).groupby(['game','half']).pitcher.shift()
    previous = pa.assign(previous=prior).set_index('pa_id').previous
    frame['replacement'] = frame.pa_id.map(previous).notna() & frame.pa_id.map(previous).ne(frame.start_pitcher)
    pa_parts,short_parts=[],[]
    for start in pd.date_range('2026-03-01','2026-10-01',freq='MS'):
        end=start+pd.offsets.MonthBegin()
        train=frame[frame.date<start]
        test=frame[(frame.date>=start)&(frame.date<end)]
        train_short=short[short.date<start]
        target=short[(short.date>=start)&(short.date<end)].copy()
        models={c:pa_model(train,c) for c in CLASSES}
        pa_parts.append(pa_forecasts(train,test,models,benchmark))
        league,classes,pitchers=kernels(edges[edges.date<start],models['players'].classes_)
        pmf=predict_short(target,models['players'],league,classes,pitchers,dated_hands(train))
        runs=target.runs.to_numpy()
        thresholds=np.arange(RUN_LEVELS)
        for i,n in enumerate(NAMES[:3]):
            dist=pmf[:,i]
            mean=dist@thresholds
            target[n+'_error']=mean-runs
            target[n+'_brier']=(dist[:,0]-(runs==0))**2
            target[n+'_rps']=((dist.cumsum(axis=1)-(runs[:,None]<=thresholds))**2).sum(axis=1)
        target['direct_error']=np.clip(direct_model(train_short).predict(target),0,12)-runs
        for name in NAMES:
            target[name+'_mse']=target[name+'_error']**2
        short_parts.append(target)
        print(str(start.date()),len(train),len(test),len(train_short),len(target),flush=True)
    p=pd.concat(pa_parts,verify_integrity=True)
    s=pd.concat(short_parts,ignore_index=True)
    report={'pa':{'all':pa_report(p),'pinch_hit':pa_report(p[p.is_ph.eq(True)]),
                  'actual_replacement':pa_report(p[p.replacement]),
                  'late_close':pa_report(p[p.inning.ge(8)&p.score_diff.abs().le(1)])},
            'short':{'all':short_report(s),'actual_replacement':short_report(s[s.replacement]),
                     'two_out':short_report(s[s.state.ge(16)]),
                     'late_close':short_report(s[s.inning.ge(8)&s.score_diff.abs().le(1)]),
                     'by_month':{str(month):short_report(group) for month,group in s.groupby(s.date.dt.to_period('M'))}},
            'excluded_three_seasons':excluded,
            'reference_sha256':sha256(args.reference.read_bytes()).hexdigest(),
            'training_by_season':frame.season.value_counts().sort_index().to_dict(),
            'scope':'Observed actors and observed runs. Short windows require one pitcher, known lineup and three batters or third out. Does not infer the effect of a substitution.'}
    final={c:pa_model(frame,c) for c in CLASSES}
    league,classes,pitchers=kernels(edges,final['players'].classes_)
    artifact=args.out/'offline-models.pkl'
    payload={'cutoff':'2027-01-01','models':final,'direct':direct_model(short),'league':league,
             'by_class':classes,'by_pitcher':pitchers,'hands':dated_hands(frame)}
    artifact.write_bytes(pickle.dumps(payload,pickle.HIGHEST_PROTOCOL))
    restored=pickle.loads(artifact.read_bytes())
    np.testing.assert_array_equal(final['players'].predict_proba(frame.tail(6)),restored['models']['players'].predict_proba(frame.tail(6)))
    report['final']={'training_pa':len(frame),'games':int(frame.game.nunique()),'short_windows':len(short),
                     'sha256':sha256(artifact.read_bytes()).hexdigest()}
    (args.out/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    p.to_csv(args.out/'pa-scores.csv')
    s.to_csv(args.out/'three-batter-scores.csv',index=False)


if __name__=='__main__':
    main()
