"""Offline two-defensive-half bullpen simulation for 2025 CPBL examples."""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from assess_pitching_change_2025 import Change, assess
from evaluate_rolling_recency import load, np, write

SEED = 20261112
DRAWS = 5000
PITCHER_PRIOR_PA = 30
MAX_PA = 80


def transition(row):
    """State recorded at the plate appearance boundaries."""
    runs, outs, bases = int(row.runs), int(row.end_outs), int(row.end_bases)
    if runs < 0 or not 0 <= outs <= 3 or not 0 <= bases <= 7:
        raise ValueError('invalid transition')
    if outs < row.outs:
        raise ValueError('outs decreased within a half')
    return min(outs, 3), bases if outs < 3 else 0, runs


def observed_halves(half_rows):
    """Accept only contiguous complete halves with identifiable participants."""
    groups = []
    for inning in (7, 8):
        rows = list(half_rows[half_rows.inning == inning].sort_values('seq').itertuples())
        if not rows or (rows[0].outs, rows[0].bases) != (0, 0):
            return None, 'missing_or_nonstandard_start'
        for index, row in enumerate(rows):
            if not isinstance(row.pitcher, str):
                return None, 'unknown_pitcher'
            try:
                outs, bases, runs = transition(row)
            except (TypeError, ValueError):
                return None, 'invalid_transition'
            if index+1 < len(rows):
                following = rows[index+1]
                if outs >= 3 or (outs, bases, row.bat_score+runs) != (
                        following.outs, following.bases, following.bat_score):
                    return None, 'between_pa_state_change'
            elif outs != 3:
                return None, 'incomplete_half'
        groups.append(rows)
    return groups, None


def empirical_prior(rows):
    league = defaultdict(Counter)
    by_pitcher = defaultdict(Counter)
    for row in rows.itertuples():
        try:
            outcome = transition(row)
        except (ValueError, TypeError):
            continue
        state = int(row.outs), int(row.bases)
        if not isinstance(row.pitcher, str):
            continue
        # Exclude mid-PA actor swaps separately before calling this function.
        league[state][outcome] += 1
        by_pitcher[(row.pitcher, *state)][outcome] += 1
    return league, by_pitcher


def sampler(prior, pitchers):
    league, by_pitcher = prior
    table = {}
    for pitcher in pitchers:
        for state, counts in league.items():
            outcomes = sorted(counts)
            own = by_pitcher[(pitcher, *state)]
            total = sum(counts.values())
            weights = np.array([own[key] + PITCHER_PRIOR_PA*counts[key]/total for key in outcomes])
            cumulative = np.cumsum(weights/weights.sum())
            cumulative[-1] = 1
            table[(pitcher, *state)] = outcomes, cumulative
    return table


def simulate(order, capacity, uniforms, prior):
    if len(set(order)) != len(order) or not order or not set(order) <= set(capacity):
        raise ValueError('Invalid pitcher order')
    if any(type(v) is not int or v <= 0 for v in capacity.values()):
        raise ValueError('Capacity must be a confirmed positive integer')
    tables = sampler(prior, order)
    runs = np.zeros(len(uniforms), dtype=int)
    completed = np.zeros(len(uniforms), dtype=bool)
    reserved = np.zeros(len(uniforms), dtype=int)
    used = np.zeros(len(uniforms), dtype=int)
    for run, randoms in enumerate(uniforms):
        arm = outs = bases = half = batters = 0
        available = capacity.copy()
        for u in randoms:
            if available[order[arm]] == 0:
                arm += 1
                if arm == len(order):
                    break
                status, _ = assess(Change(2025, True, True, False, 'relief_first',
                                          first_batter_completed=True))
                if status != 'passes_checks':
                    break
            pitcher = order[arm]
            outcomes, cumulative = tables[pitcher, outs, bases]
            end_outs, end_bases, scored = outcomes[int(np.searchsorted(cumulative,u,side='right'))]
            available[pitcher] -= 1
            runs[run] += scored
            batters += 1
            outs, bases = end_outs, end_bases
            if outs == 3:
                half += 1
                if half == 2:
                    completed[run] = True
                    break
                outs = bases = 0
        used[run] = batters
        # Only capacity on pitchers not yet used, including anyone held out of the plan.
        reserved[run] = sum(v for p,v in available.items() if v == capacity[p])
    return runs, completed, reserved, used


def describe(runs, complete, reserved, used):
    full_runs = runs[complete]
    return {
        'completion_rate': float(complete.mean()),
        'mean_runs_if_complete': float(full_runs.mean()) if len(full_runs) else None,
        'run_quantiles_if_complete': np.quantile(full_runs,[.1,.5,.9]).tolist() if len(full_runs) else None,
        'run_distribution_if_complete': dict(sorted(Counter(full_runs.tolist()).items())),
        'mean_untouched_capacity': float(reserved.mean()),
        'mean_plate_appearances': float(used.mean()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():
        parser.error('Choose a new output file')
    pa, pitches, _ = load()
    actor_swaps = pitches.loc[pitches.pitcher.ne(pitches.pa_pitcher),'pa_id'].unique()
    valid = pa[~pa.pa_id.isin(actor_swaps)]
    prior = empirical_prior(valid[valid.season == 2024])
    assert len(prior[0]) == 24
    coverage, example, errors = Counter(), None, []
    for (game, side), rows in pa[pa.season==2025].sort_values(['date','game']).groupby(['game','half'],sort=False):
        halves, reason = observed_halves(rows)
        if reason:
            coverage[reason] += 1
            continue
        flat = [r for half in halves for r in half]
        if any(r.pa_id in actor_swaps for r in flat):
            coverage['mid_pa_pitcher_change'] += 1
            continue
        sequence = [row.pitcher for i,row in enumerate(flat) if i == 0 or row.pitcher != flat[i-1].pitcher]
        if len(sequence) != len(set(sequence)):
            coverage['reentry_or_position_swap'] += 1
            continue
        changes = len(sequence)-1
        coverage['replayed'] += 1
        coverage['pitcher_changes_replayed'] += changes
        actual_capacity = Counter(r.pitcher for r in flat)
        # Replay each outcome as recorded and reconcile allocation and score.
        assert sum(actual_capacity.values())==len(flat)
        assert sum(r.runs for r in flat)==sum(half[-1].bat_score+half[-1].runs-half[0].bat_score for half in halves)
        if changes >= 2 and example is None:
            example=(game, side, flat, sequence[:3])
    if example is None:
        raise ValueError('No qualifying historical example')
    game, side, rows, order=example
    capacities=dict(zip(order,(6,5,6)))
    randoms=np.random.default_rng(SEED).random((DRAWS,MAX_PA))
    plan_a=simulate(order,capacities,randoms,prior)
    deferred_order = [order[1], order[2], order[0]]
    plan_b=simulate(deferred_order,capacities,randoms,prior)
    common=plan_a[1]&plan_b[1]
    paired=plan_b[0][common]-plan_a[0][common]
    if not len(paired):
        raise ValueError('No simulations completed for both plans')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    write(args.out,{
        'reference_season':2024,'historical_replay_season':2025,
        'historical_replay':dict(coverage),
        'game':game,'date':str(rows[0].date.date()),'batting_side':side,
        'batting_team':rows[0].bat_team,'fielding_team':rows[0].fld_team,
        'innings':[7,8], 'observed_runs':int(sum(r.runs for r in rows)),
        'order_a':order,'order_b':deferred_order,'assumed_pa_capacity':capacities,
        'pitcher_names':{r.pitcher:r.pitcher_raw_name for r in rows if r.pitcher in order},
        'draws':DRAWS,'seed':SEED,'a':describe(*plan_a),'b':describe(*plan_b),
        'paired_complete':int(common.sum()),'paired_mean_run_difference':float(paired.mean()),
        'limitations':['Demonstration uses hypothetical capacities and a retrospective pitcher list.',
                       'Pitcher-specific state transitions shrink toward the prior-season league distribution.',
                       'Runs are model estimates conditional on completing both halves, not a substitution effect.',
                       'Opposing offensive turns, hitter identity, and game win probabilities are outside scope.'],
    })
    print(game, side, coverage, flush=True)


if __name__=='__main__':
    main()
