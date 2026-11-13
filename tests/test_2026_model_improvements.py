"""Check the boundaries of the new offline model prototypes."""
from collections import Counter
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from evaluate_half_inning_2026 import forecasts, np, pd
from evaluate_pa_outcomes_2026 import gain_values, game_result
from evaluate_pitcher_workload_2026 import prior_load
from train_2026_chronological import samples


class ModelImprovements(unittest.TestCase):
    def test_absorption_and_zero_probability_after_two_outs(self):
        counts = [Counter({(24, 0): 1}) for _ in range(24)]
        counts[16] = Counter({(24, 0): 3, (17, 1): 1})
        mean, zero, three = forecasts(counts)
        self.assertAlmostEqual(mean[16], .25)
        self.assertAlmostEqual(zero[16], .75)
        self.assertAlmostEqual(three[16], .25)
        self.assertTrue(np.all((zero >= 0) & (zero <= 1)))

    def test_workload_excludes_same_day_and_later_games(self):
        frame = pd.DataFrame({'pitcher':['p','p','new'], 'date':pd.to_datetime(['2026-07-04','2026-07-06','2026-07-06'])})
        boxes = pd.DataFrame({'role':['P']*4,'name':['p']*4, 'NP':[20,10,99,80],
                              'date':pd.to_datetime(['2026-07-01','2026-07-03','2026-07-04','2026-07-06'])})
        out = prior_load(frame,boxes)
        self.assertEqual(out.previous_day.tolist(), [10,0,0])
        self.assertEqual(out.last_three_days.tolist(), [30,109,0])
        self.assertEqual(out.rest_days.tolist(), [0,1,14])

    def test_pa_actor_change_is_not_attributed_to_one_player(self):
        frame = pd.DataFrame({'batter':['a','b','c'], 'start_batter':['a','x','c'],
                              'pitcher':['p','p','q'], 'start_pitcher':['p','p','p'],
                              'start_bhand':['L','R','R'], 'RE24':[.1,.2,.3]})
        out = samples(frame)
        self.assertEqual(out.batter.tolist(), ['a'])
        self.assertEqual(out.bhand.tolist(), ['L'])

    def test_terminal_win_change_uses_batting_team_direction(self):
        rows = pd.DataFrame([
            dict(inning=9,half='home',home_margin=0,outs=2,bases=2,runs=1,
                 terminal=True,home_result=1.0),
            dict(inning=9,half='away',home_margin=0,outs=2,bases=2,runs=0,
                 terminal=True,home_result=1.0),
        ])
        np.testing.assert_allclose(gain_values(rows,({}, {}, .5)), [.5,-.5])

    def test_rebas_inning_scores_can_be_strings(self):
        self.assertEqual(game_result({'homeScores':['0','2'],'awayScores':['1','0']}),1.0)
        self.assertEqual(game_result({'homeScores':['1','0'],'awayScores':['0','1']}),.5)
        with self.assertRaises(ValueError):
            game_result({'homeScores':['unknown'],'awayScores':['0']})
