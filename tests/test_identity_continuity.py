"""Behavioral checks for identity isolation, temporal queries and safe builds."""
import argparse
from contextlib import closing, redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_identity_continuity.py"
spec = importlib.util.spec_from_file_location("continuity", SCRIPT)
continuity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(continuity)
verify_spec = importlib.util.spec_from_file_location("continuity_verifier", SCRIPT.with_name("verify_identity_continuity.py"))
verifier = importlib.util.module_from_spec(verify_spec)
verify_spec.loader.exec_module(verifier)


def fixture(seq=1, day="2024-04-01", name="舊名", team="A"):
    g = {"seq": seq, "date": day, "awayTeam": team, "awayTeamId": team,
         "homeTeam": "H", "homeTeamId": "H", "awayScores": 0, "homeScores": 0}
    g["awayBatterBox"] = [{"playerId": "a1", "playerName": name, "playerNumber": "1", "order": 1}]
    g["homeBatterBox"] = [{"playerId": "h1", "playerName": "主打", "playerNumber": "1", "order": 1}]
    g["awayPitcherBox"] = [{"playerId": "pa", "playerName": "客投", "order": 1}]
    g["homePitcherBox"] = [{"playerId": "ph", "playerName": "主投", "order": 1}]
    for side, batter, pitcher, catcher in (("away", name, "主投", "主打"), ("home", "主打", "客投", name)):
        event = {"type": "PITCH", "batterName": batter, "pitcherName": pitcher, "catcherName": catcher,
                 "pitchCode": "B", "pitchType": "FF", "velocity": "140", "coordX": "1.25", "coordY": "-2"}
        g[side + "PAList"] = [{"inning": 1, "outs": 0, "bases": 0, "batterName": batter,
                               "pitcherName": pitcher, "catcherName": catcher, "isPH": False,
                               "events": [event], "result": "GO"}]
    return g


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        temp_parent = SCRIPT.parents[1] / "output"
        temp_parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix=".identity-tests-", dir=temp_parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"

    def write_games(self, games):
        for index, game in enumerate(games):
            season = game["date"][:4]
            folder = self.raw / season
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{index}.json").write_text(json.dumps(game, ensure_ascii=False), encoding="utf-8")

    def build(self, name="out", seasons=(2024,)):
        out = self.root / name
        with redirect_stdout(io.StringIO()):
            report = continuity.build(argparse.Namespace(root=self.raw, out=out, seasons=seasons))
        return out, report

    def query(self, out, player, day="2025-12-31"):
        return continuity.player_history(out / "identity.sqlite", player, day)

    def test_same_name_in_opposing_teams_never_merges(self):
        g = fixture(name="同名")
        g["homeBatterBox"][0]["playerName"] = "同名"
        g["homePAList"][0]["batterName"] = "同名"
        g["awayPAList"][0]["catcherName"] = "同名"
        g["homePAList"][0]["events"][0]["batterName"] = "同名"
        g["awayPAList"][0]["events"][0]["catcherName"] = "同名"
        self.write_games([g])
        out, report = self.build()
        self.assertEqual(report["identity_review"]["same_name_multiple_ids"]["同名"],
                         ["rebas:CPBL:a1", "rebas:CPBL:h1"])
        for player in ("a1", "h1"):
            row = self.query(out, player)
            self.assertEqual(row["plate_appearances_by_cutoff"]["batter"], 1)
            self.assertEqual(row["pitch_events_by_cutoff"]["batter"], 1)

    def test_rename_and_team_change_have_no_future_labels_or_counts(self):
        self.write_games([fixture(), fixture(2, "2025-04-01", "新名", "C")])
        out, _ = self.build(seasons=(2024, 2025))
        before = self.query(out, "a1", "2025-03-31")
        after = self.query(out, "rebas:CPBL:a1", "2025-04-01")
        self.assertEqual(before["names_observed_by_cutoff"], ["舊名"])
        self.assertEqual(before["teams_observed_by_cutoff"], ["A"])
        self.assertEqual(before["pitch_events_by_cutoff"]["batter"], 1)
        self.assertEqual(set(after["names_observed_by_cutoff"]), {"舊名", "新名"})
        self.assertEqual(after["teams_observed_by_cutoff"], ["A", "C"])
        self.assertEqual(after["pitch_events_by_cutoff"]["batter"], 2)
        future = self.query(out, "a1", "2024-03-31")
        unknown = self.query(out, "unknown", "2024-03-31")
        self.assertEqual({k: v for k, v in future.items() if k != "player_id"},
                         {k: v for k, v in unknown.items() if k != "player_id"})

    def test_pitch_participants_override_pa_summary_and_keep_event_positions(self):
        g = fixture()
        g["awayBatterBox"].append({"playerId": "a2", "playerName": "前打"})
        g["homePitcherBox"].append({"playerId": "ph2", "playerName": "前投"})
        g["homeBatterBox"].append({"playerId": "hc2", "playerName": "前捕"})
        pa = g["awayPAList"][0]
        earlier = copy.deepcopy(pa["events"][0])
        earlier.update(batterName="前打", pitcherName="前投", catcherName="前捕")
        pa["events"] = [{"type": "SUBSTITUTION"}, earlier, pa["events"][0]]
        self.write_games([g])
        out, report = self.build()
        for player, role in (("a2", "batter"), ("ph2", "pitcher"), ("hc2", "catcher")):
            row = self.query(out, player)
            self.assertEqual(row["plate_appearances_by_cutoff"][role], 0)
            self.assertEqual(row["pitch_events_by_cutoff"][role], 1)
        self.assertEqual(self.query(out, "a1")["pitch_events_by_cutoff"]["batter"], 1)
        self.assertEqual(report["event_participant_review"]["counts_by_role"], {"batter": 1, "pitcher": 1, "catcher": 1})
        with closing(sqlite3.connect(out / "identity.sqlite")) as conn:
            self.assertEqual(conn.execute("SELECT pitch_index,event_index FROM pitch_events WHERE pa_key LIKE '%:a000' ORDER BY pitch_index").fetchall(), [(0, 1), (1, 2)])

    def test_absent_event_name_can_inherit_but_explicit_null_is_quarantined(self):
        g = fixture()
        event = g["awayPAList"][0]["events"][0]
        del event["pitcherName"]
        event["batterName"] = None
        self.write_games([g])
        out, report = self.build()
        self.assertFalse(report["identity_resolution_complete"])
        self.assertEqual(self.query(out, "a1")["pitch_events_by_cutoff"]["batter"], 0)
        self.assertEqual(self.query(out, "ph")["pitch_events_by_cutoff"]["pitcher"], 1)
        with closing(sqlite3.connect(out / "identity.sqlite")) as conn:
            row = conn.execute("SELECT batter_player_key,pitcher_identity_basis FROM pitch_events WHERE pa_key LIKE '%:a000'").fetchone()
            self.assertEqual(row, (None, "parent_pa_field_absent"))
            self.assertEqual(conn.execute("SELECT role FROM identity_resolution_issues").fetchall(), [("pitch_batter",)])

    def test_ambiguous_or_invalid_source_ids_are_not_guessed(self):
        for raw_id in (None, True, [], " "):
            with self.subTest(raw_id=raw_id):
                g = fixture()
                g["awayBatterBox"].append({"playerId": raw_id, "playerName": "舊名"})
                # Each case gets its own source/output so no file is overwritten.
                self.raw = self.root / ("raw-" + str(len(list(self.root.iterdir()))))
                self.write_games([g])
                out, report = self.build(name="out-" + str(len(list(self.root.iterdir()))))
                self.assertFalse(report["identity_resolution_complete"])
                self.assertEqual(self.query(out, "a1")["plate_appearances_by_cutoff"]["batter"], 0)
                self.assertEqual(report["counts"]["players"], 4)

    def test_doubleheader_is_two_games_not_one_date(self):
        self.write_games([fixture(), fixture(2), fixture(3, "2024-04-02", team="C")])
        out, report = self.build()
        row = self.query(out, "a1")
        old = next(x for x in row["name_observations"] if x["team_name"] == "A")
        self.assertEqual((old["observed_games"], old["observed_dates"]), (2, 1))
        player = next(x for x in report["identity_review"]["players_observed_with_multiple_team_names"] if x["player_key"].endswith(":a1"))
        self.assertEqual(player["observed_teams"][0]["observed_games"], 2)

    def test_bad_measurements_keep_raw_value_and_are_not_imputed(self):
        g = fixture()
        event = g["awayPAList"][0]["events"][0]
        event.update(velocity="12+", coordX=True, coordY="nan")
        self.write_games([g])
        out, report = self.build()
        self.assertEqual(report["measurement_review"]["invalid_nonempty_numeric_values"], 3)
        self.assertFalse(report["strict_measurement_gate_passed"])
        with closing(sqlite3.connect(out / "identity.sqlite")) as conn:
            row = conn.execute("SELECT velocity_raw_json,velocity_value,coord_x_value,coord_y_value FROM pitch_events WHERE pa_key LIKE '%:a000'").fetchone()
            self.assertEqual(row, ('"12+"', None, None, None))

    def test_rebuild_is_deterministic_and_queries_are_read_only(self):
        self.write_games([fixture()])
        a, _ = self.build("one")
        b, _ = self.build("two")
        for name in ("identity.sqlite", "identity-review.json", "manifest.json", "README.md"):
            self.assertEqual(continuity._sha256(a / name), continuity._sha256(b / name), name)
        before = continuity._sha256(a / "identity.sqlite")
        self.query(a, "a1")
        self.query(a, "unknown")
        self.assertEqual(before, continuity._sha256(a / "identity.sqlite"))

    def test_existing_destination_and_build_lock_are_preserved(self):
        self.write_games([fixture()])
        out = self.root / "out"
        out.mkdir()
        sentinel = out / "keep.txt"
        sentinel.write_text("unchanged")
        with self.assertRaises(FileExistsError): self.build()
        self.assertEqual(sentinel.read_text(), "unchanged")
        lock = self.root / ".locked.build.lock"
        lock.write_text("other process")
        with self.assertRaises(FileExistsError): self.build("locked")
        self.assertEqual(lock.read_text(), "other process")
        self.assertFalse((self.root / "locked").exists())

    def test_failure_does_not_publish_partial_database_or_leave_lock(self):
        self.write_games([fixture(), fixture()])
        with self.assertRaisesRegex(ValueError, "duplicate"): self.build()
        self.assertFalse((self.root / "out").exists())
        self.assertFalse(list(self.root.glob(".out.*")))
        with self.assertRaisesRegex(ValueError, "no JSON"): self.build(seasons=(2026,))

    def test_wrong_date_invalid_states_and_nonfinite_json_fail_closed(self):
        for field, value in (("outs", 3), ("inning", True), ("bases", -1), ("events", None)):
            with self.subTest(field=field):
                g = fixture()
                g["awayPAList"][0][field] = value
                self.raw = self.root / ("raw-" + field)
                self.write_games([g])
                with self.assertRaises(ValueError): self.build("out-" + field)
        self.raw = self.root / "nan"
        g = fixture(); g["awayPAList"][0]["events"][0]["velocity"] = float("nan")
        self.write_games([g])
        with self.assertRaisesRegex(ValueError, "non-finite"): self.build("nan-out")
        self.raw = self.root / "wrong-year"
        (self.raw / "2024").mkdir(parents=True)
        (self.raw / "2024/x.json").write_text(json.dumps(fixture(day="2025-04-01")))
        with self.assertRaisesRegex(ValueError, "selected season"): self.build("wrong-year-out")

    def test_wrong_schema_and_missing_database_are_rejected_without_creating_files(self):
        wrong = self.root / "wrong.sqlite"
        with closing(sqlite3.connect(wrong)) as conn: conn.execute("CREATE TABLE unrelated(x)")
        with self.assertRaisesRegex(ValueError, "not an identity"): continuity.player_history(wrong, "a1", "2024-04-01")
        missing = self.root / "missing.sqlite"
        with self.assertRaises(sqlite3.OperationalError): continuity.player_history(missing, "a1", "2024-04-01")
        self.assertFalse(missing.exists())

    def test_destination_created_during_build_is_not_replaced(self):
        self.write_games([fixture()])
        original = continuity._create_database
        out = self.root / "out"

        def another_writer(*args):
            result = original(*args)
            out.mkdir()
            (out / "keep.txt").write_text("other writer")
            return result

        with mock.patch.object(continuity, "_create_database", side_effect=another_writer):
            with self.assertRaisesRegex(FileExistsError, "appeared during build"): self.build()
        self.assertEqual((out / "keep.txt").read_text(), "other writer")
        self.assertFalse(list(self.root.glob(".out.*")))

    def test_independent_verifier_accepts_source_and_detects_wrong_actor_with_same_counts(self):
        self.write_games([fixture(), fixture(2, "2025-04-01", "新名", "C")])
        out, _ = self.build(seasons=(2024, 2025))
        valid = verifier.verify(self.raw, out)
        self.assertTrue(valid["passed"], valid["failures_capped_at_100"])
        with closing(sqlite3.connect(out / "identity.sqlite")) as conn:
            conn.execute("UPDATE pitch_events SET pitcher_player_key='rebas:CPBL:pa' WHERE pa_key LIKE '%:a000'")
            conn.commit()
        # Update the digest deliberately: the raw-row verifier must still
        # reject a semantically wrong store with valid keys and row counts.
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        manifest["artifacts"]["identity.sqlite"] = continuity._sha256(out / "identity.sqlite")
        (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        wrong = verifier.verify(self.raw, out)
        self.assertFalse(wrong["passed"])
        categories = {row["check"] for row in wrong["failures_capped_at_100"]}
        self.assertIn("pitch_rows", categories)
        self.assertIn("cutoff_query", categories)


if __name__ == "__main__":
    unittest.main()
