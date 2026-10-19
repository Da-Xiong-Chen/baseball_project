"""Export the fixed day's complete PA decisions, loaded one at a time by the website.

No ML training: a compatible pre-existing month-start model is required.
Run: python scripts/export_history_day.py
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
import server
import mlmodel
from engine import matchup_detail
from export_static import rnd
from load import load

DATE = "2025-09-20"
OUT = ROOT / "docs" / "data" / "replay" / ("day-" + DATE)


def details(result, model):
    pitcher = result["situation"]["pitcher"]
    pairs = {(r["球員"], pitcher) for r in result["candidates"]}
    if result["bullpen"]["next"]:
        pairs.update((result["bullpen"]["next"][0], r["投手"]) for r in result["bullpen"]["rows"])
    result["details"] = {f"{b}|{p}": matchup_detail(model, b, p) for b, p in sorted(pairs)}
    return result


def export():
    month = DATE[:7] + "-01"
    if not Path(mlmodel.path_for(month)).is_file():
        raise RuntimeError("缺少既有月初模型；本匯出不會自動訓練")
    pa, _, _ = load()
    day = pa[pa["date"].dt.strftime("%Y-%m-%d") == DATE].sort_values(["game", "inning", "half", "seq"])
    games = list(dict.fromkeys(day["game"]))
    teams = set(day["bat_team"]) | set(day["fld_team"])
    if len(games) != 3 or len(teams) != 6:
        raise ValueError("固定日必須包含六隊三場")
    OUT.mkdir(parents=True, exist_ok=True)
    model = server.model_for(DATE)
    index = dict(schema_version=1, date=DATE, model_cutoff=DATE, ml_cutoff=month,
                 games={g: [] for g in games}, files={}, sha256={}, pitcher_changes=0)
    total = 0
    for number, pid in enumerate(day["pa_id"], 1):
        ph = details(server.replay_result(pid, "ph"), model)
        changed = ph["replay_context"]["pitcher_changed"]
        pen = details(server.replay_result(pid, "pen"), model) if changed else None
        for result in [ph, pen]:
            if result is not None and not (result["ml_cutoff"] <= result["model_cutoff"] <= DATE):
                raise ValueError(f"時間界線無效：{pid}")
        payload = dict(schema_version=1, date=DATE, pa_id=pid, ph=ph, pen=pen)
        raw = json.dumps(rnd(server.clean(payload)), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf8")
        filename = pid + ".json"
        (OUT / filename).write_bytes(raw)
        index["files"][pid] = filename
        index["sha256"][pid] = hashlib.sha256(raw).hexdigest()
        index["games"]["-".join(pid.split("-")[:2])].append(pid)
        index["pitcher_changes"] += int(changed)
        total += len(raw)
        if number % 20 == 0:
            print(f"Exported {number}/{len(day)}", flush=True)
    index.update(pa_count=len(day), bytes=total)
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"pa_count": len(day), "games": len(games), "pitcher_changes": index["pitcher_changes"], "bytes": total}), flush=True)


if __name__ == "__main__":
    export()
