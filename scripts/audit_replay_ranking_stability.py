"""Measure how dated published candidate rankings change under component ablation."""
import argparse
from collections import defaultdict, Counter
import json
import math
from pathlib import Path


def audit(source):
    groups = defaultdict(Counter)
    for index_file in sorted(source.glob("day-*/index.json")):
        index = json.loads(index_file.read_bytes())
        for name in index["files"].values():
            bundle = json.loads((index_file.parent / name).read_bytes())
            for kind in ("ph", "pen"):
                result = bundle.get(kind) or bundle.get("ph")
                if not result:
                    continue
                pitching = kind == "pen"
                who = "投手" if pitching else "球員"
                gain = "守方勝率增減" if pitching else "相對現任"
                rows = result["bullpen"]["rows"] if pitching else result["candidates"]
                incumbent, *bench = rows
                candidates = [row for row in bench if pitching or row["守備"] in {"ok", "warn"}]
                variants = ("hierarchical", "tree", "without_fatigue") if pitching else (
                    "hierarchical", "tree", "without_platoon",
                )
                if not candidates or any(not isinstance(row["機器學習"], (int, float)) for row in [incumbent, *candidates]):
                    continue
                situation = result["situation"]
                segment = ["all"]
                if situation["inning"] >= 8 and abs(situation["bat_score"] - situation["fld_score"]) <= 1:
                    segment.append("late_close")
                if min(incumbent["樣本球數"], candidates[0]["樣本球數"]) < 500:
                    segment.append("incumbent_or_top_has_fewer_than_500_pitches")
                slope = result["leverage"]

                def values(row):
                    if pitching:
                        return (-row["階層式"] - row["疲勞調整"], -row["機器學習"] - row["疲勞調整"],
                                -row["預估失分"] + row["疲勞調整"])
                    return row["階層式"], row["機器學習"], row["每打席得分值"] - 0.5 * row["左右優勢"]

                current = values(incumbent)
                computed = [(row, values(row)) for row in candidates]
                for i, variant in enumerate(variants):
                    best, components = max(computed, key=lambda item: round(item[1][i] * (1 if pitching else slope), 12))
                    adjusted_gain = (components[i] - current[i]) * slope
                    if not math.isfinite(adjusted_gain):
                        raise ValueError("Non-finite replay score")
                    for label in segment:
                        g = groups[f"{kind}:{label}:{variant}"]
                        g["n"] += 1
                        g["top_changed"] += best[who] != candidates[0][who]
                        g["prompt_changed"] += (adjusted_gain >= 1) != (candidates[0][gain] >= 1)
                        g["has_two_candidates"] += len(candidates) >= 2
                        g["top_two_within_0_25_pp"] += len(candidates) >= 2 and abs(candidates[0][gain] - candidates[1][gain]) <= 0.25
    if not groups:
        raise ValueError("No dated candidate comparisons found")
    return {
        "groups": groups, "threshold_pp": 1,
        "scope": "Archived date-specific scores, same eligible candidate pool in every calculation. "
                 "Ranking and threshold sensitivity only, not observed predictive error or a causal effect. "
                 "Removing platoon subtracts the current 50% hierarchical component from the fixed blend.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(audit(args.source), stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    main()
