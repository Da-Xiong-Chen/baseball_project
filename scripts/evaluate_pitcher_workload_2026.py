"""Test workload features on future games, separately for starters and relievers."""
import argparse
import json
from pathlib import Path
import pickle

from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from evaluate_half_inning_2026 import paired_interval
from evaluate_rolling_recency import load, np, pd
from historical_actors import decorate
from runtime_config import settings

CONTEXT = ['inning','outs','bases','score_difference']
ACTORS = ['pitcher','batter','bhand','phand','fld_team','bat_team']
LOAD = ['today_pitches','today_high','repeat_batter','previous_day','last_three_days','rest_days']


def prior_load(frame, boxes):
    history = boxes[boxes.role=='P'].groupby(['name','date']).NP.sum()
    out = []
    for pitcher, rows in frame.groupby('pitcher'):
        dated = history.get(pitcher, pd.Series(dtype=float)).sort_index()
        played = np.asarray(dated.index, dtype='datetime64[D]').astype('int64')
        days = rows.date.to_numpy().astype('datetime64[D]').astype('int64')
        sums = np.r_[0,dated.to_numpy().cumsum()]
        stop = np.searchsorted(played,days,side='left')
        start1 = np.searchsorted(played,days-1,side='left')
        start3 = np.searchsorted(played,days-3,side='left')
        rest = np.full(len(days),14)
        has_history = stop>0
        rest[has_history] = np.minimum(14,days[has_history]-played[stop[has_history]-1]-1)
        out.append(pd.DataFrame({'previous_day':sums[stop]-sums[start1],
                                 'last_three_days':sums[stop]-sums[start3],'rest_days':rest},index=rows.index))
    return pd.concat(out).reindex(frame.index)


def dataset(pa, pitches, boxes):
    ordered = pitches.sort_values(['game','half','seq','j']).copy()
    ordered['today_pitches'] = ordered.groupby(['game','pitcher']).cumcount()
    first = ordered.drop_duplicates('pa_id').set_index('pa_id')
    fast = ordered[(ordered.group=='速球')&ordered.velo.notna()].drop_duplicates('pa_id').set_index('pa_id')
    frame = decorate(pa).sort_values(['game','half','seq']).copy()
    frame['bhand'] = frame.start_bhand.fillna('U')
    frame['phand'] = frame.start_phand.fillna('U')
    clean = frame.pitcher.eq(frame.start_pitcher) & frame.batter.eq(frame.start_batter)
    frame = frame[clean].dropna(subset=['pitcher','batter']).copy()
    frame['today_pitches'] = frame.pa_id.map(first.today_pitches)
    frame['repeat_batter'] = frame.groupby(['game','pitcher','batter']).cumcount()
    frame['score_difference'] = (frame.bat_score-frame.fld_score).clip(-6,6)
    frame['velo'] = frame.pa_id.map(fast.velo)
    starters = set(boxes[(boxes.role=='P')&(boxes.order==1)][['game','name']].itertuples(index=False,name=None))
    frame['role'] = ['starter' if key in starters else 'reliever' for key in frame[['game','pitcher']].itertuples(index=False,name=None)]
    frame = frame.dropna(subset=['today_pitches'])
    frame['today_high'] = (frame.today_pitches-np.where(frame.role=='starter',80,20)).clip(lower=0)
    return frame.join(prior_load(frame,boxes))


def estimator(extra=False, additional=()):
    numeric = CONTEXT + (LOAD if extra else []) + list(additional)
    prep = ColumnTransformer([('actors',OneHotEncoder(handle_unknown='ignore'),ACTORS),
                              ('context',StandardScaler(),numeric)])
    return make_pipeline(prep,Ridge(alpha=20,solver='lsqr'))


def summarize(rows):
    delta = rows.workload_error**2-rows.baseline_error**2
    return {'n':len(rows),'games':int(rows.game.nunique()),
            'baseline_mse':float((rows.baseline_error**2).mean()),
            'workload_mse':float((rows.workload_error**2).mean()),
            'mse_delta':float(delta.mean()),'paired_game_ci':paired_interval(rows,delta),
            'workload_bias':float(rows.workload_error.mean())}


def third_turn(frame, cutoffs):
    rows = frame[(frame.role=='starter')&frame.RE24.notna()].copy()
    rows['slot_exposures'] = rows.groupby(['game','pitcher','pa_order']).cumcount()
    rows['third_turn'] = rows.slot_exposures.ge(2).astype(int)
    predictions = []
    for cutoff in cutoffs:
        end = pd.Timestamp(cutoff)+pd.offsets.MonthBegin()
        train = rows[rows.date<cutoff]
        test = rows[(rows.date>=cutoff)&(rows.date<end)]
        errors = test[['game','third_turn']].copy()
        for name, added in [('baseline',('slot_exposures',)),('workload',('slot_exposures','third_turn'))]:
            model = estimator(True,added).fit(train,train.RE24)
            errors[name+'_error'] = model.predict(test)-test.RE24
        predictions.append(errors)
    joined = pd.concat(predictions)
    return {'all':summarize(joined),'third_turn_cases':summarize(joined[joined.third_turn==1]),
            'scope':'Starters only; a step at the third appearance of a lineup slot is tested over continuous workload and exposure. Not a causal estimate.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--third-turn-only', action='store_true')
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Choose a new report')
    runtime = settings()
    if runtime.data_seasons != (2024,2025,2026):
        parser.error('Use the explicit three-season runtime')
    frame = dataset(*load())
    if args.third_turn_only:
        report = third_turn(frame,runtime.replay_cutoffs)
        with args.out.open('x',encoding='utf8') as stream:
            json.dump(report,stream,indent=2,allow_nan=False)
        print(json.dumps(report,indent=2))
        return
    report, models = {}, {}
    for outcome in ('RE24','velo'):
        report[outcome] = {}
        for role in ('starter','reliever'):
            predictions = []
            sample = frame[frame.role==role].dropna(subset=[outcome])
            for cutoff in runtime.replay_cutoffs:
                end = pd.Timestamp(cutoff)+pd.offsets.MonthBegin()
                train = sample[sample.date < cutoff]
                test = sample[(sample.date >= cutoff)&(sample.date < end)]
                errors = test[['game','today_pitches','last_three_days']].copy()
                for name, extra in [('baseline',False),('workload',True)]:
                    predictor = estimator(extra).fit(train,train[outcome])
                    errors[name+'_error'] = predictor.predict(test)-test[outcome]
                predictions.append(errors.assign(month=cutoff))
            all_rows = pd.concat(predictions)
            fit_rows = sample[sample.date<runtime.cutoff]
            models[f'{outcome}_{role}'] = estimator(True).fit(fit_rows,fit_rows[outcome])
            report[outcome][role] = {'all':summarize(all_rows),
                'monthly':{month:summarize(rows) for month, rows in all_rows.groupby('month')},
                'training_rows':len(fit_rows)}
    with args.out.with_name('pitcher-workload-model.pkl').open('xb') as stream:
        pickle.dump(dict(cutoff=runtime.cutoff,models=models),stream,pickle.HIGHEST_PROTOCOL)
    with args.out.open('x',encoding='utf8') as stream:
        json.dump({'metrics':report,'scope':'Prediction on observed pitchers only. Velocity is the first valid fastball of a PA. No causal penalty.'},
                  stream,indent=2,allow_nan=False)
    print(json.dumps({o:{r:m['all'] for r,m in roles.items()} for o,roles in report.items()},indent=2))


if __name__ == '__main__':
    main()
