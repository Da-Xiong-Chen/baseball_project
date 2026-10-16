"""歷史回放的「現任打者」：守備替補上場、尚未打過的球員也必須算成現任，不能沿用被換下的先發。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from engine import load, situation


class ReplayIncumbentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pa = load()[0]

    def test_defensive_substitute_is_incumbent(self):
        # 2025-314：陳重廷守備替補上場後第一次打擊（不是代打），原先發林祖傑已退場
        row = self.pa.loc[self.pa["pa_id"] == "2025-314-a023"].iloc[0]
        self.assertFalse(bool(row["is_ph"]))
        sit = situation("2025-314-a023")
        self.assertEqual(sit["due"], row["batter"])
        self.assertNotIn(row["batter"], sit["bench"])

    def test_non_pinch_hit_incumbent_always_matches_batter(self):
        rows = self.pa[(~self.pa["is_ph"]) & (self.pa["inning"] >= 7)].sample(40, random_state=1)
        for pid, batter in zip(rows["pa_id"], rows["batter"]):
            with self.subTest(pa=pid):
                self.assertEqual(situation(pid)["due"], batter)

    def test_pinch_hit_incumbent_is_not_the_pinch_hitter(self):
        rows = self.pa[self.pa["is_ph"]].sample(20, random_state=1)
        for pid, batter in zip(rows["pa_id"], rows["batter"]):
            with self.subTest(pa=pid):
                self.assertNotEqual(situation(pid)["due"], batter)


if __name__ == "__main__":
    unittest.main()
