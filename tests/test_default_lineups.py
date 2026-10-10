"""預設場上名單的棒球規則檢查（docs/data/default-lineups-2025.json）。"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
import server
from roster import can_play

POSITIONS = {"C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"}


class DefaultLineupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "docs/data/default-lineups-2025.json").read_text(encoding="utf-8"))
        cls.rosters = server.rosters()

    def test_every_team_has_a_default(self):
        self.assertEqual(set(self.data["teams"]), set(self.rosters))

    def test_nine_players_cover_each_position_once_with_dh(self):
        for team, v in self.data["teams"].items():
            names = [s["name"] for s in v["slots"]]
            self.assertEqual(len(names), 9, team)
            self.assertEqual(len(set(names)), 9, team)
            self.assertEqual({s["pos"] for s in v["slots"]}, POSITIONS, team)
            self.assertNotIn(v["pitcher"], names, f"{team}：指定打擊制下投手不在打序中")

    def test_players_belong_to_team_and_can_play_assigned_position(self):
        for team, v in self.data["teams"].items():
            hitters = {h["name"] for h in self.rosters[team]["hitters"]}
            for s in v["slots"]:
                self.assertIn(s["name"], hitters, team)
                self.assertTrue(can_play(s["name"], s["pos"]), f"{team}：{s['name']} 沒有守 {s['pos']} 的經驗")

    def test_pitcher_is_a_starter_on_the_roster(self):
        for team, v in self.data["teams"].items():
            pitchers = {p["name"]: p for p in self.rosters[team]["pitchers"]}
            self.assertIn(v["pitcher"], pitchers, team)
            self.assertEqual(pitchers[v["pitcher"]]["role"], "先發", team)


if __name__ == "__main__":
    unittest.main()
