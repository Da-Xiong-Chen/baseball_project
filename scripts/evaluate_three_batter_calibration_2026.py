"""Matched-sample baselines and direct ordinal run-distribution forecasts."""
import argparse
import json
from pathlib import Path
import pickle

from evaluate_matchup_horizons_2026 import (ColumnTransformer, LogisticRegression, OneHotEncoder, Ridge,
                        load, make_pipeline, np, paired_interval, pd, prepare)
from sklearn.isotonic import isotonic_regression

FIELD_CONTEXT = ['state','inning','half','score_diff']
ACTORS = ['pitcher','phand','b1','b2','b3']
thresholds=np.arange(7)


def predictor(fields, estimator):
    encoder=ColumnTransformer([('cats',OneHotEncoder(handle_unknown='ignore'),fields)])
    return make_pipeline(encoder,estimator)


def probability_models(train, fields):
    # Model P(runs > k), with 7+ pooled only for distribution scoring.
    fitted=[]
    for k in thresholds:
        label=train.runs.gt(k)
        fitted.append(predictor(fields,LogisticRegression(C=.1,max_iter=500)).fit(train,label) if label.nunique()==2 else float(label.mean()))
    return fitted


def survival(fitted,target):
    raw=np.column_stack([np.full(len(target),model) if isinstance(model,float) else model.predict_proba(target)[:,1]
                         for model in fitted])
    return np.stack([isotonic_regression(row,increasing=False) for row in raw])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scores', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    pa,_,boxes=load()
    _,_,short,_=prepare(pa,boxes)
    scores=pd.read_csv(args.scores).set_index('pa_id',verify_integrity=True)
    expected=short.set_index('pa_id',verify_integrity=True).loc[scores.index]
    if not np.array_equal(scores.runs,expected.runs) or not np.array_equal(scores.game,expected.game):
        raise ValueError('Scores do not match the reconstructed three-batter windows')
    if not pd.to_datetime(scores.date).equals(expected.date):
        raise ValueError('Score dates do not match source dates')
    for period,group in scores.groupby(pd.to_datetime(scores.date).dt.to_period('M')):
        cutoff=period.start_time
        train=short[short.date<cutoff]
        observed=group.runs.to_numpy()
        out=group.index
        means=train.groupby('state').runs.mean()
        for name,cols in [('context',FIELD_CONTEXT),('actors',FIELD_CONTEXT+ACTORS)]:
            if name=='context':
                mean=predictor(cols,Ridge(alpha=60,solver='lsqr')).fit(train,train.runs).predict(group)
                scores.loc[out,'context_mse']=(np.clip(mean,0,12)-observed)**2
            predicted=survival(probability_models(train,cols),group)
            scores.loc[out,name+'_ord_rps']=((predicted-(observed[:,None]>thresholds))**2).sum(axis=1)
            scores.loc[out,name+'_ord_brier']=(predicted[:,0]-(observed>0))**2
        scores.loc[out,'state_mean_mse']=(group.state.map(means)-observed)**2
        print(str(period),len(group),flush=True)
    # The original Markov RPS includes thresholds >=7, which are negligible but
    # not identical. Recompute comparisons only between direct distributions.
    summary={}
    for name,group in {'all':scores,'actual_replacement':scores[scores.replacement],
                       'late_close':scores[scores.inning.ge(8)&scores.score_diff.abs().le(1)]}.items():
        summary[name]={'pa':len(group),'games':int(group.game.nunique()),
                       **{metric:float(group[metric].mean()) for metric in
                          ('state_mean_mse','context_mse','direct_mse','context_ord_rps','actors_ord_rps','context_ord_brier','actors_ord_brier')},
                       'direct_minus_context_ci':paired_interval(group,group.direct_mse-group.context_mse),
                       'actors_minus_context_rps_ci':paired_interval(group,group.actors_ord_rps-group.context_ord_rps)}
    with (args.out/'matched-calibration-models.pkl').open('xb') as f:
        pickle.dump({'cutoff':'2027-01-01','context':probability_models(short,FIELD_CONTEXT),
                     'actors':probability_models(short,FIELD_CONTEXT+ACTORS)},f,pickle.HIGHEST_PROTOCOL)
    (args.out/'matched-calibration.json').write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    main()
