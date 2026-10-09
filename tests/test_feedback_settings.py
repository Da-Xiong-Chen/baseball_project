"""使用者回饋功能：連投疲勞設定、近況權重、輸入驗證。預設值必須完全不影響評估。"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

import server  # noqa: E402

OFFENSE = dict(inning=8, half="home", bat_score=3, fld_score=3, bases=1, outs=1, pitcher="林子昱", due="梁家榮",
               due_pos="3B", bench=["林智平", "林子偉", "成晉"], bat_team="樂天桃猿", fld_team="味全龍")
DEFENSE = dict(inning=8, half="away", bat_score=2, fld_score=3, bases=0, outs=0, pitcher="陳冠宇", due="李凱威",
               due_pos="DH", bench=[], bat_team="味全龍", fld_team="樂天桃猿", next_batters=["李凱威", "郭天信", "劉基鴻"],
               pen=["朱承洋", "莊昕諺"], pitch_count=10, starter=False)


def rows(result, key, name_key):
    return {r[name_key]: r[key] for r in result}


class FeedbackSettings(unittest.TestCase):
    def test_defaults_do_not_change_results(self):
        base = server.api("/api/evaluate", {}, OFFENSE)
        zero = server.api("/api/evaluate", {}, dict(OFFENSE, recent_weight=0))
        self.assertEqual(rows(base["candidates"], "預估勝率", "球員"), rows(zero["candidates"], "預估勝率", "球員"))
        d0 = server.api("/api/evaluate", {}, DEFENSE)
        d1 = server.api("/api/evaluate", {}, dict(DEFENSE, streaks={"朱承洋": 2}, fatigue_d2=0, fatigue_d3=0))
        self.assertEqual(rows(d0["bullpen"]["rows"], "預估失分", "投手"), rows(d1["bullpen"]["rows"], "預估失分", "投手"))

    def test_streak_penalty_applies_per_batter(self):
        d0 = rows(server.api("/api/evaluate", {}, DEFENSE)["bullpen"]["rows"], "預估失分", "投手")
        d1 = rows(server.api("/api/evaluate", {}, dict(DEFENSE, streaks={"朱承洋": 1, "莊昕諺": 2},
                                                        fatigue_d2=0.02, fatigue_d3=0.05))["bullpen"]["rows"], "預估失分", "投手")
        self.assertAlmostEqual(d1["朱承洋"] - d0["朱承洋"], 0.02 * 3, places=9)
        self.assertAlmostEqual(d1["莊昕諺"] - d0["莊昕諺"], 0.05 * 3, places=9)
        self.assertAlmostEqual(d1["陳冠宇"], d0["陳冠宇"], places=12)

    def test_recent_weight_moves_by_recent_form(self):
        r0 = server.api("/api/evaluate", {}, OFFENSE)["candidates"]
        r1 = server.api("/api/evaluate", {}, dict(OFFENSE, recent_weight=1.0))["candidates"]
        base = {r["球員"]: r["每打席得分值"] for r in r0}
        for r in r1:
            self.assertAlmostEqual(r["每打席得分值"] - base[r["球員"]], r["近況"], places=9)

    def test_invalid_settings_rejected(self):
        for bad in (dict(streaks={"朱承洋": -1}), dict(streaks={"林子昱": 1}), dict(fatigue_d2=0.9),
                    dict(recent_weight=1.5), dict(recent_weight="1")):
            with self.assertRaises(ValueError):
                server.api("/api/evaluate", {}, dict(DEFENSE, **bad))


if __name__ == "__main__":
    unittest.main()
