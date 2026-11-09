"""CPBL 2025 first-batter and re-entry case checks."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from assess_pitching_change_2025 import Change, assess


class PitchingChangeRulesTests(unittest.TestCase):
    def setUp(self):
        self.opportunity = Change(2025, True, True, False, 'clear', False, False)

    def test_relief_first_batter_or_end_of_half_inning(self):
        relief = replace(self.opportunity, obligation='relief_first')
        self.assertEqual(assess(relief), ('blocked', 'first_batter_obligation'))
        self.assertEqual(assess(replace(relief, first_batter_completed=True)),
                         ('passes_checks', 'first_batter_completed'))
        self.assertEqual(assess(replace(relief, half_inning_ended=True)),
                         ('passes_checks', 'relief_half_inning_ended'))

    def test_starting_pitcher_and_start_of_inning_warmup(self):
        for obligation in ('starter_first', 'inning_start_first'):
            change = replace(self.opportunity, obligation=obligation)
            with self.subTest(obligation=obligation):
                self.assertEqual(assess(change), ('blocked', 'first_batter_obligation'))
                self.assertEqual(assess(replace(change, umpire_injury_exception=True)),
                                 ('passes_checks', 'umpire_injury_exception'))

    def test_reentry_and_live_ball_remain_blocked_with_injury(self):
        for fact, reason in [({'candidate_retired': True}, 'retired_cannot_reenter'),
                             ({'candidate_available': False}, 'candidate_unavailable'),
                             ({'dead_ball': False}, 'live_ball')]:
            with self.subTest(fact=fact):
                self.assertEqual(assess(replace(self.opportunity, umpire_injury_exception=True, **fact)),
                                 ('blocked', reason))

    def test_unknown_year_or_missing_facts_do_not_pass(self):
        for changes in ({'season': 2026}, {'candidate_available': None}, {'obligation': None},
                        {'obligation': 'relief_first', 'first_batter_completed': None}):
            with self.subTest(changes=changes):
                self.assertEqual(assess(replace(self.opportunity, **changes))[0], 'unknown')
