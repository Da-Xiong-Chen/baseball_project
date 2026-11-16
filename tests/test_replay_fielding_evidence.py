import unittest

from scripts.audit_2026_fielding_coverage import observed_fielding


class ReplayFieldingEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.pinch = {"batterName": "代打", "events": [{"type": "PITCH", "batterName": "代打"}]}
        self.player_ids = {"代打": {"1"}, "原野手": {"2"}, "接守者": {"3"}}

    def snapshot(self, third_base):
        return {
            "catcherName": "捕手",
            "fielderNames": ["投手", "捕手", "一壘", "二壘", third_base, "游擊", "左外", "中外", "右外"],
        }

    def test_later_valid_snapshot_recovers_a_missing_opening_snapshot(self):
        self.assertEqual(observed_fielding(self.pinch, [("open", {}), ("next", self.snapshot("代打"))],
                                          self.player_ids),
                         {"status": "pinch_hitter_fielded", "position": "3B", "observed_pa": "next"})

    def test_same_position_opening_occupant_requires_evidence_on_both_sides(self):
        opening = [("next", self.snapshot("接守者"))]
        self.assertEqual(observed_fielding(self.pinch, opening, self.player_ids,
                                          [("before", self.snapshot("原野手"))], "原野手"),
                         {"status": "other_player_fielded", "observed_pa": "next",
                          "original_position": "3B", "opening_fielder": "接守者"})
        self.assertEqual(observed_fielding(self.pinch, opening, self.player_ids),
                         {"status": "other_player_fielded", "observed_pa": "next"})

    def test_no_following_half_and_ambiguous_mid_pa_are_distinct(self):
        self.assertEqual(observed_fielding(self.pinch, [], self.player_ids), {"status": "no_defensive_half"})
        self.pinch["events"].append({"type": "PITCH", "batterName": "另一打者"})
        self.assertEqual(observed_fielding(self.pinch, [], self.player_ids), {"status": "unconfirmed"})

    def test_incomplete_fielding_stays_unconfirmed(self):
        self.assertEqual(observed_fielding(self.pinch, [("open", {})], self.player_ids),
                         {"status": "unconfirmed"})
