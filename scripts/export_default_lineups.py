"""產生各隊 2025 預設場上名單（場上名單頁的初始值）。

做法：取各隊 2025 最後 RECENT 場的先發打者（每個棒次第一位出場者），
先發捕手取同期間最常先發的捕手；其餘 7 個守位與指定打擊一起分配：
每個守位只排「能守」的球員（歷年該守位 ≥ 3 場，與網站守備檢查相同），
在此前提下讓 8 人的最後 RECENT 場先發次數合計最多；同分時比 2025 全季先發次數（主力優先），
再同分才比該守位出賽場數；
棒次依平均先發棒次排序；投手取該期間先發次數最多、且仍在名單中的投手。
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


CANNOT = 1e6     # 不能守的守位


def build(rosters, pa, boxes, position_games, can_play, recent=RECENT):
    b25 = boxes[boxes["date"].dt.year == 2025]
    pa25 = pa[pa["season"] == 2025]
    g = position_games(None)
    out = {}
    for team, r in sorted(rosters.items()):
        hitters = {h["name"] for h in r["hitters"]}
        pitchers = {p["name"] for p in r["pitchers"]}
        games = sorted(b25.loc[b25["team"] == team, "game"].unique())[-recent:]
        d = b25[(b25["team"] == team) & b25["game"].isin(games)]
        bat = d[d["role"] == "B"].drop_duplicates(["game", "order"])  # 每棒次第一位＝先發
        bat = bat[bat["order"].between(1, 9) & bat["name"].isin(hitters)]
        starts = bat.groupby("name").agg(n=("game", "size"), order=("order", "mean"))
        season = b25[(b25["team"] == team) & (b25["role"] == "B")].drop_duplicates(["game", "order"])
        season = season[season["order"].between(1, 9)].groupby("name").size()
        # 先發捕手：本隊守備時、每場第一個打席的捕手
        first = pa25[(pa25["fld_team"] == team) & pa25["game"].isin(games)].sort_values(["game", "seq"]).drop_duplicates("game")
        catchers = first["catcher"].value_counts()
        catchers = [c for c in catchers.index if c in hitters]
        if len(starts) < 8 or not catchers:
            continue
        catcher = catchers[0]
        # 候選：名單中除捕手外的所有野手（近期沒先發的人只在必要時用來補守位）
        names = sorted(hitters - {catcher})
        # 分數：近期先發 ＋ 0.001 × 全季先發（≤ 0.144，只在近期同分時起作用）＋ 1e-6 × 守位場數（≤ 0.0003）
        score = starts["n"].reindex(names).fillna(0).to_numpy() + 1e-3 * season.reindex(names).fillna(0).to_numpy()
        cost = np.array([[-score[i] if s == "DH" else
                          (-score[i] - 1e-6 * min(float(g.get((name, s), 0.0)), 300) if can_play(name, s) else CANNOT)
                          for s in SLOTS] for i, name in enumerate(names)])
        ri, ci = linear_sum_assignment(cost)
        if cost[ri, ci].max() >= CANNOT:
            raise ValueError(f"{team} 找不到能守全部守位的組合")
        pos = {names[i]: SLOTS[j] for i, j in zip(ri, ci)}
        pos[catcher] = "C"
        nine = starts.reindex(list(pos)).assign(n=lambda x: x["n"].fillna(0)).sort_values(["order", "n"], ascending=[True, False], na_position="last")
        pit = d[(d["role"] == "P") & (d["order"] == 1) & d["name"].isin(pitchers)]["name"].value_counts()
        pitcher = pit.index[0] if len(pit) else next((p["name"] for p in r["pitchers"] if p["role"] == "先發"), "")
        out[team] = {"slots": [{"name": n, "pos": pos[n]} for n in nine.index], "pitcher": pitcher,
                     "games": len(games), "through": str(b25.loc[b25["game"].isin(games), "date"].max().date())}
    return out


if __name__ == "__main__":
    import server
    from load import load
    from roster import can_play, position_games

    pa, _, boxes = load()
    teams = build(server.rosters(), pa, boxes, position_games, can_play)
    result = {"season": 2025, "method": f"各隊最後 {RECENT} 場先發打者與先發投手（Rebas 2025 例行賽，ODC-By v1.0）", "teams": teams}
    (ROOT / "docs/data/default-lineups-2025.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for t, v in teams.items():
        print(t, v["pitcher"], " ".join(f"{s['name']}({s['pos']})" for s in v["slots"]))
