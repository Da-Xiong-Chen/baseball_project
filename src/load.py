"""讀取 Rebas Open Data，整理成打席表 (pa) 與逐球表 (pitches)，並計算每顆球的得分價值。"""
import glob
import json
import os
from bisect import bisect_right
from collections import defaultdict
from functools import lru_cache

import numpy as np
import pandas as pd
from identity import source_key, game_rosters, participant_key
from runtime_config import settings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.abspath(os.environ.get("BASEBALL_DATA_ROOT", os.path.join(ROOT, "data")))

# 球種分群：依實際進壘高度（2025 平均 coordY：FF +10、SI -2.5、FC -14、SL -31、CU -30、CH -35、FO -40）
PITCH_GROUP = {
    "FF": "速球", "SI": "速球",
    "FC": "滑卡", "SL": "滑卡",
    "CU": "曲球",
    "CH": "低落", "FO": "低落", "FS": "低落", "KN": "低落", "EP": "曲球",
}
GROUPS = ["速球", "滑卡", "曲球", "低落"]
LOW_Y = -21.0  # 好球帶約 ±63，低於下三分之一視為低球
CELLS = [f"{g}{'低' if low else '高中'}" for g in GROUPS for low in (False, True)]

STRIKE_CODES = {"S", "SW", "FT", "TRY_BUNT"}
FOUL_CODES = {"F", "FOUL_BUNT"}


def _game_files():
    files=[]
    for year in settings().data_seasons:
        selected=sorted(glob.glob(os.path.join(DATA,'rebas',str(year),'*.json')))
        if not selected:raise ValueError(f'Missing configured season: {year}')
        files.extend(selected)
    return files


@lru_cache(maxsize=1)
def load():
    """回傳 (pa, pitches, boxes)。"""
    pa_rows, pitch_rows, box_rows = [], [], []
    for f in _game_files():
        with open(f, encoding="utf8") as source:
            g = json.load(source)
        roster = game_rosters(g)
        season = int(g["date"][:4])
        gid = f"{season}-{g['seq']:03d}"
        date = pd.Timestamp(g["date"][:10])
        teams = {"away": g["awayTeam"], "home": g["homeTeam"]}
        for side in ("away", "home"):
            other = "home" if side == "away" else "away"
            for b in g[side + "BatterBox"]:
                box_rows.append(dict(game=gid, date=date, team=teams[side], name=source_key(b["playerId"]),
                                     raw_name=b['playerName'], source_player_id=b['playerId'],
                                     number=b.get('playerNumber'), source_file=f,
                                     order=b["order"], role="B", PA=b["PA"]))
            for i, p in enumerate(g[side + "PitcherBox"]):
                box_rows.append(dict(game=gid, date=date, team=teams[side], name=source_key(p["playerId"]),
                                     raw_name=p['playerName'], source_player_id=p['playerId'],
                                     number=p.get('playerNumber'), source_file=f,
                                     order=i + 1, role="P", NP=p["NP"], BF=p["BF"]))
            for k, p in enumerate(g[side + "PAList"]):
                bat_start = p["awayScores"] if side == "away" else p["homeScores"]
                bat_end = p["endAwayScores"] if side == "away" else p["endHomeScores"]
                fld_start = p["homeScores"] if side == "away" else p["awayScores"]
                pa_id = f"{gid}-{side[0]}{k:03d}"
                pa_rows.append(dict(
                    pa_id=pa_id, game=gid, season=season, date=date, seq=k, half=side,
                    bat_team=teams[side], fld_team=teams[other],
                    inning=p["inning"], outs=p["outs"], bases=p["bases"],
                    bat_score=bat_start, fld_score=fld_start, runs=bat_end - bat_start,
                    end_outs=p["endOuts"], end_bases=p["endBases"],
                    batter=participant_key(roster, side, 'batter', p['batterName']), bhand=p['batterHand'],
                    pitcher=participant_key(roster, other, 'pitcher', p['pitcherName']), phand=p['pitcherHand'],
                    catcher=participant_key(roster, other, 'catcher', p['catcherName']),
                    batter_raw_name=p['batterName'], pitcher_raw_name=p['pitcherName'], catcher_raw_name=p['catcherName'],
                    source_file=f,
                    is_ph=p["isPH"], pa_order=p["paOrder"],
                    result=p.get("result", p.get("results")),
                    hardness=p.get("hardness") or None, trajectory=p.get("trajectory") or None,
                    WPA=float(p["WPA"]) if p["WPA"] not in (None, "") else np.nan,
                    RE24=float(p["RE24"]) if p["RE24"] not in (None, "") else np.nan,
                    homeWE=float(p["homeWE"]) if p["homeWE"] not in (None, "") else np.nan,
                ))
                # 依 event 重建球數
                balls = strikes = 0
                pitches = [(i,e) for i,e in enumerate(p["events"]) if e["type"] == "PITCH"]
                parent = pa_rows[-1]
                for j, (event_index, e) in enumerate(pitches):
                    code = e["pitchCode"]
                    bn, pn, cn = (e[field] if field in e else p[field] for field in ('batterName','pitcherName','catcherName'))
                    batter = participant_key(roster, side, 'batter', bn)
                    pitcher = participant_key(roster, other, 'pitcher', pn)
                    catcher = participant_key(roster, other, 'catcher', cn)
                    velocity = _numeric(e.get('velocity'))
                    pitch_rows.append(dict(
                        pa_id=pa_id, j=j, last=(j == len(pitches) - 1), balls=min(balls, 3), strikes=min(strikes, 2),
                        event_index=event_index, batter=batter, pitcher=pitcher, catcher=catcher,
                        batter_raw_name=bn, pitcher_raw_name=pn, catcher_raw_name=cn,
                        pa_batter=parent['batter'], pa_pitcher=parent['pitcher'], pa_catcher=parent['catcher'],
                        bhand=p['batterHand'] if batter == parent['batter'] and batter is not None else None,
                        phand=p['pitcherHand'] if pitcher == parent['pitcher'] and pitcher is not None else None,
                        velocity_raw=e.get('velocity'), velo=velocity if 80 <= velocity <= 170 else np.nan,
                        ptype=e["pitchType"] or None, code=code,
                        y=_numeric(e.get('coordY')), x=_numeric(e.get('coordX')),
                    ))
                    if code == "B":
                        balls += 1
                    elif code in STRIKE_CODES:
                        strikes += 1
                    elif code in FOUL_CODES and strikes < 2:
                        strikes += 1
    pa = pd.DataFrame(pa_rows)
    pitches = pd.DataFrame(pitch_rows)
    boxes = pd.DataFrame(box_rows)

    # 半局結束時的得分 → 每個打席開始到半局結束的得分（用來建立含球數的得分期望表）
    half_key = ["game", "half", "inning"]
    pa["runs_to_end"] = pa.groupby(half_key)["runs"].transform(lambda s: s[::-1].cumsum()[::-1])
    pitches = pitches.merge(pa[["pa_id", "bases", "outs", "runs_to_end", "runs", "end_outs", "end_bases",
                                "date", "season", "game", "seq", "half", "inning", "fld_team", "bat_team",
                                "hardness"]], on="pa_id", validate='many_to_one')
    _resolve_pitch_hands(pa, pitches)
    # 逐球結果分類：揮空、強勁擊球（進場且 hardness=H）、其他
    pitches["whiff"] = (pitches["code"] == "SW").astype(float)
    pitches["hard"] = ((pitches["code"] == "H") & pitches["last"] & (pitches["hardness"] == "H")).astype(float)
    pitches["group"] = pitches["ptype"].map(PITCH_GROUP)
    pitches["low"] = pitches["y"] < LOW_Y
    pitches["cell"] = pitches["group"] + np.where(pitches["low"], "低", "高中")
    pitches.loc[pitches["group"].isna() | pitches["y"].isna(), "cell"] = None
    pitches["platoon"] = np.where(pitches["bhand"] == pitches["phand"], "同側", "異側")
    pitches.loc[~pitches.bhand.isin(['L','R']) | ~pitches.phand.isin(['L','R']), 'platoon'] = None

    pitches["rv"] = _pitch_run_values(pitches)
    return pa, pitches, boxes


def _numeric(value):
    if isinstance(value, bool):
        return np.nan
    try:
        value = float(value)
        return value if np.isfinite(value) else np.nan
    except (ValueError, TypeError, OverflowError):
        return np.nan


def _resolve_pitch_hands(pa, pitches):
    """Use same-actor PA evidence or dated own-player evidence, never another actor's hand."""
    histories = {}
    for actor, hand in (('pitcher','phand'), ('batter','bhand')):
        known = pa[pa[hand].isin(['L','R','S']) & pa[actor].notna()].sort_values('date', kind='stable')
        histories[actor] = {key: (list(rows.date), list(rows[hand])) for key, rows in known.groupby(actor)}
    cache = {}

    def lookup(actor, key, day, opposite=None):
        token = (actor,key,day,opposite)
        if token in cache:
            return cache[token]
        days, hands = histories[actor].get(key, ([],[]))
        stop = bisect_right(days, day)
        if not stop:
            result = (None, None)
        else:
            observed = hands[:stop]
            switch = 'S' in observed or (set(observed) >= {'L','R'} and
                     min(observed.count('L'),observed.count('R')) / len(observed) > .1)
            if actor == 'batter' and switch:
                result = (('L' if opposite == 'R' else 'R') if opposite in ('L','R') else None, days[stop-1])
            else:
                result = (observed[-1] if observed[-1] in ('L','R') else None, days[stop-1])
        cache[token] = result
        return result

    for actor, column in (('pitcher','phand'), ('batter','bhand')):
        source_col, date_col = column + '_source', column + '_evidence_date'
        pitches[source_col] = np.where(pitches[column].isin(['L','R']), 'same_actor_pa', 'unresolved')
        pitches[date_col] = pitches['date'].where(pitches[column].isin(['L','R']))
        missing = pitches.index[~pitches[column].isin(['L','R'])]
        for index in missing:
            row = pitches.loc[index]
            hand, evidence_day = lookup(actor, row[actor], row['date'], row['phand'] if actor == 'batter' else None)
            if hand:
                pitches.at[index, column] = hand
                pitches.at[index, source_col] = 'dated_own_player_evidence'
                pitches.at[index, date_col] = evidence_day


def _pitch_run_values(p):
    """每顆球的得分價值 = 投球後狀態的得分期望 − 投球前狀態的得分期望（含該球造成的得分）。"""
    re = p.groupby(["bases", "outs", "balls", "strikes"])["runs_to_end"].mean()
    re00 = re.xs((0, 0), level=("balls", "strikes"))

    def lookup(b, o, bl, st):
        return re.reindex(pd.MultiIndex.from_arrays([b, o, bl, st])).to_numpy()

    before = lookup(p["bases"], p["outs"], p["balls"], p["strikes"])
    nb = p["balls"].to_numpy().copy()
    ns = p["strikes"].to_numpy().copy()
    code = p["code"].to_numpy()
    nb = np.where(code == "B", np.minimum(nb + 1, 3), nb)
    ns = np.where(np.isin(code, list(STRIKE_CODES)), np.minimum(ns + 1, 2), ns)
    ns = np.where(np.isin(code, list(FOUL_CODES)), np.minimum(ns + 1, 2), ns)
    mid = lookup(p["bases"], p["outs"], nb, ns)

    end_re = re00.reindex(pd.MultiIndex.from_arrays([p["end_bases"], p["end_outs"]])).to_numpy()
    end_re = np.where(p["end_outs"].to_numpy() >= 3, 0.0, end_re)
    terminal = end_re + p["runs"].to_numpy() - before
    rv = np.where(p["last"].to_numpy(), terminal, mid - before)
    return rv


@lru_cache(maxsize=2)
def pitches_before(cutoff):
    """Training labels and run-expectancy table both use only completed prior games."""
    p = load()[1]
    p = p[p["date"] < pd.Timestamp(cutoff)].copy()
    if p.empty:
        raise ValueError("截止日前沒有逐球資料")
    p["rv"] = _pitch_run_values(p)
    return p
