"""Attach retrospective observations to the published 2026 dates in a staging directory."""
import argparse
import json
from pathlib import Path


def write_json(path, payload, *, newline="\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline=newline) as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def build(source, fielding, coverage, output):
    encoded_catalog = (source / "dates.json").read_bytes()
    catalog = json.loads(encoded_catalog)
    catalog["evidence_schema"] = 1
    for date in catalog["days"]:
        folder = "day-" + date["date"]
        index = json.loads((source / folder / "index.json").read_bytes())
        actual = set()
        for game, entries in index["games"].items():
            pas = json.loads((source / folder / f"{game}.json").read_bytes())["pas"]
            if [pa["pa_id"] for pa in pas] != entries:
                raise ValueError(f"Game index changed: {game}")
            actual.update(pa["pa_id"] for pa in pas if pa["is_ph"])
        played = {pa: fielding["decisions"][pa] for pa in sorted(actual)}
        audited = set(index["files"])
        if audited.intersection(fielding["decisions"]) != actual:
            raise ValueError(f"Pinch-hit labels disagree: {date['date']}")
        availability = {pa: coverage["reasons"][pa] for pa in sorted(audited & coverage["reasons"].keys())}
        payload = {
            "schema_version": 1, "date": date["date"], "batch_id": index["batch_id"],
            "fielding": played, "availability": availability,
        }
        write_json(output / folder / "evidence.json", payload)
        if date["date"] == "2026-07-29":
            date.pop("observed_case", None)
            pa = next((pa for pa, row in played.items() if row["status"] == "pinch_hitter_fielded"), None)
            if pa:
                date["observed_case"] = {
                    "label": "代打後實際接守", "game": pa.rsplit("-", 1)[0], "pa": pa, "decision": "ph",
                }
    write_json(output / "dates.json", catalog, newline="\r\n" if b"\r\n" in encoded_catalog else "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("source", "fielding", "coverage", "out"):
        parser.add_argument("--" + arg, type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Choose a new staging directory")
    build(args.source, json.loads(args.fielding.read_bytes()), json.loads(args.coverage.read_bytes()), args.out)


if __name__ == "__main__":
    main()
