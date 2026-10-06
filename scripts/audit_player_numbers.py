"""Independently check published aliases against every 2025 box-score row."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def audit(root=ROOT):
    aliases = json.loads((root / "docs/data/player-numbers-2025.json").read_text(encoding="utf-8"))
    model = json.loads((root / "docs/data/model.json").read_text(encoding="utf-8"))
    assert aliases["season"] == 2025, "Wrong alias season"
    files = sorted((root / "data/rebas/2025").glob("*.json"))
    assert files, "Download the 2025 Rebas source before running the audit"
    assert len(files) == aliases["games"], "Incomplete source season"
    records = 0
    errors = []
    for path in files:
        game = json.loads(path.read_text(encoding="utf-8"))
        assert str(game["date"]).startswith("2025-"), "Wrong game season"
        for side in ("home", "away"):
            team = game[side + "Team"]
            for kind in ("Batter", "Pitcher"):
                for player in game[side + kind + "Box"]:
                    records += 1
                    if aliases["teams"].get(team, {}).get(player["playerName"]) != player["playerNumber"]:
                        errors.append({"game": path.name, "team": team, "name": player["playerName"]})
    roster_rows = 0
    missing = []
    for team, roster in model["rosters"].items():
        for kind in ("hitters", "pitchers"):
            for player in roster[kind]:
                roster_rows += 1
                if player["name"] not in aliases["teams"].get(team, {}):
                    missing.append({"team": team, "kind": kind, "name": player["name"]})
    report = {"season": 2025, "games": len(files), "source_records": records,
              "roster_rows": roster_rows, "mismatches": errors, "missing_roster_numbers": missing}
    assert not errors and not missing, report
    return report


if __name__ == "__main__":
    report = audit()
    target = ROOT / "docs/qa/player-numbers-source-audit.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {report['source_records']} source records and {report['roster_rows']} roster entries")
