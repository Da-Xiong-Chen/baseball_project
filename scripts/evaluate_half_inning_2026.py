"""Validate absorbing half-inning forecasts against recorded CPBL runs."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from simulate_bullpen_two_halves import PITCHER_PRIOR_PA, transition
from evaluate_rolling_recency import load, np, pd
from historical_actors import decorate
from runtime_config import settings


def clean_halves(pa):
    rows = decorate(pa).sort_values(['game', 'half', 'inning', 'seq'])
    records, excluded = [], Counter()
    for _, half in rows.groupby(['game', 'half', 'inning'], sort=False):
        events = list(half.itertuples())
        if events[-1].end_outs != 3:
            excluded['no_recorded_third_out'] += len(events)
            continue
        if any(r.start_pitcher != r.pitcher or r.start_batter != r.batter or
               not isinstance(r.pitcher, str) for r in events):
            excluded['actor_change_or_unknown'] += len(events)
            continue
        try:
            outcomes = [transition(r) for r in events]
        except (TypeError, ValueError, OverflowError):
            excluded['invalid_transition'] += len(events)
            continue
        if any((r.outs, r.bases, r.bat_score) != (outs, bases, previous.bat_score + runs)
               for previous, r, (outs, bases, runs) in zip(events, events[1:], outcomes)):
            excluded['between_pa_change'] += len(events)
            continue
        remaining = 0
        constant = True
        for r, (outs, bases, runs) in reversed(list(zip(events, outcomes))):
            remaining += runs
            constant = constant and r.pitcher == events[-1].pitcher
            records.append((r.date, r.game, r.inning, r.pitcher, r.outs*8+r.bases,
                            24 if outs==3 else outs*8+bases, runs, remaining, constant))
    frame = pd.DataFrame.from_records(records, columns=['date','game','inning','pitcher','state',
                                       'next_state','runs','remaining','same_pitcher'])
    return frame, dict(excluded)


def forecasts(counts):
    """Return expected runs, zero-run probability and a three-PA benchmark."""
    total = np.zeros((24,24))
    zeros = np.zeros_like(total)
    reward = np.zeros(24)
    finish_without_run = np.zeros(24)
    for state, outcomes in enumerate(counts):
        n = sum(outcomes.values())
        if not n:
            raise ValueError(f'No reference transitions for state {state}')
        for (end, runs), count in outcomes.items():
            prob = count / n
            reward[state] += prob * runs
            if end < 24:
                total[state,end] += prob
                if not runs:
                    zeros[state,end] += prob
            elif not runs:
                finish_without_run[state] += prob
    identity = np.eye(24)
    mean = np.linalg.solve(identity-total, reward)
    zero = np.linalg.solve(identity-zeros, finish_without_run)
    short = reward + total @ (reward + total @ reward)
    if not np.isfinite(mean).all() or np.any(mean < -1e-10) or np.any((zero < -1e-10)|(zero > 1+1e-10)):
        raise ValueError('Invalid absorbing distribution')
    return mean, np.clip(zero,0,1), short


def fit_prior(frame):
    league = [Counter() for _ in range(24)]
    personal = defaultdict(Counter)
    for row in frame.itertuples():
        key = (row.next_state,row.runs)
        league[row.state][key] += 1
        personal[row.pitcher,row.state][key] += 1
    return league, personal


def pooled_forecasts(league_prior, personal, pitcher):
    return forecasts([
        {key:prob+personal.get((pitcher,state), {}).get(key,0) for key,prob in outcomes.items()}
        for state,outcomes in enumerate(league_prior)])


def shrinkage_prior(league):
    return [{key:PITCHER_PRIOR_PA*value/sum(count.values()) for key,value in count.items()} for count in league]


def query(path, outs, bases, pitchers):
    if outs not in range(3) or bases not in range(8):
        raise ValueError('Outs must be 0–2 and the base occupancy mask must be 0–7')
    artifact = json.loads(path.read_bytes())

    def counts(row):
        return {tuple(map(int,key.split(','))):value for key,value in row.items()}

    league = list(map(counts,artifact['league']))
    prior = shrinkage_prior(league)
    personal = {}
    for key,row in artifact['by_pitcher'].items():
        pitcher,state = key.rsplit('|',1)
        if pitcher in pitchers:
            personal[pitcher,int(state)] = counts(row)
    state = outs*8+bases

    def pick(result):
        mean,zero,_ = result
        return {'expected_runs':float(mean[state]),'zero_run_probability':float(zero[state])}

    return {'cutoff':artifact['cutoff'],'outs':outs,'bases':bases,'league':pick(forecasts(league)),
            'pitchers':{p:{**pick(pooled_forecasts(prior,personal,p)),
                           'uses_pitcher_history':any((p,s) in personal for s in range(24))}
                        for p in pitchers}}


def predict_month(train, target):
    league, personal = fit_prior(train)
    mean, zero, short = forecasts(league)
    target = target.copy()
    target['league_mean'] = mean[target.state]
    target['league_zero'] = zero[target.state]
    target['three_pa_mean'] = short[target.state]
    prior = shrinkage_prior(league)
    by_pitcher = {pitcher:pooled_forecasts(prior,personal,pitcher) for pitcher in target.pitcher.unique()}
    target['pitcher_mean'] = [by_pitcher[p][0][s] for p,s in zip(target.pitcher,target.state)]
    target['pitcher_zero'] = [by_pitcher[p][1][s] for p,s in zip(target.pitcher,target.state)]
    return target


def paired_interval(frame, delta):
    games = frame.assign(delta=np.asarray(delta)).groupby('game').delta.agg(['sum','count'])
    idx = np.random.default_rng(20261112).integers(len(games), size=(2000,len(games)))
    draws = games['sum'].to_numpy()[idx].sum(axis=1)/games['count'].to_numpy()[idx].sum(axis=1)
    return np.quantile(draws,[.025,.975]).tolist()


def summary(frame):
    if frame.empty:
        return {'pa':0}
    scores = {}
    errors = {}
    for name in ('three_pa','league','pitcher'):
        error = frame[name+'_mean'] - frame.remaining
        errors[name] = error**2
        scores[name] = {'mse':float(errors[name].mean()),'mean_error':float(error.mean())}
        if name!='three_pa':
            scores[name]['zero_run_brier'] = float(((frame[name+'_zero']-frame.remaining.eq(0))**2).mean())
            scores[name]['predicted_zero'] = float(frame[name+'_zero'].mean())
    difference = errors['pitcher']-errors['league']
    return {'pa':len(frame),'games':int(frame.game.nunique()),'observed_zero':float(frame.remaining.eq(0).mean()),
            'scores':scores,'pitcher_minus_league_mse':float(difference.mean()),
            'game_cluster_ci':paired_interval(frame,difference)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--out', type=Path)
    mode.add_argument('--model', type=Path)
    parser.add_argument('--outs', type=int, default=0)
    parser.add_argument('--bases', type=int, default=0, help='Base occupancy mask: first=1, second=2, third=4')
    parser.add_argument('--pitcher', action='append', default=[], help='Rebas player key, repeat to compare')
    args = parser.parse_args()
    if args.model:
        print(json.dumps(query(args.model,args.outs,args.bases,args.pitcher),indent=2))
        return
    if args.out.exists():
        parser.error('Choose a new report')
    runtime = settings()
    if runtime.data_seasons != (2024,2025,2026):
        parser.error('Use the explicit three-season runtime')
    pa = load()[0]
    rows, excluded = clean_halves(pa)
    predictions = []
    for cutoff in runtime.replay_cutoffs:
        end = pd.Timestamp(cutoff)+pd.offsets.MonthBegin()
        target = rows[(rows.date >= cutoff)&(rows.date < end)&(rows.inning>=6)]
        predictions.append(predict_month(rows[rows.date < cutoff], target))
    all_rows = pd.concat(predictions)
    # A fixed pitcher forecast cannot be fully judged where real pitchers changed later.
    same = all_rows[all_rows.same_pitcher]
    final_league, final_personal = fit_prior(rows[rows.date < runtime.cutoff])
    full = {'cutoff':runtime.cutoff, 'league':[{f'{s},{r}':n for (s,r),n in c.items()} for c in final_league],
            'by_pitcher':{f'{p}|{state}':{f'{s},{r}':n for (s,r),n in c.items()}
                          for (p,state),c in final_personal.items()}}
    with args.out.with_name('half-inning-model.json').open('x',encoding='utf8') as stream:
        json.dump(full,stream,allow_nan=False,separators=(',',':'))
    report = {'scope':'2026 from inning six; contiguous recorded halves ending at three outs',
              'excluded_training_and_test_pa':excluded,
              'eligible_by_month':{c:len(d) for c,d in zip(runtime.replay_cutoffs,predictions)},
              'all':summary(all_rows),'two_out':summary(all_rows[all_rows.state>=16]),
              'same_pitcher_to_end':summary(same),'two_out_same_pitcher':summary(same[same.state>=16]),
              'limits':'Observed run forecast; later pitcher changes and exclusions affect comparison. No substitution effect.'}
    with args.out.open('x',encoding='utf8') as stream:
        json.dump(report,stream,indent=2,allow_nan=False)
    print(json.dumps({'all':report['all'],'two_out':report['two_out']},indent=2))


if __name__ == '__main__':
    main()
