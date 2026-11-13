"""Fit and test a plate-appearance outcome distribution and win-state prototype."""
import argparse
import json
from pathlib import Path
import pickle
import warnings

from sklearn.compose import ColumnTransformer
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder

from evaluate_rolling_recency import fit, load, np, pd
from evaluate_half_inning_2026 import paired_interval
from historical_actors import decorate
from runtime_config import settings

CONTEXT = ['inning_group','half','score_diff','outs','bases','bhand','phand']
NAMED = {'SO':'strikeout','BB':'walk_or_hbp','uBB':'walk_or_hbp','iBB':'walk_or_hbp',
         'IBB':'walk_or_hbp','HBP':'walk_or_hbp','1B':'single','2B':'double','3B':'triple','HR':'home_run'}


def estimator(individual):
    fields = CONTEXT + (['batter','pitcher'] if individual else [])
    data = ColumnTransformer([('category',OneHotEncoder(handle_unknown='ignore'),fields)])
    return make_pipeline(data,LogisticRegression(C=.2, max_iter=1200, tol=.001))


def fit_outcomes(train, individual):
    with warnings.catch_warnings():
        warnings.simplefilter('error', ConvergenceWarning)
        return estimator(individual).fit(train,train.outcome)


def game_result(record):
    scores = []
    for side in ('homeScores','awayScores'):
        innings = record[side]
        if not innings or any(type(value) not in (int,str) or not str(value).isdigit() for value in innings):
            raise ValueError(f'Invalid official inning scores: {side}')
        scores.append(sum(map(int,innings)))
    return 1.0 if scores[0]>scores[1] else 0.0 if scores[0]<scores[1] else .5


def dataset(pa):
    frame = decorate(pa).sort_values(['game','inning','half','seq'])
    frame['inning_group'] = frame.inning.clip(upper=10)
    frame['home_margin'] = np.where(frame.half=='home',frame.bat_score-frame.fld_score,frame.fld_score-frame.bat_score)
    frame['score_diff'] = (frame.bat_score-frame.fld_score).clip(-6,6)
    frame['bhand'] = frame.start_bhand.fillna('U')
    frame['phand'] = frame.start_phand.fillna('U')
    final = {}
    for game,file in frame[['game','source_file']].drop_duplicates().itertuples(index=False,name=None):
        final[game] = game_result(json.loads(Path(file).read_bytes()))
    if not {0.0,1.0} <= set(final.values()):
        raise ValueError('Historical winner labels are degenerate')
    frame['home_result'] = frame.game.map(final)
    frame['terminal'] = ~frame.game.duplicated(keep='last')
    frame['next_bases'] = frame.groupby('game').bases.shift(-1)
    frame['outcome'] = frame.result.map(NAMED).fillna(pd.Series(
        np.where(frame.end_outs-frame.outs>=2,'multi_out','other'),index=frame.index))
    clean = frame.batter.eq(frame.start_batter) & frame.pitcher.eq(frame.start_pitcher)
    return frame, frame[clean & frame.result.notna()].dropna(subset=['batter','pitcher']).copy()


def win_tables(rows):
    keys = ['inning_group','half','margin','outs','bases']
    data = rows.assign(margin=rows.home_margin.clip(-6,6))
    prior = float(data.home_result.mean())
    coarse = data.groupby(keys[:3]).home_result.agg(['sum','count'])
    smooth = ((coarse['sum']+30*prior)/(coarse['count']+30)).to_dict()
    detail = data.groupby(keys).home_result.agg(['sum','count'])
    fine = {key:(row['sum']+20*smooth[key[:3]])/(row['count']+20) for key,row in detail.iterrows()}
    return fine,smooth,prior


def gain_values(rows, tables):
    fine,smooth,prior = tables

    def probability(inning,half,margin,outs,bases):
        key = (min(inning,10),half,int(np.clip(margin,-6,6)),outs,bases)
        return fine.get(key,smooth.get(key[:3],prior))

    values = []
    for r in rows.itertuples():
        before = probability(r.inning,r.half,r.home_margin,r.outs,r.bases)
        margin = r.home_margin+(r.runs if r.half=='home' else -r.runs)
        if r.terminal:
            after = r.home_result
        elif r.end_outs>=3:
            after = (probability(r.inning,'home',margin,0,int(r.next_bases)) if r.half=='away'
                     else probability(r.inning+1,'away',margin,0,int(r.next_bases)))
        else:
            after = probability(r.inning,r.half,margin,r.end_outs,r.end_bases)
        values.append((after-before)*(1 if r.half=='home' else -1))
    return np.asarray(values)


def event_values(rows):
    states = ['inning_group','half','score_diff','outs','bases','outcome']
    prior = rows.groupby('outcome').gain.mean().to_dict()
    coarse = rows.groupby(states[:2]+['outcome']).gain.agg(['sum','count'])
    smooth = {k:(r['sum']+20*prior[k[-1]])/(r['count']+20) for k,r in coarse.iterrows()}
    fine = rows.groupby(states).gain.agg(['sum','count'])
    return ({k:(r['sum']+12*smooth[k[:2]+(k[-1],)])/(r['count']+12) for k,r in fine.iterrows()},smooth,prior)


def values_for(target, classes, tables):
    fine,coarse,prior = tables
    fields = ['inning_group','half','score_diff','outs','bases']
    return np.asarray([[fine.get(key+(c,),coarse.get(key[:2]+(c,),prior[c])) for c in classes]
                       for key in target[fields].itertuples(index=False,name=None)])


def assess(rows):
    delta=rows.matchup_loss-rows.context_loss
    change=rows.matchup_gain-rows.context_gain
    result = {'pa':len(rows),'games':int(rows.game.nunique()),
            'log_loss_context':float(rows.context_loss.mean()),'log_loss_matchup':float(rows.matchup_loss.mean()),
            'log_loss_difference':float(delta.mean()),'paired_game_ci':paired_interval(rows,delta),
            'win_change_context_mse':float(((rows.context_gain-rows.observed_gain)**2).mean()),
            'win_change_matchup_mse':float(((rows.matchup_gain-rows.observed_gain)**2).mean()),
            'mean_absolute_shift_pp':float(change.abs().mean()*100)}
    for name in ('context','matchup'):
        result['multiclass_brier_'+name] = float(rows[name+'_brier'].mean())
        bins = rows.groupby(np.minimum((rows[name+'_confidence']*10).astype(int),9))
        result['top_class_calibration_'+name] = [
            {'bin':int(index),'pa':len(group),'confidence':float(group[name+'_confidence'].mean()),
             'accuracy':float(group[name+'_hit'].mean())} for index,group in bins]
    if 'legacy_gain' in rows:
        comparison = {}
        for target in ('observed_gain','source_wpa'):
            valid = rows.dropna(subset=[target,'legacy_gain','matchup_gain'])
            legacy = (valid.legacy_gain-valid[target])**2
            alternative = (valid.matchup_gain-valid[target])**2
            comparison[target] = {'pa':len(valid),'games':int(valid.game.nunique()),
                                  'legacy_mse':float(legacy.mean()),'outcome_mse':float(alternative.mean()),
                                  'paired_game_ci':paired_interval(valid,alternative-legacy)}
        result['same_target_win_comparison'] = comparison
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--predictions',type=Path,help='Directory containing frozen monthly RE24 predictions')
    args=parser.parse_args()
    if args.out.exists():
        parser.error('Choose a new report')
    runtime=settings()
    if runtime.data_seasons!=(2024,2025,2026):
        parser.error('Use the explicit three-season runtime')
    games, frame=dataset(load()[0])
    frames=[]
    for cutoff in runtime.replay_cutoffs:
        stop=pd.Timestamp(cutoff)+pd.offsets.MonthBegin()
        train=frame[frame.date<cutoff]
        target=frame[(frame.date>=cutoff)&(frame.date<stop)]
        win=win_tables(games[games.date<cutoff])
        events=event_values(train.assign(gain=gain_values(train,win)))
        out=target[['game','inning','outs','score_diff']].copy()
        out['observed_gain']=gain_values(target,win)
        if args.predictions:
            forecast = pd.read_csv(args.predictions/cutoff/'predictions.csv').set_index('pa_id',verify_integrity=True)
            expected = target.pa_id.map(forecast.reference_ensemble)
            if expected.notna().sum()!=len(forecast) or not np.allclose(
                    target.loc[expected.notna(),'RE24'],target.loc[expected.notna(),'pa_id'].map(forecast.RE24)):
                raise ValueError(f'Monthly predictions are not aligned at {cutoff}')
            hierarchy = fit(cutoff)
            out['legacy_gain'] = expected * np.asarray([
                hierarchy.run_to_win(r.inning,r.half,r.bat_score,r.fld_score,r.bases,r.outs)
                for r in target.itertuples()])
            out['source_wpa'] = target.WPA
        for name,individual in [('context',False),('matchup',True)]:
            model=fit_outcomes(train,individual)
            probabilities=model.predict_proba(target)
            code={c:i for i,c in enumerate(model.classes_)}
            observed=np.asarray([code[c] for c in target.outcome])
            observed_probability=probabilities[np.arange(len(target)),observed]
            out[name+'_loss']=-np.log(np.clip(observed_probability,1e-15,1))
            out[name+'_brier']=(probabilities**2).sum(axis=1)-2*observed_probability+1
            out[name+'_confidence']=probabilities.max(axis=1)
            out[name+'_hit']=probabilities.argmax(axis=1)==observed
            out[name+'_gain']=(probabilities*values_for(target,model.classes_,events)).sum(axis=1)
        frames.append(out.assign(month=cutoff))
        print(cutoff,len(target),'PA',flush=True)
    whole=pd.concat(frames)
    high=whole[(whole.inning>=8)&(whole.score_diff.abs()<=1)]
    train=frame[frame.date<runtime.cutoff]
    win=win_tables(games[games.date<runtime.cutoff])
    events=event_values(train.assign(gain=gain_values(train,win)))
    final_model = fit_outcomes(train,True)
    with args.out.with_name('pa-outcomes-model.pkl').open('xb') as stream:
        pickle.dump({'cutoff':runtime.cutoff,'model':final_model,
                     'win_table':win,'event_values':events},stream,pickle.HIGHEST_PROTOCOL)
    report={'all':assess(whole),'late_close':assess(high),
            'training_games_by_home_result':games.drop_duplicates('game').home_result.value_counts().to_dict(),
            'monthly':{month:assess(rows) for month,rows in whole.groupby('month')},
            'scope':'Temporal forecasts of observed PA outcomes. The optional RE24 comparator uses a frozen monthly slope and common targets; it does not identify counterfactual gains.'}
    with args.out.open('x',encoding='utf8') as stream:
        json.dump(report,stream,indent=2,allow_nan=False)
    print(json.dumps({'all':report['all'],'late_close':report['late_close']},indent=2))


if __name__=='__main__':
    main()
