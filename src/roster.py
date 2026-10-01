"""守位能力、當日名單推估、守備檢查。"""
import os
from functools import lru_cache

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from load import DATA, load

FIELD_POS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
POS_ZH = {"C": "捕手", "1B": "一壘", "2B": "二壘", "3B": "三壘", "SS": "游擊",
          "LF": "左外野", "CF": "中外野", "RF": "右外野", "DH": "指定打擊"}
SHORT_TEAM = {"中信": "中信兄弟", "統一": "統一7-ELEVEn獅", "樂天": "樂天桃猿", "富邦": "富邦悍將",
              "味全": "味全龍", "台鋼": "台鋼雄鷹", "Lamigo": "樂天桃猿"}
MIN_GAMES = 3          # 近年在該守位出賽 ≥ 3 場才算「能守」
CATCHER_MIN_PITCHES = 50


@lru_cache(maxsize=1)
def position_games():
    """(team, name, pos) → 加權出賽場數。2025 中職官網 + 2023–2024 ldkrsi（MIT）。"""
    frames = []
    cur_path = os.path.join(DATA, "cpbl", "positions_2025.csv")
    if os.path.exists(cur_path):  # 中職官網整理的 2025 守位（不隨 repo 公開，見 README）
        cur = pd.read_csv(cur_path, dtype={"ID": str}, encoding="utf-8-sig")
        cur["w"] = 1.0
        frames.append(cur.rename(columns={"Team Name": "team", "Name": "name"}))
    for y, w in ((2024, 0.7), (2023, 0.4)):
        d = pd.read_csv(os.path.join(DATA, "ldkrsi", f"fieldings_{y}.csv"), dtype={"ID": str})
        d = d[d["POS"] != "P"]
        d["team"] = d["Team Name"].map(SHORT_TEAM).fillna(d["Team Name"])
        d["w"] = w
        frames.append(d.rename(columns={"Name": "name"}))
    allp = pd.concat(frames)[["name", "team", "POS", "G", "w"]]
    allp["G_w"] = allp["G"] * allp["w"]
    # 守位能力跟人走、不跟隊伍走（轉隊仍能守）
    return allp.groupby(["name", "POS"])["G_w"].sum()


@lru_cache(maxsize=1)
def catcher_pitches():
    _, p, _ = load()
    return p.groupby("catcher").size()


def can_play(name, pos):
    if pos == "DH":
        return True
    g = position_games()
    games = float(g.get((name, pos), 0.0))
    if pos == "C":
        return games >= MIN_GAMES or catcher_pitches().get(name, 0) >= CATCHER_MIN_PITCHES
    return games >= MIN_GAMES


def positions_of(name):
    g = position_games()
    if name not in g.index.get_level_values(0):
        return {}
    s = g.loc[name]
    return {p: round(float(v), 1) for p, v in s.sort_values(ascending=False).items() if v >= MIN_GAMES}


def assign_positions(lineup):
    """依守位出賽紀錄，把 9 位打者分配到 9 個守位（含 DH），最大化總出賽場數。"""
    slots = FIELD_POS + ["DH"]
    g = position_games()
    cost = np.zeros((len(lineup), len(slots)))
    for i, n in enumerate(lineup):
        for j, s in enumerate(slots):
            cost[i, j] = -0.5 if s == "DH" else -float(g.get((n, s), 0.0))
            if s == "C" and not can_play(n, "C"):
                cost[i, j] = 1000
    r, c = linear_sum_assignment(cost)
    return {lineup[i]: slots[j] for i, j in zip(r, c)}


def defense_check(out_name, out_pos, in_name, bench_after):
    """out_name（守 out_pos）被 in_name 代打後，守備排不排得出來。"""
    if out_pos == "DH":
        return "ok", f"{in_name} 接任指定打擊"
    if can_play(in_name, out_pos):
        msg = f"{in_name} 可直接接守{POS_ZH[out_pos]}"
        status = "ok"
    else:
        cover = [b for b in bench_after if can_play(b, out_pos)]
        if cover:
            msg = f"需由 {cover[0]} 接守{POS_ZH[out_pos]}（再消耗 1 名板凳）"
            status = "warn"
        else:
            return "bad", f"換下後板凳無人可守{POS_ZH[out_pos]}"
    if out_pos == "C":
        backups = [b for b in bench_after if can_play(b, "C") and b != in_name]
        if len(backups) == 0:
            msg += "；之後板凳已無備用捕手"
            status = "warn" if status == "ok" else status
    return status, msg


def active_roster(team, game_date, game_id, window_days=10):
    """推估當日名單：過去 window_days 天內該隊出賽過的野手 + 當場名單（不含當天以後的資料）。"""
    _, _, boxes = load()
    d = boxes[(boxes["team"] == team)]
    recent = d[(d["date"] < game_date) & (d["date"] >= game_date - pd.Timedelta(days=window_days))]
    today = d[d["game"] == game_id]
    pitchers = set(d.loc[(d["role"] == "P") & (d["date"] >= game_date - pd.Timedelta(days=30)), "name"])
    hitters = set(recent.loc[recent["role"] == "B", "name"]) | set(today.loc[today["role"] == "B", "name"])
    # 牛棚：排除先發投手（本季先發比例 ≥ 50%，或今天是先發）
    season_p = d[(d["role"] == "P") & (d["date"] < game_date) & (d["date"].dt.year == game_date.year)]
    start_ratio = season_p.assign(start=season_p["order"] == 1).groupby("name")["start"].mean()
    starters = set(start_ratio[start_ratio >= 0.5].index) | set(today.loc[(today["role"] == "P") & (today["order"] == 1), "name"])
    pen = (set(recent.loc[recent["role"] == "P", "name"]) | set(today.loc[today["role"] == "P", "name"])) - starters
    return sorted(hitters - pitchers), sorted(pen)
