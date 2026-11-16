"""Measure the evidence available for observed fielding after a pinch hitter enters."""

import argparse
from collections import Counter
import json
from pathlib import Path


POSITIONS = ("P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")


def opening_fielders(pa):
    names = pa.get("fielderNames")
    if not isinstance(names, list) or len(names) != len(POSITIONS):
        return None
    if not all(isinstance(name, str) and name.strip() for name in names):
        return None
    if len(set(names)) != len(POSITIONS) or names[1] != pa.get("catcherName"):
        return None
    return dict(zip(names, POSITIONS))


def observed_fielding(pa, next_half, player_ids, previous_half=(), outgoing=None):
    name = pa.get("batterName")
    pitch_batters = {event.get("batterName", name) for event in pa["events"] if event.get("type") == "PITCH"}
    if not name or len(player_ids.get(name, ())) != 1 or pitch_batters != {name}:
        return {"status": "unconfirmed"}
    if not next_half:
        return {"status": "no_defensive_half"}
    for pa_id, snapshot in next_half:
        lineup = opening_fielders(snapshot)
        if lineup and name in lineup:
            return {"status": "pinch_hitter_fielded", "position": lineup[name], "observed_pa": pa_id}
    first_id, first_pa = next_half[0]
    lineup = opening_fielders(first_pa)
    if lineup:
        result = {"status": "other_player_fielded", "observed_pa": first_id}
        previous = opening_fielders(previous_half[-1][1]) if previous_half else None
        position = previous.get(outgoing) if previous and len(player_ids.get(outgoing, ())) == 1 else None
        if position and position != "P":
            occupant = next(player for player, pos in lineup.items() if pos == position)
            if occupant != outgoing and len(player_ids.get(occupant, ())) == 1:
                result.update(original_position=position, opening_fielder=occupant)
        return result
    return {"status": "unconfirmed"}


def audit(source):
    totals, positions, within_inning, classifications = Counter(), Counter(), Counter(), Counter()
    examples = {}
    decisions = {}
    for path in sorted(source.glob("*.json")):
        game = json.loads(path.read_text(encoding="utf-8"))
        game_id = f"{game['date'][:4]}-{game['seq']:03d}"
        totals["games"] += 1
        for offense, defense, next_inning in (("away", "home", 0), ("home", "away", 1)):
            attack = game[f"{offense}PAList"]
            opponent = game[f"{defense}PAList"]
            by_inning = {}
            for i, pa in enumerate(opponent):
                by_inning.setdefault(pa["inning"], []).append((f"{game_id}-{defense[0]}{i:03d}", pa))
            ids_by_name = {}
            batting_slots = {}
            for row in game[f"{offense}BatterBox"] + game[f"{offense}PitcherBox"]:
                ids_by_name.setdefault(row["playerName"], set()).add(row["playerId"])
            for row in game[f"{offense}BatterBox"]:
                batting_slots.setdefault(row["order"], row["playerName"])

            for i, pa in enumerate(attack):
                totals["pa_records"] += 1
                totals["complete_opening_fielding"] += opening_fielders(pa) is not None
                totals["event_fielding_arrays"] += sum(
                    isinstance(event.get("fielderNames"), list) for event in pa["events"]
                )
                outgoing = batting_slots.get(pa["paOrder"])
                batting_slots[pa["paOrder"]] = pa.get("batterName")
                if not pa.get("isPH"):
                    continue
                totals["pinch_hit_records"] += 1
                next_half = by_inning.get(pa["inning"] + next_inning, [])
                previous_half = by_inning.get(pa["inning"] + next_inning - 1, [])
                result = observed_fielding(pa, next_half, ids_by_name, previous_half, outgoing)
                classifications[result["status"]] += 1
                decisions[f"{game_id}-{offense[0]}{i:03d}"] = result
                name = pa.get("batterName")
                if not name or len(ids_by_name.get(name, set())) != 1:
                    totals["ambiguous_identity"] += 1
                    continue
                pitch_batters = {event.get("batterName") for event in pa["events"] if event.get("type") == "PITCH"}
                if pitch_batters != {name}:
                    totals["uncertain_pinch_hit_actor"] += 1
                    continue
                if not next_half:
                    totals["no_following_defensive_half"] += 1
                    continue
                lineup = opening_fielders(next_half[0][1])
                if lineup is None:
                    totals["incomplete_opening_snapshot"] += 1
                    continue
                position = lineup.get(name)
                if position is None:
                    totals["not_observed_in_opening_nine"] += 1
                else:
                    totals["observed_in_opening_nine"] += 1
                    positions[position] += 1
                    examples.setdefault(position, {"game": path.stem, "batting_side": offense, "pa_index": i})
                for _, later_pa in next_half:
                    later = opening_fielders(later_pa)
                    if later and name in later:
                        within_inning[later[name]] += 1
                        break
    if totals["games"] == 0:
        raise ValueError(f"No game records in {source}")
    return {
        "totals": dict(totals),
        "opening_positions": dict(positions),
        "first_observed_position_in_following_half": dict(within_inning),
        "examples": examples,
        "classifications": dict(classifications),
        "decisions": decisions,
        "scope": "Observed following defensive half only. Absence from the field is not DH status or ineligibility.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
