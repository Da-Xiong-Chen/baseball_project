"""Compare dated candidate rules against the existing 2026 timing decision cohort."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
from historical_actors import decorate
from load import load
from roster import active_roster
from runtime_config import settings


VARIANTS = ((10, False, False), (10, True, False), (21, True, False), (35, True, False), (10, True, True))


def tally(counter, candidates, observed, off_team):
    counter.update({
        "decisions": 1, "empty": not candidates, "candidate_slots": len(candidates),
        "observed_changes": bool(observed), "observed_in_pool": bool(observed and observed in candidates),
        "different_latest_team_slots": len(candidates & off_team),
    })


def audit(timing):
    pa, pitches, boxes = load()
    season = decorate(pa[pa.season.eq(settings().season)])
    opening_date = season.date.min()
    previous_season = boxes[boxes.date.dt.year.eq(settings().season - 1)]
    carryover = {
        team: tuple(map(set, active_roster(team, last + pd.Timedelta(days=1), None, window_days=21)))
        for team, last in previous_season.groupby("team").date.max().items()
    }
    eligible = timing.set_index("pa_id", verify_integrity=True)
    if not eligible.index.isin(season.pa_id).all():
        raise ValueError("Timing cohort contains decisions outside the configured season")
    sighted = boxes.groupby("date", sort=True)
    dates = iter(sighted)
    next_history = next(dates, None)
    latest_teams = {}
    declared = defaultdict(Counter)
    breakdown = defaultdict(lambda: defaultdict(Counter))
    counts = Counter()
    decisions = {}
    candidate_sizes = defaultdict(Counter)

    relevant_pitches = pitches[pitches.pa_id.isin(season.pa_id)]
    actors_by_pa = {
        key: (set(rows.batter.dropna()), set(rows.pitcher.dropna()))
        for key, rows in relevant_pitches.groupby("pa_id", sort=False)
    }
    for date, day in season.groupby("date", sort=True):
        while next_history is not None and next_history[0] < date:
            _, previous = next_history
            for name, teams in previous.groupby("name").team:
                latest_teams[name] = set(teams)
            next_history = next(dates, None)
        for game, rows in day.groupby("game", sort=False):
            lineup = boxes[(boxes.game == game) & (boxes.role == "B")]
            used_hitters = {
                team: set(group.groupby("order").name.first()) for team, group in lineup.groupby("team")
            }
            used_pitchers = defaultdict(set)
            teams = set(rows.bat_team)
            history = {
                (team, window): tuple(map(set, active_roster(team, date, game, window_days=window)))
                for team in teams for window in {window for window, _, _ in VARIANTS}
            }
            datestr = str(date.date())
            last_team_conflicts = {
                team: {player for player, prior in latest_teams.items() if prior != {team}} for team in teams
            }
            for row in rows.sort_values(["inning", "half", "seq"]).itertuples():
                if row.pa_id in eligible.index:
                    record = eligible.loc[row.pa_id]
                    bench_used = used_hitters.get(row.bat_team, set()) | (
                        {row.start_batter} if not row.is_ph else set()
                    )
                    pen_used = used_pitchers[row.fld_team] | {record.inc}
                    actual = {
                        "ph": row.start_batter if row.is_ph and not row.mid_pa_actor_change else None,
                        "pen": row.start_pitcher if row.start_pitcher != record.inc else None,
                    }
                    states = {}
                    for window, filter_latest_team, opening_fallback in VARIANTS:
                        for kind, team, role_index, used in (
                            ("ph", row.bat_team, 0, bench_used),
                            ("pen", row.fld_team, 1, pen_used),
                        ):
                            proposed = history[team, window][role_index]
                            conflicts = last_team_conflicts[team]
                            candidates = proposed - used
                            if filter_latest_team:
                                candidates -= conflicts
                            key = f"{kind}_{window}" + ("_team" if filter_latest_team else "")
                            if opening_fallback:
                                key += "_opening"
                                if not candidates and date < opening_date + pd.Timedelta(days=10) and team in carryover:
                                    candidates = carryover[team][role_index] - used - conflicts
                            candidate_sizes[key][len(candidates)] += 1
                            tally(declared[key], candidates, actual[kind], conflicts)
                            tally(breakdown[f"{datestr[:7]} | {team}"][key], candidates, actual[kind], conflicts)
                            if filter_latest_team:
                                continue
                            status = record[f"{kind}_status"]
                            if (status == "no_candidate") != (not candidates):
                                counts[f"{kind}_baseline_disagreements"] += 1
                            if status == "no_candidate" and not candidates:
                                reason = "all_used" if proposed else "no_prior_pool"
                                counts[f"{kind}_{reason}"] += 1
                                breakdown[f"{datestr[:7]} | {team}"]["exclusions"][f"{kind}_{reason}"] += 1
                                states[kind] = reason
                            elif kind == "ph" and status == "fielding_unconfirmed":
                                counts["ph_fielding_unconfirmed"] += 1
                                breakdown[f"{datestr[:7]} | {team}"]["exclusions"]["ph_fielding_unconfirmed"] += 1
                                states[kind] = "fielding_unconfirmed"
                    if states:
                        decisions[row.pa_id] = states
                batters, pitchers = actors_by_pa.get(row.pa_id, (set(), set()))
                used_hitters.setdefault(row.bat_team, set()).update(batters | {row.batter})
                used_pitchers[row.fld_team].update(pitchers | {row.pitcher})
    covered = {row["decisions"] for row in declared.values()}
    if covered != {len(eligible)} or any(counts[f"{kind}_baseline_disagreements"] for kind in ("ph", "pen")):
        raise ValueError(f"Audit does not reproduce the frozen timing cohort: {dict(counts)}")
    return {
        "season": settings().season, "games": int(eligible.game.nunique()), "decisions": len(eligible),
        "summary": declared, "candidate_size_histograms": candidate_sizes, "by_month_team": breakdown,
        "exclusions": counts, "reasons": decisions,
        "scope": "Exact incumbent and prior actors; observed changes label coverage, not eligibility. "
                 "Alternatives require last observed team before game day to match. "
                 "Opening fallback only fills empty pools in the first ten calendar days, "
                 "using each club's final 21-day window from the previous season. Retrospective only.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timing-csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if settings().season != 2026 or args.out.exists():
        parser.error("Use the 2026 runtime and a new output path")
    report = audit(pd.read_csv(args.timing_csv))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps({"summary": report["summary"], "exclusions": report["exclusions"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
