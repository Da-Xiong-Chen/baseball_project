"""換人時機回測與近期加權的單元測試。"""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import model
import timing_backtest as tb


def rows(gains, changes, team="A", game="G1"):
    return pd.DataFrame(dict(game=game, fld_team=team, pen_gain=gains, pen_change=changes))


class PenTimingTests(unittest.TestCase):
    def test_system_earlier_same_time_and_never(self):
        # 第 2 個打席起系統就建議（≥1），第 4 個打席才實際換投 → 早 2 個打席
        self.assertEqual(tb.pen_timing(rows([0.2, 1.5, 1.2, 0.3], [False, False, False, True]), 1.0), [2])
        # 換投當下才建議 → 0
        self.assertEqual(tb.pen_timing(rows([0.2, 0.4, 1.3], [False, False, True]), 1.0), [0])
        # 整段都沒建議 → None
        self.assertEqual(tb.pen_timing(rows([0.2, 0.4, 0.1], [False, False, True]), 1.0), [None])

    def test_each_stint_is_measured_separately_per_game_and_team(self):
        d = pd.concat([rows([1.5, 0.1, 0.2, 0.3], [False, True, False, True]),
                       rows([0.1, 2.0], [False, True], team="B")])
        self.assertEqual(tb.pen_timing(d, 1.0), [1, None, 0])
        s = tb.timing_summary([1, None, 0, 3])
        self.assertEqual((s["changes"], s["system_never"], s["same"], s["earlier"], s["earlier_median"]), (4, 1, 1, 2, 2.0))


class SummaryTests(unittest.TestCase):
    def test_counts_and_stay_comparison(self):
        d = pd.DataFrame(dict(pen_gain=[2.0, 2.0, 0.1, 0.1, 3.0], pen_change=[False, False, False, False, True],
                              ph_gain=[0.0, 1.5, None, 0.2, 0.0], is_ph=[False, True, False, False, False],
                              RE24=[0.5, 0.3, -0.1, -0.3, 0.0]))
        s = tb.summarize(d, 1.0)
        self.assertEqual((s["pen"]["n"], s["pen"]["actual"], s["pen"]["suggested"], s["pen"]["both"]), (5, 1, 3, 1))
        self.assertEqual((s["pen"]["sys_only"], s["pen"]["actual_only"]), (2, 0))
        # 系統建議但續投（0.5、0.3）平均 0.4；不建議（-0.1、-0.3）平均 -0.2
        self.assertAlmostEqual(s["pen"]["stay_diff"], 0.6)
        self.assertLess(s["pen"]["stay_diff_ci"][0], s["pen"]["stay_diff"])
        self.assertEqual((s["ph"]["n"], s["ph"]["actual"], s["ph"]["suggested"]), (4, 1, 1))


class DecisionPointTests(unittest.TestCase):
    def test_incumbent_is_previous_pitcher_of_same_fielding_team(self):
        d = tb.decision_points()
        self.assertTrue((d["inning"] >= tb.MIN_INNING).all())
        self.assertTrue(d["inc"].notna().all())
        changed = d[d["pitcher"] != d["inc"]]
        self.assertGreater(len(changed), 1000)
        # 實際換投比例應在合理範圍（每個打席不可能都換）
        self.assertLess(len(changed) / len(d), 0.3)


class RecencyTests(unittest.TestCase):
    def test_age_excludes_offseason(self):
        p = pd.DataFrame(dict(date=pd.to_datetime(["2024-10-01", "2025-04-01", "2025-04-11"]), season=[2024, 2025, 2025]))
        # 2024-10-01 → 2025-04-01 之間的休季不算；距最後一筆（2025-04-11）為 1 + 10 天
        np.testing.assert_allclose(model._age_days(p), [11, 10, 0])

    def test_default_has_no_recency_weighting(self):
        self.assertIsNone(model.PITCHER_HALF_LIFE)

    def test_half_life_changes_only_pitcher_effects(self):
        base = model.fit("2025-06-01")
        decay = model.fit("2025-06-01", pitcher_half_life=180)
        pd.testing.assert_frame_equal(base.bat_all, decay.bat_all)
        pd.testing.assert_series_equal(base.pit_all["n"], decay.pit_all["n"])
        self.assertFalse(np.allclose(base.pit_all["effect"], decay.pit_all["effect"]))


if __name__ == "__main__":
    unittest.main()
