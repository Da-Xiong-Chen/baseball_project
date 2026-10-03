"""守位能力、當日名單推估、守備檢查。"""
import os
from functools import lru_cache

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from load import DATA, load
from identity import catalog

FIELD_POS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
POS_ZH = {"C": "捕手", "1B": "一壘", "2B": "二壘", "3B": "三壘", "SS": "游擊",
          "LF": "左外野", "CF": "中外野", "RF": "右外野", "DH": "指定打擊"}
SHORT_TEAM = {"中信": "中信兄弟", "統一": "統一7-ELEVEn獅", "樂天": "樂天桃猿", "富邦": "富邦悍將",
              "味全": "味全龍", "台鋼": "台鋼雄鷹", "Lamigo": "樂天桃猿"}
MIN_GAMES = 3          # 近年在該守位出賽 ≥ 3 場才算「能守」
CATCHER_MIN_PITCHES = 50


@lru_cache(maxsize=64)
def position_games(cutoff=None):
    """(team, name, pos) → 加權出賽場數。2025 中職官網 + 2023–2024 ldkrsi（MIT）。"""
    frames = []
    cur_path = os.path.join(DATA, "cpbl", "positions_2025.csv")
    year = pd.Timestamp(cutoff).year if cutoff else 9999
    if year > 2025 and os.path.exists(cur_path):  # 整季資料僅能於下一年使用
        cur = pd.read_csv(cur_path, dtype={"ID": str}, encoding="utf-8-sig")
        cur["w"] = 1.0
        frames.append(cur.rename(columns={"Team Name": "team", "Name": "name"}))
    for y, w in ((2024, 0.7), (2023, 0.4)):
        if y >= year:
            continue
        path = os.path.join(DATA, "ldkrsi", f"fieldings_{y}.csv")
        if not os.path.exists(path):
            continue
        d = pd.read_csv(path, dtype={"ID": str})
        d = d[d["POS"] != "P"]
        d["team"] = d["Team Name"].map(SHORT_TEAM).fillna(d["Team Name"])
        d["w"] = w
        frames.append(d.rename(columns={"Name": "name"}))
    if not frames:
        return pd.Series(dtype=float, index=pd.MultiIndex.from_tuples([], names=["name", "POS"]))
    allp = pd.concat(frames)[["name", "team", "POS", "G", "w"]]
    allp["G_w"] = allp["G"] * allp["w"]
    # 守位能力跟人走、不跟隊伍走（轉隊仍能守）
    return allp.groupby(["name", "POS"])["G_w"].sum()


@lru_cache(maxsize=64)
def catcher_pitches(cutoff=None):
    _, p, _ = load()
    if cutoff:
        p = p[p["date"] < pd.Timestamp(cutoff)]
    return p.groupby("catcher").size()


def can_play(name, pos, cutoff=None):
    if pos == "DH":
        return True
    if len(catalog().get(name, ())) > 1:
        return False  # Cross-provider IDs are not interchangeable; never merge by name.
    g = position_games(cutoff)
    games = float(g.get((name, pos), 0.0))
    if pos == "C":
        return games >= MIN_GAMES or catcher_pitches(cutoff).get(name, 0) >= CATCHER_MIN_PITCHES
    return games >= MIN_GAMES


def positions_of(name, cutoff=None):
    if len(catalog().get(name, ())) > 1:
        return {}
    g = position_games(cutoff)
    if name not in g.index.get_level_values(0):
        return {}
    s = g.loc[name]
    return {p: round(float(v), 1) for p, v in s.sort_values(ascending=False).items() if v >= MIN_GAMES}


def assign_positions(lineup, cutoff=None):
    """依守位出賽紀錄，把 9 位打者分配到 9 個守位（含 DH），最大化總出賽場數。"""
    slots = FIELD_POS + ["DH"]
    g = position_games(cutoff)
    cost = np.zeros((len(lineup), len(slots)))
    for i, n in enumerate(lineup):
        for j, s in enumerate(slots):
            cost[i, j] = -0.5 if s == "DH" else -float(g.get((n, s), 0.0))
            if s != "DH" and not can_play(n, s, cutoff):
                cost[i, j] = 1000
    r, c = linear_sum_assignment(cost)
    return {lineup[i]: slots[j] for i, j in zip(r, c) if cost[i, j] < 1000}


def defense_check(out_name, out_pos, in_name, bench_after, cutoff=None):
    """out_name（守 out_pos）被 in_name 代打後，守備排不排得出來。"""
    if out_pos not in FIELD_POS + ["DH"]:
        return "warn", "現任守位未知，請確認當場守位與接守安排；未評估守備品質"
    if out_pos == "DH":
        return "ok", f"{in_name} 接任指定打擊"
    if can_play(in_name, out_pos, cutoff):
        msg = f"{in_name} 可直接接守{POS_ZH[out_pos]}"
        status = "ok"
    else:
        cover = [b for b in bench_after if can_play(b, out_pos, cutoff)]
        if cover:
            msg = f"需由 {cover[0]} 接守{POS_ZH[out_pos]}（再消耗 1 名板凳）"
            status = "warn"
        else:
            return "bad", f"換下後板凳無人可守{POS_ZH[out_pos]}"
    if out_pos == "C":
        backups = [b for b in bench_after if can_play(b, "C", cutoff) and b != in_name]
        if len(backups) == 0:
            msg += "；之後板凳已無備用捕手"
            status = "warn" if status == "ok" else status
    return status, msg


def pitcher_names(boxes):
    """以投手身分出賽次數多於野手的人才算投手（野手偶爾敗戰處理登板不算）。"""
    c = boxes.groupby(["name", "role"]).size().unstack(fill_value=0)
    p = c.get("P", pd.Series(0, index=c.index))
    b = c.get("B", pd.Series(0, index=c.index))
    return set(c.index[p > b])


POOL_MIN_PA = 100     # 價值分數的比較基準：2025 年 100 打席以上的打者
POOL_MIN_GAMES = 15   # 以及 15 場以上的後援投手


@lru_cache(maxsize=64)
def hitter_pool(cutoff=None):
    boxes = load()[2]
    if cutoff:
        boxes = boxes[boxes["date"] < pd.Timestamp(cutoff)]
    year = min(pd.Timestamp(cutoff).year, 2025) if cutoff else 2025
    b = boxes[boxes["date"].dt.year == year]
    if b.loc[b["role"] == "B", "PA"].sum() < POOL_MIN_PA:
        b = boxes[boxes["date"].dt.year == year - 1]
    pa = b[b["role"] == "B"].groupby("name")["PA"].sum()
    result = sorted(set(pa[pa >= POOL_MIN_PA].index) - pitcher_names(b))
    if not result and cutoff:
        b = boxes[boxes["date"].dt.year == year - 1]
        pa = b[b["role"] == "B"].groupby("name")["PA"].sum()
        result = sorted(set(pa[pa >= POOL_MIN_PA].index) - pitcher_names(b))
    return result


@lru_cache(maxsize=64)
def reliever_pool(cutoff=None):
    boxes = load()[2]
    if cutoff:
        boxes = boxes[boxes["date"] < pd.Timestamp(cutoff)]
    year = min(pd.Timestamp(cutoff).year, 2025) if cutoff else 2025
    b = boxes[boxes["date"].dt.year == year]
    p = b[b["role"] == "P"]
    g = p.groupby("name").agg(n=("game", "nunique"), st=("order", lambda s: (s == 1).mean()))
    result = sorted(set(g[(g["n"] >= POOL_MIN_GAMES) & (g["st"] < 0.5)].index) & pitcher_names(b))
    if not result and cutoff:
        b = boxes[boxes["date"].dt.year == year - 1]
        p = b[b["role"] == "P"]
        g = p.groupby("name").agg(n=("game", "nunique"), st=("order", lambda s: (s == 1).mean()))
        result = sorted(set(g[(g["n"] >= POOL_MIN_GAMES) & (g["st"] < 0.5)].index) & pitcher_names(b))
    return result


def active_roster(team, game_date, game_id, window_days=10):
    """僅以比賽日前 window_days 天的出賽推估可用名單，並非官方登錄。"""
    _, _, boxes = load()
    d = boxes[(boxes["team"] == team)]
    recent = d[(d["date"] < game_date) & (d["date"] >= game_date - pd.Timedelta(days=window_days))]
    # 最終 box score 不能當成賽前登錄名單。僅採過去出賽推估。
    today = d.iloc[:0]
    pitchers = pitcher_names(d[(d["date"] < game_date) & (d["date"] >= game_date - pd.Timedelta(days=60))])
    hitters = set(recent.loc[recent["role"] == "B", "name"]) | set(today.loc[today["role"] == "B", "name"])
    # 牛棚：排除先發投手（本季先發比例 ≥ 50%，或今天是先發）
    season_p = d[(d["role"] == "P") & (d["date"] < game_date) & (d["date"].dt.year == game_date.year)]
    start_ratio = season_p.assign(start=season_p["order"] == 1).groupby("name")["start"].mean()
    starters = set(start_ratio[start_ratio >= 0.5].index) | set(today.loc[(today["role"] == "P") & (today["order"] == 1), "name"])
    pen = (set(recent.loc[recent["role"] == "P", "name"]) | set(today.loc[today["role"] == "P", "name"])) - starters
    pen &= pitchers | pitcher_names(today)
    return sorted(hitters - pitchers), sorted(pen)
