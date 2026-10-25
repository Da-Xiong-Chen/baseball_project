"""Independently reconcile an identity store with every selected raw Rebas game.

Checks source/artifact hashes, all relational rows and per-event identities,
dated alias/team reports, historical query boundaries, and optional rebuild.
The expected data is reconstructed from raw JSON, not from the builder report.
"""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, timedelta
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sqlite3
import time


ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "rebas:CPBL"
SCHEMA = "baseball.identity-continuity.v2"
ROLES = ("batter", "pitcher", "catcher")


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def read_json(path):
    def reject(value):
        raise ValueError("nonfinite JSON constant " + value)
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class Checks:
    def __init__(self):
        self.comparisons = Counter()
        self.failures = []
        self.failure_count = 0

    def equal(self, category, actual, expected, where=""):
        self.comparisons[category] += 1
        if actual != expected:
            self.failure_count += 1
            if len(self.failures) < 100:
                # Full raw rows can be very large; preserve enough to locate
                # a discrepancy without duplicating the source corpus.
                self.failures.append({"check": category, "where": where,
                                      "actual": repr(actual)[:1000], "expected": repr(expected)[:1000]})


def player_key(raw_id):
    return NAMESPACE + ":" + raw_id if isinstance(raw_id, str) and raw_id and raw_id == raw_id.strip() else None


def resolve(raw_game, side, role, name):
    if not isinstance(name, str) or not name:
        return None
    suffixes = ("BatterBox",) if role == "batter" else (("PitcherBox",) if role == "pitcher" else ("BatterBox", "PitcherBox"))
    matches = {player_key(row.get("playerId")) for suffix in suffixes
               for row in raw_game[side + suffix] if row.get("playerName") == name}
    return next(iter(matches)) if len(matches) == 1 and None not in matches else None


def measurement(value):
    if value is None or value == "":
        return None, None
    if isinstance(value, bool):
        return None, "boolean_not_numeric"
    try:
        numeric = float(value)
    except (ValueError, TypeError, OverflowError):
        return None, "not_numeric"
    return (numeric, None) if math.isfinite(numeric) else (None, "non_finite")


def _load_query_function():
    spec = importlib.util.spec_from_file_location("identity_query_under_verification", ROOT / "scripts/build_identity_continuity.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.player_history


def _expected_history(observations, stats, key, cutoff):
    before = [row for row in observations[key] if row["date"] <= cutoff]
    if not before:
        return {"found": False}
    groups = defaultdict(list)
    for row in before:
        groups[(row["team_id"], row["team_name"], row["role"], row["name"])].append(row)
    history = []
    for (tid, team, role, name), rows in groups.items():
        days = {row["date"] for row in rows}
        history.append({"team_id": tid, "team_name": team, "role": role, "observed_name": name,
                        "first_observed": min(days), "last_observed": max(days), "observed_dates": len(days),
                        "observed_games": len({row["game"] for row in rows})})
    history.sort(key=lambda row: (row["first_observed"], row["team_name"], row["role"], row["observed_name"] or ""))
    counts = {kind: {role: sum(count for (day, actor_role), count in stats[kind][key].items()
                             if day <= cutoff and actor_role == role) for role in ROLES}
              for kind in ("pa", "pitch")}
    return {"found": True, "player_key": key, "source_namespace": NAMESPACE,
            "source_player_id": key[len(NAMESPACE) + 1:], "as_of": cutoff,
            "name_observations": history,
            "names_observed_by_cutoff": sorted({row["name"] for row in before if row["name"]}),
            "teams_observed_by_cutoff": sorted({row["team_name"] for row in before}),
            "first_observed_on_or_before_cutoff": min(row["date"] for row in before),
            "last_observed_on_or_before_cutoff": max(row["date"] for row in before),
            "plate_appearances_by_cutoff": counts["pa"], "pitch_events_by_cutoff": counts["pitch"]}


def verify(source_root, artifact_dir, rebuild_dir=None, intake_path=None):
    started = time.monotonic()
    source_root, artifact_dir = Path(source_root).resolve(), Path(artifact_dir).resolve()
    checks = Checks()
    manifest = read_json(artifact_dir / "manifest.json")
    report = read_json(artifact_dir / "identity-review.json")
    checks.equal("schema", manifest["schema"], SCHEMA)
    checks.equal("schema", report["schema"], SCHEMA)
    checks.equal("builder_hash", manifest.get("builder_sha256"), digest(ROOT / "scripts/build_identity_continuity.py"))
    checks.equal("namespace", manifest["source_namespace"], NAMESPACE)
    primary_hashes = {name: digest(artifact_dir / name) for name in ("identity.sqlite", "identity-review.json", "README.md")}
    checks.equal("artifact_hashes", manifest.get("artifacts"), primary_hashes)
    seasons = manifest["selected_seasons"]
    selected_files = sorted(path.relative_to(source_root).as_posix()
                            for year in seasons for path in (source_root / str(year)).glob("*.json"))
    manifest_files = {row["relative_path"]: row["sha256"] for row in manifest["source_hashes"]}
    checks.equal("manifest_file_uniqueness", len(manifest_files), len(manifest["source_hashes"]))
    checks.equal("source_file_selection", sorted(manifest_files), selected_files)
    if intake_path:
        prior = read_json(intake_path)
        checks.equal("prior_intake_hashes", manifest_files,
                     {row["file"]: row["sha256"] for row in prior["source_manifest"]})

    counts = Counter()
    by_season = defaultdict(Counter)
    observations = defaultdict(list)
    stats = {"pa": defaultdict(Counter), "pitch": defaultdict(Counter)}
    name_ids, id_names, id_teams, id_seasons = defaultdict(set), defaultdict(lambda: defaultdict(list)), defaultdict(lambda: defaultdict(dict)), defaultdict(set)
    event_differences, invalid_values = [], []
    unresolved = 0
    with closing(sqlite3.connect((artifact_dir / "identity.sqlite").as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        checks.equal("sqlite_integrity", conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        checks.equal("foreign_keys", list(conn.execute("PRAGMA foreign_key_check")), [])
        checks.equal("metadata", dict(conn.execute("SELECT key,value FROM metadata")), {"schema": SCHEMA, "source_namespace": NAMESPACE})
        checks.equal("database_source_manifest", {row[0]: row[1] for row in conn.execute("SELECT relative_path,sha256 FROM source_files")}, manifest_files)
        for relative in selected_files:
            path = (source_root / relative).resolve()
            if source_root not in path.parents:
                raise ValueError("source path escaped source root")
            checks.equal("raw_source_hash", digest(path), manifest_files.get(relative), relative)
            raw = read_json(path)
            year = int(relative.split("/")[0])
            day = raw["date"][:10]
            game = f"{NAMESPACE}:{year}-{raw['seq']:03d}"
            counts["games"] += 1
            by_season[year]["games"] += 1
            game_row = conn.execute("SELECT g.*,s.relative_path FROM games g JOIN source_files s USING(source_file_id) WHERE game_key=?", (game,)).fetchone()
            expected_game = {"game_key": game, "source_namespace": NAMESPACE, "relative_path": relative,
                             "season": year, "sequence": raw["seq"], "game_date": day, "stadium": raw.get("stadium"),
                             "away_team_name": raw["awayTeam"], "home_team_name": raw["homeTeam"],
                             "away_team_id": str(raw["awayTeamId"]) if raw.get("awayTeamId") not in (None, "") else None,
                             "home_team_id": str(raw["homeTeamId"]) if raw.get("homeTeamId") not in (None, "") else None,
                             "away_score_raw_json": canonical(raw.get("awayScores")), "home_score_raw_json": canonical(raw.get("homeScores"))}
            checks.equal("game_rows", {k: game_row[k] for k in expected_game} if game_row else None, expected_game, game)
            expected_boxes = []
            expected_pas = {}
            expected_pitches = {}
            for side in ("away", "home"):
                other = "home" if side == "away" else "away"
                for suffix, role in (("BatterBox", "batter_box"), ("PitcherBox", "pitcher_box")):
                    for box in raw[side + suffix]:
                        key = player_key(box.get("playerId"))
                        name = box.get("playerName")
                        tid = str(raw[side + "TeamId"]) if raw.get(side + "TeamId") not in (None, "") else None
                        team = raw[side + "Team"]
                        expected_boxes.append({"player_key": key, "source_player_id_raw_json": canonical(box.get("playerId")),
                                               "game_key": game, "observed_date": day, "team_id": tid, "team_name": team,
                                               "role": role, "observed_name": name,
                                               "jersey_number": str(box["playerNumber"]) if box.get("playerNumber") is not None else None,
                                               "lineup_order": box.get("order"), "stats_raw_json": canonical(box)})
                        counts["player_box_observations"] += 1
                        if key:
                            observations[key].append(dict(date=day, game=game, team_id=tid, team_name=team, role=role, name=name))
                            id_seasons[key].add(year)
                            id_teams[key][team][game] = day
                            if name:
                                name_ids[name].add(key)
                                id_names[key][name].append((day, team))
                        else:
                            unresolved += 1
                for index, pa in enumerate(raw[side + "PAList"]):
                    pa_key = f"{game}:{side[0]}{index:03d}"
                    keys = {role: resolve(raw, side if role == "batter" else other, role, pa.get(role + "Name")) for role in ROLES}
                    unresolved += sum(key is None for key in keys.values())
                    expected_pas[pa_key] = dict(pa_key=pa_key, game_key=game, batting_side=side, pa_index=index,
                                               inning=pa.get("inning"), outs_before=pa.get("outs"), bases_before=pa.get("bases"),
                                               batter_name=pa.get("batterName"), batter_hand=pa.get("batterHand"), batter_player_key=keys["batter"],
                                               pitcher_name=pa.get("pitcherName"), pitcher_hand=pa.get("pitcherHand"), pitcher_player_key=keys["pitcher"],
                                               catcher_name=pa.get("catcherName"), catcher_player_key=keys["catcher"],
                                               result=pa.get("result", pa.get("results")), is_pinch_hitter=int(pa["isPH"]) if isinstance(pa.get("isPH"), bool) else None,
                                               raw_json=canonical(pa))
                    counts["plate_appearances"] += 1
                    by_season[year]["plate_appearances"] += 1
                    for role, key in keys.items():
                        if key: stats["pa"][key][(day, role)] += 1
                    pitch_index = 0
                    for event_index, event in enumerate(pa["events"]):
                        if event["type"] != "PITCH": continue
                        pitch_key = f"{pa_key}:p{pitch_index:03d}"
                        expected = {"pitch_key": pitch_key, "pa_key": pa_key, "pitch_index": pitch_index, "event_index": event_index,
                                    "pitch_code": event.get("pitchCode"), "pitch_type": event.get("pitchType"), "raw_event_json": canonical(event)}
                        for role in ROLES:
                            field = role + "Name"
                            name = event[field] if field in event else pa.get(field)
                            key = resolve(raw, side if role == "batter" else other, role, name)
                            expected.update({role + "_name": name, role + "_player_key": key,
                                             role + "_identity_basis": "event_name" if field in event else "parent_pa_field_absent"})
                            if key: stats["pitch"][key][(day, role)] += 1
                            else: unresolved += 1
                            if field in event and name != pa.get(field):
                                event_differences.append(dict(game_key=game, date=day, side=side, pa_index=index, event_index=event_index,
                                                              role=role, pa_name=pa.get(field), event_name=name, event_player_key=key))
                        invalid = {}
                        for column, field in (("coord_x", "coordX"), ("coord_y", "coordY"), ("velocity", "velocity")):
                            value, issue = measurement(event.get(field))
                            expected.update({column + "_present": int(field in event), column + "_raw_json": canonical(event.get(field)),
                                             column + "_value": value})
                            if issue:
                                invalid[column] = issue
                                invalid_values.append(dict(game_key=game, date=day, side=side, pa_index=index, event_index=event_index,
                                                           measurement=column, raw_json=canonical(event.get(field)), reason=issue))
                        expected["invalid_measurements_json"] = canonical(invalid)
                        expected_pitches[pitch_key] = expected
                        pitch_index += 1
                        counts["pitch_events"] += 1
                        by_season[year]["pitch_events"] += 1
            actual_boxes = [dict(row) for row in conn.execute("SELECT * FROM player_observations WHERE game_key=?", (game,))]
            for row in actual_boxes: row.pop("observation_id")
            checks.equal("box_observation_rows", sorted(map(canonical, actual_boxes)), sorted(map(canonical, expected_boxes)), game)
            actual_pas = {row["pa_key"]: dict(row) for row in conn.execute("SELECT * FROM plate_appearances WHERE game_key=?", (game,))}
            checks.equal("pa_keys", sorted(actual_pas), sorted(expected_pas), game)
            for key, expected in expected_pas.items(): checks.equal("pa_rows", actual_pas.get(key), expected, key)
            actual_pitches = {row["pitch_key"]: dict(row) for row in conn.execute("SELECT pe.* FROM pitch_events pe JOIN plate_appearances pa USING(pa_key) WHERE pa.game_key=?", (game,))}
            checks.equal("pitch_keys", sorted(actual_pitches), sorted(expected_pitches), game)
            for key, expected in expected_pitches.items(): checks.equal("pitch_rows", actual_pitches.get(key), expected, key)

        expected_players = {key: (NAMESPACE, key[len(NAMESPACE) + 1:]) for key in observations}
        checks.equal("player_registry", {row[0]: (row[1], row[2]) for row in conn.execute("SELECT * FROM players")}, expected_players)
        checks.equal("unresolved_count", conn.execute("SELECT COUNT(*) FROM identity_resolution_issues").fetchone()[0], unresolved)
        for table, count in (("games", counts["games"]), ("source_files", len(selected_files)),
                             ("player_observations", counts["player_box_observations"]),
                             ("plate_appearances", counts["plate_appearances"]), ("pitch_events", counts["pitch_events"])):
            checks.equal("total_table_rows", conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], count, table)

    aliases = {key: [{"name": name, "first_observed": min(day for day, _ in rows),
                      "last_observed": max(day for day, _ in rows), "teams_observed": sorted({team for _, team in rows})}
                     for name, rows in sorted(names.items(), key=lambda item: (min(day for day, _ in item[1]), item[0]))]
               for key, names in sorted(id_names.items()) if len(names) > 1}
    collisions = {name: sorted(keys) for name, keys in sorted(name_ids.items()) if len(keys) > 1}
    cross_year = [{"player_key": key, "source_player_id": key[len(NAMESPACE) + 1:], "seasons_observed": sorted(years)}
                  for key, years in sorted(id_seasons.items()) if len(years) > 1]
    cross_team = [{"player_key": key,
                   "observed_teams": [{"team_name": team, "first_observed": min(games.values()), "last_observed": max(games.values()),
                                        "observed_games": len(games)} for team, games in sorted(teams.items())],
                   "interpretation": "observations only; not a verified transaction or roster interval"}
                  for key, teams in sorted(id_teams.items()) if len(teams) > 1]
    expected_counts = dict(counts, source_files=len(selected_files), players=len(observations))
    checks.equal("report_counts", report["counts"], expected_counts)
    checks.equal("report_aliases", report["identity_review"]["same_id_multiple_names"], aliases)
    checks.equal("report_collisions", report["identity_review"]["same_name_multiple_ids"], collisions)
    checks.equal("report_cross_year", report["identity_review"]["players_observed_in_multiple_seasons"], cross_year)
    checks.equal("report_cross_team", report["identity_review"]["players_observed_with_multiple_team_names"], cross_team)
    checks.equal("report_unresolved", report["identity_review"]["unresolved_identity_observations"]["total"], unresolved)
    checks.equal("report_measurements", sorted(map(canonical, report["measurement_review"]["items"])), sorted(map(canonical, invalid_values)))
    checks.equal("report_event_participants", sorted(map(canonical, report["event_participant_review"]["items"])), sorted(map(canonical, event_differences)))
    checks.equal("identity_gate", report["identity_resolution_complete"], unresolved == 0)
    checks.equal("measurement_gate", report["strict_measurement_gate_passed"], not invalid_values)
    checks.equal("model_gate", report["model_ready"], False)

    query = _load_query_function()
    query_cases = 0
    max_day = max(row["date"] for rows in observations.values() for row in rows)
    for key, rows in sorted(observations.items()):
        boundaries = {min(row["date"] for row in rows), max_day, "2024-12-31"}
        boundaries.update(min(day for day, _ in samples) for samples in id_names[key].values())
        boundaries.update(min(games.values()) for games in id_teams[key].values())
        cutoffs = boundaries | {(date.fromisoformat(day) - timedelta(days=1)).isoformat() for day in boundaries}
        for cutoff in sorted(cutoffs):
            expected = _expected_history(observations, stats, key, cutoff)
            actual = query(artifact_dir / "identity.sqlite", key, cutoff)
            checks.equal("cutoff_query", {field: actual.get(field) for field in expected}, expected, key + "@" + cutoff)
            if not expected["found"]:
                checks.equal("no_future_fields", sorted(actual), ["as_of", "found", "note", "player_id", "schema"], key + "@" + cutoff)
            query_cases += 1
    checks.equal("readonly_database_hash", digest(artifact_dir / "identity.sqlite"), primary_hashes["identity.sqlite"])
    rebuild_hashes = None
    if rebuild_dir:
        rebuild_dir = Path(rebuild_dir)
        rebuild_hashes = {name: digest(rebuild_dir / name) for name in (*primary_hashes, "manifest.json")}
        checks.equal("deterministic_full_rebuild", rebuild_hashes,
                     {**primary_hashes, "manifest.json": digest(artifact_dir / "manifest.json")})
    return {
        "schema": "baseball.identity-continuity-verification.v2",
        "passed": checks.failure_count == 0,
        "failure_count": checks.failure_count,
        "failures_capped_at_100": checks.failures,
        "comparisons": dict(sorted(checks.comparisons.items())),
        "counts_reconstructed_from_raw": expected_counts,
        "counts_by_season": {str(year): dict(values) for year, values in sorted(by_season.items())},
        "players_queried": len(observations), "cutoff_query_cases": query_cases,
        "same_name_groups": len(collisions), "alias_groups": len(aliases),
        "cross_year_identities": len(cross_year), "multiple_team_observation_identities": len(cross_team),
        "event_participant_differences": dict(Counter(row["role"] for row in event_differences)),
        "unresolved_identity_observations": unresolved,
        "raw_invalid_numeric_measurements_preserved": len(invalid_values),
        "strict_measurement_gate_passed": not invalid_values, "model_ready": False,
        "artifact_hashes": primary_hashes,
        "full_rebuild_compared": rebuild_dir is not None,
        "verifier_sha256": digest(Path(__file__)),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "data/rebas")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--rebuild", type=Path)
    parser.add_argument("--intake", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists(): raise FileExistsError(f"verification output already exists: {args.out}")
    result = verify(args.root, args.artifacts, args.rebuild, args.intake)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: value for key, value in result.items() if key not in ("artifact_hashes", "comparisons")}, ensure_ascii=True, indent=2))
    if not result["passed"]: raise SystemExit(1)


if __name__ == "__main__":
    main()
