"""Offline 2025 CPBL pitching-change checks for ordinary substitutions.

The caller supplies confirmed facts about the current dead-ball opportunity.
This models the first-batter obligations and re-entry checks in §5.10;
it does not model mound visits, official roster eligibility or position swaps.
"""
from dataclasses import dataclass
from typing import Literal

RuleState = Literal['clear', 'starter_first', 'relief_first', 'inning_start_first']


@dataclass(frozen=True)
class Change:
    season: int
    dead_ball: bool | None
    candidate_available: bool | None
    candidate_retired: bool | None
    obligation: RuleState | None
    first_batter_completed: bool | None = None
    half_inning_ended: bool | None = None
    umpire_injury_exception: bool = False


def assess(change: Change) -> tuple[str, str]:
    """Return a covered-rule status and a stable reason code."""
    if change.season != 2025:
        return 'unknown', 'season_unverified'
    if change.candidate_retired is True:
        return 'blocked', 'retired_cannot_reenter'
    if change.candidate_available is False:
        return 'blocked', 'candidate_unavailable'
    if change.dead_ball is False:
        return 'blocked', 'live_ball'
    if (change.dead_ball is not True or change.candidate_available is not True
            or change.candidate_retired is not False):
        return 'unknown', 'opportunity_or_roster_unconfirmed'
    if change.obligation not in ('clear', 'starter_first', 'relief_first', 'inning_start_first'):
        return 'unknown', 'obligation_unconfirmed'
    if change.obligation == 'clear':
        return 'passes_checks', 'no_first_batter_obligation'
    if change.umpire_injury_exception is True:
        return 'passes_checks', 'umpire_injury_exception'
    if change.first_batter_completed is True:
        return 'passes_checks', 'first_batter_completed'
    if change.obligation == 'relief_first' and change.half_inning_ended is True:
        return 'passes_checks', 'relief_half_inning_ended'
    if (change.first_batter_completed is None
            or (change.obligation == 'relief_first' and change.half_inning_ended is None)):
        return 'unknown', 'first_batter_or_half_inning_unconfirmed'
    return 'blocked', 'first_batter_obligation'
