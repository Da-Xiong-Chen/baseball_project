"""產生各隊 2025 預設場上名單（場上名單頁的初始值）。

做法：取各隊 2025 最後 RECENT 場的先發打者（每個棒次第一位出場者），
先發捕手取同期間最常先發的捕手，其餘 8 人取先發次數最多者；
棒次依平均先發棒次排序，守位以歷年守位出賽場數做最佳分配；
投手取該期間先發次數最多、且仍在名單中的投手。
"""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

RECENT = 30
SLOTS = ["1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]


def build(rosters, pa, boxes, position_games, recent=RECENT):
    b25 = boxes[boxes["date"].dt.year == 2025]
    pa25 = pa[pa["season"] == 2025]
    g = position_games("2026-01-01")
    out = {}
    for team, r in sorted(rosters.items()):
        hitters = {h["name"] for h in r["hitters"]}
        pitchers = {p["name"] for p in r["pitchers"]}
        games = sorted(b25.loc[b25["team"] == team, "game"].unique())[-recent:]
        d = b25[(b25["team"] == team) & b25["game"].isin(games)]
        bat = d[d["role"] == "B"].drop_duplicates(["game", "order"])  # 每棒次第一位＝先發
        bat = bat[bat["order"].between(1, 9) & bat["name"].isin(hitters)]
        starts = bat.groupby("name").agg(n=("game", "size"), order=("order", "mean"))
        # 先發捕手：本隊守備時、每場第一個打席的捕手
        first = pa25[(pa25["fld_team"] == team) & pa25["game"].isin(games)].sort_values(["game", "seq"]).drop_duplicates("game")
        catchers = first["catcher"].value_counts()
        catchers = [c for c in catchers.index if c in hitters]
        if len(starts) < 8 or not catchers:
            continue
        catcher = catchers[0]
        others = starts.drop(index=catcher, errors="ignore").sort_values("n", ascending=False).head(8)
        nine = starts.loc[[catcher] + list(others.index)].sort_values(["order", "n"], ascending=[True, False])
        # 守位分配（捕手固定）
        names = list(others.index)
        cost = np.array([[-0.5 if s == "DH" else -float(g.get((n, s), 0.0)) for s in SLOTS] for n in names])
        ri, ci = linear_sum_assignment(cost)
        pos = {names[i]: SLOTS[j] for i, j in zip(ri, ci)}
        pos[catcher] = "C"
        pit = d[(d["role"] == "P") & (d["order"] == 1) & d["name"].isin(pitchers)]["name"].value_counts()
        pitcher = pit.index[0] if len(pit) else next((p["name"] for p in r["pitchers"] if p["role"] == "先發"), "")
        out[team] = {"slots": [{"name": n, "pos": pos[n]} for n in nine.index], "pitcher": pitcher,
                     "games": len(games), "through": str(b25.loc[b25["game"].isin(games), "date"].max().date())}
    return out


if __name__ == "__main__":
    import server
    from load import load
    from roster import position_games

    pa, _, boxes = load()
    teams = build(server.rosters(), pa, boxes, position_games)
    result = {"season": 2025, "method": f"各隊最後 {RECENT} 場先發打者與先發投手（Rebas 2025 例行賽，ODC-By v1.0）", "teams": teams}
    (ROOT / "docs/data/default-lineups-2025.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for t, v in teams.items():
        print(t, v["pitcher"], " ".join(f"{s['name']}({s['pos']})" for s in v["slots"]))
