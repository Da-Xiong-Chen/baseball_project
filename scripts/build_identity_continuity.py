"""Build and query a source-namespaced, date-aware Rebas player identity store.

This is an offline research data layer. It does not alter the production loader,
site data, model files, or source JSON. Player identity is keyed by the source
box-score playerId; names and team labels remain dated observations.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing, contextmanager
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMESPACE = "rebas:CPBL"
SCHEMA_VERSION = "baseball.identity-continuity.v2"


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA application_id = 1112097842;
PRAGMA user_version = 2;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE source_files (
    source_file_id INTEGER PRIMARY KEY,
    source_namespace TEXT NOT NULL,
    season INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    UNIQUE(source_namespace, relative_path)
);
CREATE TABLE games (
    game_key TEXT PRIMARY KEY,
    source_namespace TEXT NOT NULL,
    source_file_id INTEGER NOT NULL REFERENCES source_files(source_file_id),
    season INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    game_date TEXT NOT NULL,
    stadium TEXT,
    away_team_id TEXT,
    away_team_name TEXT NOT NULL,
    home_team_id TEXT,
    home_team_name TEXT NOT NULL,
    away_score_raw_json TEXT,
    home_score_raw_json TEXT,
    UNIQUE(source_namespace, season, sequence)
);
CREATE INDEX games_by_date ON games(game_date, game_key);
CREATE TABLE players (
    player_key TEXT PRIMARY KEY,
    source_namespace TEXT NOT NULL,
    source_player_id TEXT NOT NULL,
    UNIQUE(source_namespace, source_player_id)
);
CREATE TABLE player_observations (
    observation_id INTEGER PRIMARY KEY,
    player_key TEXT REFERENCES players(player_key),
    source_player_id_raw_json TEXT,
    game_key TEXT NOT NULL REFERENCES games(game_key),
    observed_date TEXT NOT NULL,
    team_id TEXT,
    team_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('batter_box','pitcher_box')),
    observed_name TEXT,
    jersey_number TEXT,
    lineup_order INTEGER,
    stats_raw_json TEXT NOT NULL
);
CREATE INDEX player_observations_by_identity_date
    ON player_observations(player_key, observed_date, team_name, role);
CREATE INDEX player_observations_by_name_date
    ON player_observations(observed_name, observed_date);
CREATE TABLE plate_appearances (
    pa_key TEXT PRIMARY KEY,
    game_key TEXT NOT NULL REFERENCES games(game_key),
    batting_side TEXT NOT NULL CHECK(batting_side IN ('away','home')),
    pa_index INTEGER NOT NULL,
    inning INTEGER,
    outs_before INTEGER,
    bases_before INTEGER,
    batter_name TEXT,
    batter_hand TEXT,
    batter_player_key TEXT REFERENCES players(player_key),
    pitcher_name TEXT,
    pitcher_hand TEXT,
    pitcher_player_key TEXT REFERENCES players(player_key),
    catcher_name TEXT,
    catcher_player_key TEXT REFERENCES players(player_key),
    result TEXT,
    is_pinch_hitter INTEGER,
    raw_json TEXT NOT NULL,
    UNIQUE(game_key, batting_side, pa_index)
);
CREATE INDEX pa_by_batter_date ON plate_appearances(batter_player_key, game_key);
CREATE INDEX pa_by_pitcher_date ON plate_appearances(pitcher_player_key, game_key);
CREATE INDEX pa_by_catcher_date ON plate_appearances(catcher_player_key, game_key);
CREATE TABLE pitch_events (
    pitch_key TEXT PRIMARY KEY,
    pa_key TEXT NOT NULL REFERENCES plate_appearances(pa_key),
    pitch_index INTEGER NOT NULL,
    event_index INTEGER NOT NULL,
    pitch_code TEXT,
    pitch_type TEXT,
    batter_name TEXT,
    batter_player_key TEXT REFERENCES players(player_key),
    batter_identity_basis TEXT NOT NULL,
    pitcher_name TEXT,
    pitcher_player_key TEXT REFERENCES players(player_key),
    pitcher_identity_basis TEXT NOT NULL,
    catcher_name TEXT,
    catcher_player_key TEXT REFERENCES players(player_key),
    catcher_identity_basis TEXT NOT NULL,
    coord_x_present INTEGER NOT NULL,
    coord_x_raw_json TEXT NOT NULL,
    coord_x_value REAL,
    coord_y_present INTEGER NOT NULL,
    coord_y_raw_json TEXT NOT NULL,
    coord_y_value REAL,
    velocity_present INTEGER NOT NULL,
    velocity_raw_json TEXT NOT NULL,
    velocity_value REAL,
    invalid_measurements_json TEXT NOT NULL,
    raw_event_json TEXT NOT NULL,
    UNIQUE(pa_key, pitch_index),
    UNIQUE(pa_key, event_index)
);
CREATE INDEX pitches_by_pa ON pitch_events(pa_key, pitch_index);
CREATE INDEX pitches_by_batter ON pitch_events(batter_player_key, pa_key);
CREATE INDEX pitches_by_pitcher ON pitch_events(pitcher_player_key, pa_key);
CREATE INDEX pitches_by_catcher ON pitch_events(catcher_player_key, pa_key);
CREATE TABLE identity_resolution_issues (
    issue_id INTEGER PRIMARY KEY,
    game_key TEXT NOT NULL REFERENCES games(game_key),
    pa_key TEXT REFERENCES plate_appearances(pa_key),
    pitch_key TEXT REFERENCES pitch_events(pitch_key),
    role TEXT NOT NULL,
    observed_name TEXT,
    reason TEXT NOT NULL,
    candidates_raw_json TEXT NOT NULL
);
CREATE INDEX identity_issues_by_game ON identity_resolution_issues(game_key, role);
"""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _reject_constant(value):
    raise ValueError("non-finite JSON constant: " + value)


def _source_id(value):
    if value is None or value == "":
        return None
    return str(value)


def _player_source_id(value):
    # Rebas playerId is an opaque nonempty string. Coercing booleans, arrays,
    # or whitespace to IDs could silently merge unrelated malformed records.
    return value if isinstance(value, str) and value and value == value.strip() else None


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _player_key(source_player_id):
    if source_player_id is None:
        return None
    return SOURCE_NAMESPACE + ":" + source_player_id


def _number(raw):
    """Return an observed finite number without coercing malformed values."""
    if raw is None or raw == "":
        return None, None
    if isinstance(raw, bool):
        return None, "boolean_not_numeric"
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None, "not_numeric"
    if not math.isfinite(value):
        return None, "non_finite"
    return value, None


def _game_key(season, sequence):
    return f"{SOURCE_NAMESPACE}:{season}-{sequence:03d}"


def _insert_issue(cursor, game_key, pa_key, role, name, reason, candidates=(), pitch_key=None):
    cursor.execute(
        "INSERT INTO identity_resolution_issues"
        "(game_key,pa_key,pitch_key,role,observed_name,reason,candidates_raw_json) VALUES(?,?,?,?,?,?,?)",
        (game_key, pa_key, pitch_key, role, name if isinstance(name, str) else None,
         reason, _json(sorted(candidates))),
    )


def _resolve_name(name, roster):
    if not isinstance(name, str) or not name:
        return None, "missing_name", []
    raw_candidates = roster.get(name, set())
    candidates = sorted(candidate for candidate in raw_candidates if candidate is not None)
    has_unidentified_box_row = None in raw_candidates
    if len(candidates) == 1 and not has_unidentified_box_row:
        return candidates[0], None, candidates
    if not candidates and has_unidentified_box_row:
        return None, "matching_box_record_missing_source_player_id", candidates
    if not candidates:
        return None, "no_exact_same_game_team_box_match", candidates
    reason = ("ambiguous_same_game_team_box_match" if len(candidates) > 1
              else "ambiguous_due_to_unidentified_same_name_box_row")
    return None, reason, candidates


def _list_json_files(root, seasons):
    if not seasons or any(isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2200
                          for year in seasons):
        raise ValueError("select one or more valid integer seasons")
    files = []
    errors = []
    for season in sorted(set(seasons)):
        season_dir = root / str(season)
        matches = sorted(season_dir.glob("*.json")) if season_dir.is_dir() else []
        if not matches:
            errors.append(f"no JSON source files for explicitly selected season {season}: {season_dir}")
        files.extend((season, path) for path in matches)
    if errors:
        raise ValueError("; ".join(errors))
    return files


def _create_database(db_path, source_root, seasons):
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO metadata VALUES(?,?)",
                         [("schema", SCHEMA_VERSION), ("source_namespace", SOURCE_NAMESPACE)])
        conn.commit()
        return _populate_database(conn, source_root, seasons)


def _populate_database(conn, source_root, seasons):
    files = _list_json_files(source_root, seasons)
    cursor = conn.cursor()
    counts = defaultdict(int)
    names_to_ids = defaultdict(set)
    ids_to_names = defaultdict(set)
    ids_to_seasons = defaultdict(set)
    ids_to_team_games = defaultdict(lambda: defaultdict(dict))
    bad_measurements = []
    participant_differences = []
    duplicate_game_keys = set()

    try:
        conn.execute("BEGIN IMMEDIATE")
        for selected_season, path in files:
            raw_bytes = path.read_bytes()
            source_hash = hashlib.sha256(raw_bytes).hexdigest()
            try:
                game = json.loads(raw_bytes, parse_constant=_reject_constant)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid JSON source {path}: {exc}") from exc
            try:
                if not isinstance(game, dict) or not isinstance(game.get("date"), str):
                    raise ValueError("game must have an ISO date string")
                game_date = date.fromisoformat(str(game["date"])[:10]).isoformat()
                sequence = game["seq"]
                if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
                    raise ValueError("invalid game sequence")
                if date.fromisoformat(game_date).year != selected_season:
                    raise ValueError("game date does not match selected season")
                for side in ("away", "home"):
                    if not isinstance(game.get(side + "Team"), str) or not game[side + "Team"]:
                        raise ValueError(f"missing {side} team name")
                    for suffix in ("BatterBox", "PitcherBox", "PAList"):
                        if not isinstance(game.get(side + suffix), list):
                            raise ValueError(f"invalid {side + suffix}")
                if game["awayTeam"] == game["homeTeam"]:
                    raise ValueError("identical opponents")
                if game.get("awayTeamId") not in (None, "") and game.get("awayTeamId") == game.get("homeTeamId"):
                    raise ValueError("identical opponent source team IDs")
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid game envelope {path}: {exc}") from exc

            game_key = _game_key(selected_season, sequence)
            if game_key in duplicate_game_keys:
                raise ValueError(f"duplicate source game identity: {game_key}")
            duplicate_game_keys.add(game_key)
            relative_path = path.relative_to(source_root).as_posix()
            cursor.execute(
                "INSERT INTO source_files(source_namespace,season,relative_path,sha256) VALUES(?,?,?,?)",
                (SOURCE_NAMESPACE, selected_season, relative_path, source_hash),
            )
            source_file_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO games VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (game_key, SOURCE_NAMESPACE, source_file_id, selected_season, sequence, game_date,
                 game.get("stadium"), _source_id(game.get("awayTeamId")), game["awayTeam"],
                 _source_id(game.get("homeTeamId")), game["homeTeam"],
                 _json(game.get("awayScores")), _json(game.get("homeScores"))),
            )
            counts["games"] += 1
            counts["source_files"] += 1

            # Build exact-name indexes for this game only. Different IDs with
            # the same name remain distinct and therefore unresolved as needed.
            roster = {"away": {"batter_box": defaultdict(set), "pitcher_box": defaultdict(set), "all": defaultdict(set)},
                      "home": {"batter_box": defaultdict(set), "pitcher_box": defaultdict(set), "all": defaultdict(set)}}
            for side in ("away", "home"):
                team_name = game[side + "Team"]
                team_id = _source_id(game.get(side + "TeamId"))
                for box_suffix, role in (("BatterBox", "batter_box"), ("PitcherBox", "pitcher_box")):
                    for player in game[side + box_suffix]:
                        if not isinstance(player, dict):
                            raise ValueError(f"invalid box player in {path} {side}{box_suffix}")
                        raw_id = player.get("playerId")
                        source_player_id = _player_source_id(raw_id)
                        player_key = _player_key(source_player_id)
                        observed_name = player.get("playerName")
                        if source_player_id:
                            cursor.execute(
                                "INSERT OR IGNORE INTO players(player_key,source_namespace,source_player_id) VALUES(?,?,?)",
                                (player_key, SOURCE_NAMESPACE, source_player_id),
                            )
                            ids_to_seasons[player_key].add(selected_season)
                            ids_to_team_games[player_key][team_name][game_key] = game_date
                            if isinstance(observed_name, str) and observed_name:
                                names_to_ids[observed_name].add(player_key)
                                ids_to_names[player_key].add(observed_name)
                        if isinstance(observed_name, str) and observed_name:
                            roster[side][role][observed_name].add(player_key)
                            roster[side]["all"][observed_name].add(player_key)
                        cursor.execute(
                            "INSERT INTO player_observations"
                            "(player_key,source_player_id_raw_json,game_key,observed_date,team_id,team_name,role,"
                            "observed_name,jersey_number,lineup_order,stats_raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (player_key, _json(raw_id), game_key, game_date, team_id, team_name, role,
                             observed_name if isinstance(observed_name, str) else None,
                             str(player.get("playerNumber")) if player.get("playerNumber") is not None else None,
                             player.get("order"), _json(player)),
                        )
                        counts["player_observations"] += 1
                        if not source_player_id:
                            _insert_issue(cursor, game_key, None, role, observed_name,
                                          "box_score_missing_source_player_id")

            for side in ("away", "home"):
                defense = "home" if side == "away" else "away"
                for pa_index, pa in enumerate(game[side + "PAList"]):
                    if not isinstance(pa, dict):
                        raise ValueError(f"invalid PA object in {path} {side}[{pa_index}]")
                    for field, lower, upper in (("inning", 1, 30), ("outs", 0, 2), ("bases", 0, 7)):
                        value = pa.get(field)
                        if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                            raise ValueError(f"invalid PA {field} in {path} {side}[{pa_index}]")
                    if "events" not in pa or not isinstance(pa["events"], list):
                        raise ValueError(f"invalid PA events in {path} {side}[{pa_index}]")
                    if pa.get("isPH") is not None and not isinstance(pa["isPH"], bool):
                        raise ValueError(f"invalid isPH in {path} {side}[{pa_index}]")
                    pa_key = f"{game_key}:{side[0]}{pa_index:03d}"
                    batter_name = pa.get("batterName")
                    pitcher_name = pa.get("pitcherName")
                    catcher_name = pa.get("catcherName")
                    batter_key, batter_reason, batter_candidates = _resolve_name(
                        batter_name, roster[side]["batter_box"])
                    pitcher_key, pitcher_reason, pitcher_candidates = _resolve_name(
                        pitcher_name, roster[defense]["pitcher_box"])
                    catcher_key, catcher_reason, catcher_candidates = _resolve_name(
                        catcher_name, roster[defense]["all"])
                    is_ph = pa.get("isPH")
                    is_ph_value = int(is_ph) if isinstance(is_ph, bool) else None
                    cursor.execute(
                        "INSERT INTO plate_appearances"
                        "(pa_key,game_key,batting_side,pa_index,inning,outs_before,bases_before,batter_name,batter_hand,"
                        "batter_player_key,pitcher_name,pitcher_hand,pitcher_player_key,catcher_name,catcher_player_key,"
                        "result,is_pinch_hitter,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (pa_key, game_key, side, pa_index, pa.get("inning"), pa.get("outs"), pa.get("bases"),
                         batter_name if isinstance(batter_name, str) else None, pa.get("batterHand"), batter_key,
                         pitcher_name if isinstance(pitcher_name, str) else None, pa.get("pitcherHand"), pitcher_key,
                         catcher_name if isinstance(catcher_name, str) else None, catcher_key,
                         pa.get("result", pa.get("results")), is_ph_value,
                         _json(pa)),
                    )
                    counts["plate_appearances"] += 1
                    for role, name, resolved, reason, candidates in (
                        ("batter", batter_name, batter_key, batter_reason, batter_candidates),
                        ("pitcher", pitcher_name, pitcher_key, pitcher_reason, pitcher_candidates),
                        ("catcher", catcher_name, catcher_key, catcher_reason, catcher_candidates),
                    ):
                        if reason:
                            _insert_issue(cursor, game_key, pa_key, role, name, reason, candidates)
                    events = pa["events"]
                    pitch_index = 0
                    for event_index, event in enumerate(events):
                        if not isinstance(event, dict):
                            raise ValueError(f"invalid event in {path} {side}[{pa_index}][{event_index}]")
                        if not isinstance(event.get("type"), str) or not event["type"]:
                            raise ValueError(f"missing event type in {path} {side}[{pa_index}][{event_index}]")
                        if event.get("type") != "PITCH":
                            continue
                        pitch_key = f"{pa_key}:p{pitch_index:03d}"
                        participants = {}
                        for role, field, owner, box_role, pa_name in (
                            ("batter", "batterName", side, "batter_box", batter_name),
                            ("pitcher", "pitcherName", defense, "pitcher_box", pitcher_name),
                            ("catcher", "catcherName", defense, "all", catcher_name),
                        ):
                            # An explicit event participant takes precedence. Only
                            # an absent field can inherit its enclosing PA name.
                            name = event[field] if field in event else pa_name
                            basis = "event_name" if field in event else "parent_pa_field_absent"
                            key, reason, candidates = _resolve_name(name, roster[owner][box_role])
                            participants[role] = (name if isinstance(name, str) else None, key, basis, reason, candidates)
                            if field in event and name != pa_name:
                                participant_differences.append({
                                    "game_key": game_key, "date": game_date, "side": side,
                                    "pa_index": pa_index, "event_index": event_index, "role": role,
                                    "pa_name": pa_name, "event_name": name,
                                    "event_player_key": key,
                                })
                        values = {}
                        invalid = {}
                        for column, source_field in (("coord_x", "coordX"), ("coord_y", "coordY"), ("velocity", "velocity")):
                            value, reason = _number(event.get(source_field))
                            values[column] = (int(source_field in event), _json(event.get(source_field)), value)
                            if reason:
                                invalid[column] = reason
                                bad_measurements.append({
                                    "game_key": game_key, "date": game_date, "side": side,
                                    "pa_index": pa_index, "event_index": event_index,
                                    "measurement": column, "raw_json": _json(event.get(source_field)),
                                    "reason": reason,
                                })
                        cursor.execute(
                            "INSERT INTO pitch_events"
                            "(pitch_key,pa_key,pitch_index,event_index,pitch_code,pitch_type,"
                            "batter_name,batter_player_key,batter_identity_basis,"
                            "pitcher_name,pitcher_player_key,pitcher_identity_basis,"
                            "catcher_name,catcher_player_key,catcher_identity_basis,"
                            "coord_x_present,coord_x_raw_json,coord_x_value,coord_y_present,coord_y_raw_json,coord_y_value,"
                            "velocity_present,velocity_raw_json,velocity_value,invalid_measurements_json,raw_event_json)"
                            " VALUES(" + ",".join("?" for _ in range(26)) + ")",
                            (pitch_key, pa_key, pitch_index, event_index,
                             event.get("pitchCode"), event.get("pitchType"),
                             *participants["batter"][:3], *participants["pitcher"][:3], *participants["catcher"][:3],
                             *values["coord_x"], *values["coord_y"], *values["velocity"],
                             _json(invalid), _json(event)),
                        )
                        for role, (name, _, _, reason, candidates) in participants.items():
                            if reason:
                                _insert_issue(cursor, game_key, pa_key, "pitch_" + role,
                                              name, reason, candidates, pitch_key=pitch_key)
                        counts["pitches"] += 1
                        pitch_index += 1

        conn.commit()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk_violations:
            raise RuntimeError(f"database integrity failed: {integrity}; foreign keys: {fk_violations[:5]}")
        counts["players"] = len(ids_to_seasons)
        for table, key in (("games", "games"), ("players", "players"),
                           ("player_observations", "player_observations"),
                           ("plate_appearances", "plate_appearances"), ("pitch_events", "pitches"),
                           ("source_files", "source_files")):
            actual = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if actual != counts[key]:
                raise RuntimeError(f"row count mismatch in {table}: expected {counts[key]}, got {actual}")
    except Exception:
        conn.rollback()
        raise

    all_ids = sorted(ids_to_seasons)
    same_id_multiple_names = {}
    for player_key in all_ids:
        observed_names = sorted(ids_to_names[player_key])
        if len(observed_names) > 1:
            observations = conn.execute(
                "SELECT observed_name, MIN(observed_date), MAX(observed_date) "
                "FROM player_observations WHERE player_key=? AND observed_name IS NOT NULL GROUP BY observed_name "
                "ORDER BY MIN(observed_date), observed_name",
                (player_key,),
            ).fetchall()
            same_id_multiple_names[player_key] = [
                {"name": row[0], "first_observed": row[1], "last_observed": row[2],
                 "teams_observed": [team[0] for team in conn.execute(
                     "SELECT DISTINCT team_name FROM player_observations WHERE player_key=? AND observed_name=? ORDER BY team_name",
                     (player_key, row[0]))]}
                for row in observations
            ]
    same_name_multiple_ids = {
        name: sorted(player_keys) for name, player_keys in sorted(names_to_ids.items()) if len(player_keys) > 1
    }
    multi_season_players = [
        {"player_key": key, "source_player_id": key.split(":", 2)[-1],
         "seasons_observed": sorted(ids_to_seasons[key])}
        for key in all_ids if len(ids_to_seasons[key]) > 1
    ]
    multi_team_observations = []
    for key in all_ids:
        teams = ids_to_team_games[key]
        if len(teams) > 1:
            multi_team_observations.append({
                "player_key": key,
                "observed_teams": [
                    {"team_name": team, "first_observed": min(games.values()), "last_observed": max(games.values()),
                     "observed_games": len(games)}
                    for team, games in sorted(teams.items())
                ],
                "interpretation": "observations only; not a verified transaction or roster interval",
            })
    unresolved_rows = conn.execute(
        "SELECT role,reason,COUNT(*) FROM identity_resolution_issues GROUP BY role,reason ORDER BY role,reason"
    ).fetchall()
    unresolved_examples = conn.execute(
        "SELECT game_key,pa_key,pitch_key,role,observed_name,reason,candidates_raw_json "
        "FROM identity_resolution_issues ORDER BY issue_id LIMIT 30"
    ).fetchall()
    unresolved_summary = {
        "total": sum(row[2] for row in unresolved_rows),
        "by_role_and_reason": [dict(role=r[0], reason=r[1], count=r[2]) for r in unresolved_rows],
        "examples_capped_at_30": [dict(game_key=r[0], pa_key=r[1], pitch_key=r[2], role=r[3], name=r[4], reason=r[5],
                                        candidates=json.loads(r[6])) for r in unresolved_examples],
    }
    player_count = counts["players"]

    return {
        "schema": SCHEMA_VERSION,
        "build_status": "complete",
        "identity_resolution_complete": unresolved_summary["total"] == 0,
        "strict_measurement_gate_passed": len(bad_measurements) == 0,
        "source_namespace": SOURCE_NAMESPACE,
        "selected_seasons": sorted(set(seasons)),
        "counts": {"source_files": counts["source_files"], "games": counts["games"],
                   "players": player_count, "player_box_observations": counts["player_observations"],
                   "plate_appearances": counts["plate_appearances"], "pitch_events": counts["pitches"]},
        "integrity": {"sqlite_integrity_check": "ok", "foreign_key_violations": 0},
        "identity_review": {
            "same_name_multiple_ids": same_name_multiple_ids,
            "same_id_multiple_names": same_id_multiple_names,
            "players_observed_in_multiple_seasons": multi_season_players,
            "players_observed_with_multiple_team_names": multi_team_observations,
            "unresolved_identity_observations": unresolved_summary,
            "team_and_name_dates_are_observations_not_contract_or_roster_intervals": True,
            "no_canonical_name_or_name_only_merge_created": True,
        },
        "measurement_review": {
            "invalid_nonempty_numeric_values": len(bad_measurements),
            "items": bad_measurements,
            "raw_json_values_preserved": True,
            "invalid_values_are_not_imputed": True,
        },
        "event_participant_review": {
            "differences_from_pa_summary": len(participant_differences),
            "counts_by_role": {role: sum(row["role"] == role for row in participant_differences)
                               for role in ("batter", "pitcher", "catcher")},
            "items": participant_differences,
            "policy": "Resolve each explicit event name in its own game/team box; absent fields inherit PA name explicitly.",
        },
        "model_ready": False,
        "model_ready_note": "An identity store is not model validation, feature parity, fielding eligibility, or production adoption.",
    }


def _readme():
    return """# Rebas 跨年度球員身分資料層

這是隔離的離線研究資料層，不會替換正式網站載入器或模型。

## 建置

```powershell
python scripts/build_identity_continuity.py build --seasons 2024 2025 --out output/player-identity-new
```

輸出資料夾必須尚不存在；工具不覆寫舊交付。建置失敗時不發布半成品。資料庫以 `rebas:CPBL:<source playerId>` 作為穩定鍵，逐場保留原始來源檔 SHA-256、box-score 名稱觀測、打席、逐球及身分解析問題。日期查詢只使用截止日當天及之前的觀測。

## 查詢球員歷程

```powershell
python scripts/build_identity_continuity.py player --db output/player-identity-new/identity.sqlite --player-id gdEku --as-of 2024-12-31
```

也可傳完整鍵，例如 `rebas:CPBL:gdEku`。回傳名稱、球隊、角色及打席／逐球統計都只根據截止日前的來源觀測。沒有資料時回傳 `found: false`，不會用未來名稱補值。

## 資料邊界

- 同名不同來源 ID 保持分離；不以姓名、背號或跨年最後名稱合併。
- 球隊名稱是該場 box-score 的觀測，不等於正式轉隊日期或完整名單區間。
- 捕手只在同一場防守隊 box-score 中可唯一對應時連結；否則列為待核對，不猜 ID。
- 每顆球優先採用事件本身的打者、投手及捕手名稱；與打席摘要不同時保留差異紀錄。僅當事件缺少該欄位時，明確記錄沿用打席姓名；明示空值不會被補值。
- `--as-of` 包含指定日期當天的已觀測資料，以日期為粒度；不能用來宣稱同一天比賽中的即時名單資訊。
- 非數字球速／座標原值保留在資料庫及報告中，不插補、不更動原始檔。
- `model_ready` 固定為 false；資料層完成不代表模型已通過驗證或採用。
"""


def build(args):
    source_root = args.root.resolve()
    final_dir = args.out.resolve()
    if final_dir.exists():
        raise FileExistsError(f"output already exists; refusing to overwrite: {final_dir}")
    if final_dir == source_root or source_root in final_dir.parents:
        raise ValueError("output must not be inside the raw source data directory")
    _list_json_files(source_root, args.seasons)
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    with _build_lock(final_dir), tempfile.TemporaryDirectory(prefix=f".{final_dir.name}.staging-", dir=final_dir.parent) as temp:
        staging = Path(temp)
        db_path = staging / "identity.sqlite"
        report = _create_database(db_path, source_root, args.seasons)
        report_path = staging / "identity-review.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        (staging / "README.md").write_text(_readme(), encoding="utf-8")
        manifest = {
            "schema": SCHEMA_VERSION,
            "source_namespace": SOURCE_NAMESPACE,
            "selected_seasons": sorted(set(args.seasons)),
            "builder_sha256": _sha256(Path(__file__)),
            "database": "identity.sqlite",
            "report": "identity-review.json",
            "source_files": report["counts"]["source_files"],
            "source_hashes": _source_hashes(db_path),
            "artifacts": {name: _sha256(staging / name)
                          for name in ("identity.sqlite", "identity-review.json", "README.md")},
            "data_policy": "source IDs and dated observations only; no name-only merge; no future data in cutoff queries",
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if final_dir.exists():
            raise FileExistsError(f"destination appeared during build; refusing to replace: {final_dir}")
        # Rename is atomic on the same volume and the destination must not exist.
        os.rename(staging, final_dir)
    print(json.dumps({"status": "complete", "output": str(final_dir), "summary": report["counts"],
                      "same_name_groups": len(report["identity_review"]["same_name_multiple_ids"]),
                      "alias_groups": len(report["identity_review"]["same_id_multiple_names"]),
                      "unresolved_identity_records": report["identity_review"]["unresolved_identity_observations"]["total"],
                      "invalid_measurements_preserved": report["measurement_review"]["invalid_nonempty_numeric_values"],
                      "event_participant_differences": report["event_participant_review"]["counts_by_role"],
                      "identity_resolution_complete": report["identity_resolution_complete"],
                      "model_ready": False}, ensure_ascii=False, indent=2))
    return report


@contextmanager
def _build_lock(final_dir):
    lock_path = final_dir.parent / ("." + final_dir.name + ".build.lock")
    marker = _json({"pid": os.getpid(), "token": os.urandom(16).hex()})
    try:
        stream = lock_path.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise FileExistsError(f"another build lock exists; inspect it before retrying: {lock_path}") from exc
    try:
        stream.write(marker)
        stream.flush()
        yield
    finally:
        stream.close()
        if lock_path.exists() and lock_path.read_text(encoding="utf-8") == marker:
            lock_path.unlink()


def _source_hashes(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        return [
            {"relative_path": row[0], "sha256": row[1]}
            for row in conn.execute(
                "SELECT relative_path,sha256 FROM source_files ORDER BY season,relative_path"
            ).fetchall()
        ]


def player_history(db_path, player_id, cutoff):
    cutoff_date = date.fromisoformat(cutoff).isoformat()
    if not isinstance(player_id, str) or not player_id or player_id != player_id.strip():
        raise ValueError("player ID must be a nonempty exact source ID or namespaced key")
    if player_id.startswith(SOURCE_NAMESPACE + ":"):
        player_key = player_id
    else:
        player_key = _player_key(player_id)
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        try:
            metadata = dict(conn.execute("SELECT key,value FROM metadata"))
        except sqlite3.DatabaseError as exc:
            raise ValueError("not an identity-continuity database") from exc
        if metadata.get("schema") != SCHEMA_VERSION or metadata.get("source_namespace") != SOURCE_NAMESPACE:
            raise ValueError(f"unsupported identity schema or source namespace: {metadata}")
        obs = conn.execute(
            "SELECT team_id,team_name,role,observed_name,MIN(observed_date) AS first_observed, "
            "MAX(observed_date) AS last_observed,COUNT(DISTINCT observed_date) AS observed_dates, "
            "COUNT(DISTINCT game_key) AS observed_games "
            "FROM player_observations WHERE player_key=? AND observed_date<=? "
            "GROUP BY team_id,team_name,role,observed_name "
            "ORDER BY MIN(observed_date),team_name,role,observed_name",
            (player_key, cutoff_date),
        ).fetchall()
        if not obs:
            # Unknown and future-only players have the same response. Even
            # existence beyond the cutoff must not be exposed to the caller.
            return {"schema": SCHEMA_VERSION, "found": False, "player_id": player_id, "as_of": cutoff_date,
                    "note": "No observation on or before this cutoff; later records were not used."}
        player = conn.execute("SELECT * FROM players WHERE player_key=?", (player_key,)).fetchone()
        pa_counts, pitch_counts = {}, {}
        for role in ("batter", "pitcher", "catcher"):
            pa_counts[role] = conn.execute(
                f"SELECT COUNT(*) FROM plate_appearances pa JOIN games g USING(game_key) "
                f"WHERE pa.{role}_player_key=? AND g.game_date<=?", (player_key, cutoff_date),
            ).fetchone()[0]
            pitch_counts[role] = conn.execute(
                f"SELECT COUNT(*) FROM pitch_events pe JOIN plate_appearances pa USING(pa_key) "
                f"JOIN games g USING(game_key) WHERE pe.{role}_player_key=? AND g.game_date<=?",
                (player_key, cutoff_date),
            ).fetchone()[0]
    names = sorted({row["observed_name"] for row in obs if row["observed_name"]})
    teams = sorted({row["team_name"] for row in obs})
    return {
        "schema": SCHEMA_VERSION,
        "found": True,
        "player_key": player["player_key"],
        "source_namespace": player["source_namespace"],
        "source_player_id": player["source_player_id"],
        "as_of": cutoff_date,
        "name_observations": [dict(row) for row in obs],
        "names_observed_by_cutoff": names,
        "teams_observed_by_cutoff": teams,
        "plate_appearances_by_cutoff": pa_counts,
        "pitch_events_by_cutoff": pitch_counts,
        "first_observed_on_or_before_cutoff": min(row["first_observed"] for row in obs),
        "last_observed_on_or_before_cutoff": max(row["last_observed"] for row in obs),
        "interpretation": "Observed records only; team observations are not verified transfer dates.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="build a new, non-overwriting SQLite identity store")
    build_parser.add_argument("--root", type=Path, default=ROOT / "data" / "rebas")
    build_parser.add_argument("--seasons", nargs="+", type=int, required=True)
    build_parser.add_argument("--out", type=Path, required=True)
    player_parser = commands.add_parser("player", help="read player identity/participation as of a date")
    player_parser.add_argument("--db", type=Path, required=True)
    player_parser.add_argument("--player-id", required=True, help="raw source playerId or full namespaced key")
    player_parser.add_argument("--as-of", required=True, help="inclusive cutoff date YYYY-MM-DD")
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    else:
        result = player_history(args.db, args.player_id, args.as_of)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
