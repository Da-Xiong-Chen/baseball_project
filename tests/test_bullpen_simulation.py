import sys
import unittest
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from simulate_bullpen_two_halves import observed_halves, simulate


class BullpenSimulationTests(unittest.TestCase):
    def setUp(self):
        self.uniforms = np.full((8, 20), .5)
        self.prior = ({(outs,0): Counter({(outs+1,0,0): 1}) for outs in range(3)},
                      defaultdict(Counter))

    def test_half_resets_and_next_pitcher_takes_over_at_capacity(self):
        runs, completed, reserved, used = simulate(
            ['A','B'], {'A': 3,'B': 3,'reserve': 4}, self.uniforms, self.prior)
        self.assertTrue(completed.all())
        self.assertTrue((runs == 0).all())
        self.assertTrue((reserved == 4).all())
        self.assertTrue((used == 6).all())

    def test_capacity_shortage_does_not_count_as_completed(self):
        _, completed, _, used = simulate(['A'], {'A': 5}, self.uniforms, self.prior)
        self.assertFalse(completed.any())
        self.assertTrue((used == 5).all())

    def test_duplicate_pitcher_and_unknown_capacity_are_rejected(self):
        for order, capacities in [(['A','A'],{'A': 4}), (['A'],{'A': None}), (['B'],{'A': 4})]:
            with self.subTest(order=order, capacities=capacities), self.assertRaises(ValueError):
                simulate(order, capacities, self.uniforms, self.prior)

    def test_replay_rejects_unmodelled_state_change_between_plate_appearances(self):
        rows = pd.DataFrame([
            dict(inning=i, seq=j, outs=j, bases=0, pitcher='A', bat_score=0,
                 end_outs=j+1, end_bases=0, runs=0)
            for i in (7,8) for j in range(3)
        ])
        halves, reason = observed_halves(rows)
        self.assertIsNone(reason)
        self.assertEqual([len(half) for half in halves], [3,3])
        rows.loc[1,'bases'] = 2
        self.assertEqual(observed_halves(rows), (None, 'between_pa_state_change'))
