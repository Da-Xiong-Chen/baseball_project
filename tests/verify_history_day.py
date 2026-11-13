import os
"""Recompute all fixed-day snapshots; independently compare markers with model decisions."""
from pathlib import Path
import json
import sys
import math
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
import server
from batch_contract import metadata as batch_metadata
from load import load
from runtime_config import settings


def main():
    data_root = Path(os.environ.get("BASEBALL_STATIC_OUT",ROOT/"docs/data"))
    root = data_root / "replay" / ('day-'+settings().history_date)
    index = json.loads((root / "index.json").read_text(encoding="utf8"))
    fixed_snapshot = 'schedule' in index
    timing_path = root/'timing.json' if fixed_snapshot else data_root/f'timing-{settings().season}.json'
    timing = json.loads(timing_path.read_text(encoding="utf8"))
    max_error, results, marks = 0.0, 0, 0
    mismatches = []
    for n, (pid, filename) in enumerate(index["files"].items(), 1):
        bundle = json.loads((root / filename).read_text(encoding="utf8"))
        for decision in ("ph", "pen"):
            expected = server.replay_result(pid, decision)
            actual = bundle[decision] or bundle["ph"]
            assert expected["situation"]["pitcher"] == actual["situation"]["pitcher"], pid
            for field, key in (("candidates", "球員"), ("bullpen", "投手")):
                a = actual[field] if field == "candidates" else actual[field]["rows"]
                b = expected[field] if field == "candidates" else expected[field]["rows"]
                assert [r[key] for r in a] == [r[key] for r in b], (pid, decision, field)
                for x, y in zip(a, b):
                    for metric in ("相對現任", "守方勝率增減", "預估失分", "預估勝率", "疲勞調整"):
                        if y.get(metric) is not None:
                            error = abs(x[metric] - y[metric]);max_error = max(max_error, error)
                            assert math.isfinite(x[metric]) and error <= 1e-8+1e-7*abs(y[metric]), (pid, metric, error)
            marker = timing["games"].get("-".join(pid.split("-")[:2]), {}).get(pid)
            if marker:
                rows = [r for r in expected["bullpen"]["rows"] if r["角色"] == "牛棚"] if decision == "pen" else [r for r in expected["candidates"] if r["角色"] == "代打" and r["守備"] in ("ok", "warn")]
                value = rows[0]["守方勝率增減" if decision == "pen" else "相對現任"] if rows else None
                offset = 0 if decision == "pen" else 3
                stored = marker[offset]
                limit = 1e-9 if fixed_snapshot else .011
                mismatch = (value is None) != (stored is None)
                if value is not None and stored is not None:
                    mismatch |= abs(value - stored) > limit
                    if fixed_snapshot:
                        candidate = rows[0]['投手' if decision == 'pen' else '球員']
                        threshold = timing['threshold']
                        mismatch |= candidate != marker[offset+1] or (value >= threshold) != (stored >= threshold)
                if mismatch:
                    mismatches.append(dict(pa=pid, decision=decision, computed=value, marker=stored))
                marks += 1
            results += 1
        if n % 30 == 0: print(f"Verified {n}/{index['pa_count']}", flush=True)
    report = dict(pa_count=index["pa_count"], evaluated_views=results, max_numeric_error=max_error,
                  timing_views_checked=marks, timing_mismatches=mismatches,
                  model_cutoff=index["model_cutoff"], ml_cutoff=index["ml_cutoff"])
    out = Path(os.environ.get("BASEBALL_REPORT_OUT",ROOT/"output/closeout")) / "history-day-parity.json";out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    assert not mismatches, "回放與時機標記不一致，請檢查報告"
    receipt=Path(os.environ.get('BASEBALL_REPORT_OUT',ROOT/'output/closeout'))/'history_day-receipt.json'
    receipt.parent.mkdir(parents=True,exist_ok=True)
    receipt.write_text(json.dumps(dict(report,passed=True,**batch_metadata()),ensure_ascii=False,indent=2),encoding='utf8')


if __name__ == "__main__": main()
