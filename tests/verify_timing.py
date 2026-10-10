"""核對 docs/data/timing-2025.json 與網站「歷史回放」的計算一致（抽樣，不需啟動伺服器）。

抽沒有實際換投的打席（此時回放的場上投手就是續投者），比較最佳代打／最佳牛棚的人選與勝率差值。
用法：python tests/verify_timing.py [抽樣數，預設 12]
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
import server
import mlmodel
from engine import situation


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    data = json.loads((ROOT / "docs/data/timing-2025.json").read_text(encoding="utf8"))
    pa, _, _ = server.load()
    pitcher = dict(zip(pa["pa_id"], pa["pitcher"]))
    date = dict(zip(pa["pa_id"], pa["date"]))
    pool = [(pid, v) for g in data["games"].values() for pid, v in g.items() if v[2] == pitcher[pid] and v[0] is not None and v[3] is not None]
    random.Random(0).shuffle(pool)
    fails = 0
    for pid, (pen_gain, pen_best, inc, ph_gain, ph_best, due, *_) in pool[:n]:
        d = str(date[pid].date())
        r = server.build_result(situation(pid), server.model_for(d), mlmodel.for_date(d))
        ph = [c for c in r["candidates"] if c["角色"] == "代打" and c["守備"] != "bad"]
        pen = [c for c in r["bullpen"]["rows"] if c["角色"] == "牛棚"]
        got = (ph[0]["球員"], round(ph[0]["相對現任"], 2), pen[0]["投手"], round(pen[0]["守方勝率增減"], 2))
        ok = got == (ph_best, ph_gain, pen_best, pen_gain)
        fails += not ok
        print(("OK  " if ok else "DIFF"), pid, "時機資料", (ph_best, ph_gain, pen_best, pen_gain), "回放", got)
    # 有板凳但全員換下後守備排不出來的打席：回放頁的候選也應全部是 bad（網站不會建議代打）
    nobody = [(pid, v) for g in data["games"].values() for pid, v in g.items() if v[3] is None and len(v) > 6 and v[6]]
    random.Random(1).shuffle(nobody)
    for pid, _ in nobody[:5]:
        d = str(date[pid].date())
        r = server.build_result(situation(pid), server.model_for(d), mlmodel.for_date(d))
        bench = [c for c in r["candidates"] if c["角色"] == "代打"]
        ok = bool(bench) and all(c["守備"] == "bad" for c in bench)
        fails += not ok
        print(("OK  " if ok else "DIFF"), pid, "板凳全員守備不成立", len(bench), "人")
    print(f"抽樣 {min(n, len(pool)) + min(5, len(nobody))} 個打席，不一致 {fails} 個")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
