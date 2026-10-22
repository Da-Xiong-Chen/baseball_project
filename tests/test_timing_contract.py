import sys
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from timing_backtest import summarize, cluster_interval, pen_timing


class TimingContractTests(unittest.TestCase):
    def test_missing_candidate_is_not_a_negative_recommendation(self):
        d = pd.DataFrame(dict(game=['a','b','c'], ph_gain=[2.,.1,np.nan],
                              pen_gain=[2.,.1,np.nan], is_ph=False, pen_change=False,
                              RE24=[.2,-.1,9], ph_has_bench=True))
        for result in summarize(d, 1).values():
            self.assertEqual(result['n'], 2)
            self.assertEqual(result['excluded'], 1)
            self.assertEqual(sum(result[k] for k in ['both','sys_only','actual_only','neither']), 2)

    def test_cluster_resamples_games_and_is_reproducible(self):
        d = pd.DataFrame(dict(game=['a','a','b','b','c','c'], gain=[2,0,2,0,2,0], RE24=[1,0,2,0,3,0]))
        self.assertEqual(cluster_interval(d,'gain',1), cluster_interval(d,'gain',1))
        one = d.assign(game='one')
        self.assertIsNone(cluster_interval(one,'gain',1))

    def test_missing_change_does_not_merge_pitcher_stints(self):
        d = pd.DataFrame(dict(game='g', fld_team='t', pen_gain=[2.,np.nan,.1,.1],
                              pen_change=[False,True,False,True],
                              stint_id=[1,2,2,3], inc_stint_id=[1,1,2,2]))
        # First change is unclassifiable, second has no signal in its own stint.
        self.assertEqual(pen_timing(d,1), [None])
