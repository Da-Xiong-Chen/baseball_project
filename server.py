"""本機網頁伺服器：python server.py 後開啟 http://localhost:8000

只用 Python 標準函式庫 + 專案既有的 pandas/numpy/scipy。
"""
import json
import math
import os
import sys
import threading
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))

import pandas as pd  # noqa: E402

from engine import (_hands, bat_hand, custom_situation, evaluate_bullpen, evaluate_pinch_hit,  # noqa: E402
                    matchup_detail, situation)
from load import CELLS, load  # noqa: E402
from model import fit  # noqa: E402
from roster import POS_ZH, can_play, positions_of  # noqa: E402

PORT = int(os.environ.get("PORT", 8000))
WEB = os.path.join(ROOT, "docs")
_lock = threading.Lock()
_models = {}
FULL = "2026-01-01"  # 自訂情境用全部資料


def model_for(date_str):
    with _lock:
        if date_str not in _models:
            _models[date_str] = fit(date_str, season=2025 if date_str == FULL else None)
        return _models[date_str]


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [clean(v) for v in o]
    if isinstance(o, pd.DataFrame):
        return clean(o.to_dict("records"))
    if isinstance(o, pd.Series):
        return clean(o.to_dict())
    if isinstance(o, pd.Timestamp):
        return str(o.date())
    if hasattr(o, "item"):
        o = o.item()
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return o


# ---------- 名單 ----------
_rosters = None


def rosters():
    global _rosters
    if _rosters is not None:
        return _rosters
    pa, _, boxes = load()
    b25 = boxes[boxes["date"].dt.year == 2025].sort_values("date")
    bh, ph = _hands()
    out = {}
    for team, d in b25.groupby("team"):
        hit = d[d["role"] == "B"]
        pit = d[d["role"] == "P"]
        # 球員以最後出現的隊伍為準
        last_team_b = b25[b25["role"] == "B"].groupby("name")["team"].last()
        last_team_p = b25[b25["role"] == "P"].groupby("name")["team"].last()
        hitters = []
        for name, g in hit.groupby("name"):
            if last_team_b.get(name) != team or name in set(pit["name"]):
                continue
            hitters.append(dict(name=name, hand=bh.get(name, "R"), pa=int(g["PA"].sum()), games=int(g["game"].nunique()),
                                positions=positions_of(name), catcher=bool(can_play(name, "C"))))
        pitchers = []
        for name, g in pit.groupby("name"):
            if last_team_p.get(name) != team:
                continue
            starts = int((g["order"] == 1).sum())
            pitchers.append(dict(name=name, hand=ph.get(name, "R"), games=int(len(g)), starts=starts,
                                 role="先發" if starts >= len(g) / 2 else "後援", np=int(g["NP"].sum())))
        out[team] = dict(hitters=sorted(hitters, key=lambda x: -x["pa"]),
                         pitchers=sorted(pitchers, key=lambda x: (x["role"] != "後援", -x["games"])))
    _rosters = out
    return out


# ---------- 結果組裝 ----------
def pitch_mix_payload(m, pitcher):
    res = {}
    for h in ("R", "L"):
        mix, n = m.pitch_mix(pitcher, h)
        res[h] = dict(n=int(n), cells={c: float(mix.get(c, 0)) for c in CELLS})
    return res


def build_result(sit, m, actual=None):
    row = sit["row"]
    ph_df, slope, _ = evaluate_pinch_hit(sit, model=m)
    bp_df, nxt = evaluate_bullpen(sit, model=m)
    r = {k: row[k] for k in ("inning", "half", "outs", "bases", "bat_score", "fld_score", "pitcher", "phand",
                             "bat_team", "fld_team", "date")}
    r["pitch_count"] = sit.get("pitch_count")
    r["starter"] = sit.get("starter", False)
    r["due"] = sit["due"]
    r["due_pos"] = sit["positions"].get(sit["due"], "DH")
    r["due_pos_zh"] = POS_ZH.get(r["due_pos"], r["due_pos"])
    return clean(dict(
        situation=r, actual=actual, leverage=slope * 100, league_leverage=m.slope_all * 100,
        pitch_mix=pitch_mix_payload(m, row["pitcher"]),
        candidates=ph_df, bullpen=dict(next=nxt, rows=bp_df), model_cutoff=str(m.cutoff.date()),
    ))


# ---------- API ----------
def api(path, qs, body):
    pa, _, boxes = load()
    if path == "/api/meta":
        r = rosters()
        return dict(teams=sorted(r), cells=CELLS, positions=POS_ZH)
    if path == "/api/team":
        return rosters()[qs["team"][0]]
    if path == "/api/games":
        team = qs["team"][0]
        g = pa[(pa["season"] == 2025) & ((pa["bat_team"] == team) | (pa["fld_team"] == team))]
        out = []
        for gid, d in g.groupby("game"):
            aw = d[d["half"] == "away"]
            hm = d[d["half"] == "home"]
            away = aw["bat_team"].iat[0] if len(aw) else hm["fld_team"].iat[0]
            home = hm["bat_team"].iat[0] if len(hm) else aw["fld_team"].iat[0]
            ascore = int((aw["bat_score"] + aw["runs"]).max()) if len(aw) else 0
            hscore = int((hm["bat_score"] + hm["runs"]).max()) if len(hm) else 0
            out.append(dict(game=gid, date=str(d["date"].iat[0].date()), away=away, home=home,
                            away_score=ascore, home_score=hscore, ph=int(d["is_ph"].sum())))
        return sorted(out, key=lambda x: x["date"], reverse=True)
    if path == "/api/game":
        gid = qs["game"][0]
        d = pa[pa["game"] == gid]
        d = d.assign(h=d["half"].map({"away": 0, "home": 1})).sort_values(["inning", "h", "seq"])
        cols = ["pa_id", "inning", "half", "outs", "bases", "bat_team", "fld_team", "bat_score", "fld_score",
                "batter", "pitcher", "is_ph", "result", "WPA"]
        return clean(d[cols])
    if path == "/api/replay":
        pid = qs["pa"][0]
        row = pa.loc[pa["pa_id"] == pid].iloc[0]
        m = model_for(str(row["date"].date()))
        sit = situation(pid)
        actual = dict(batter=row["batter"], is_ph=bool(row["is_ph"]), result=row["result"], WPA=row["WPA"])
        return build_result(sit, m, actual)
    if path == "/api/evaluate":
        m = model_for(FULL)
        s = custom_situation(**body)
        return build_result(s, m)
    if path == "/api/detail":
        date = qs.get("date", [FULL])[0]
        m = model_for(date if date != "custom" else FULL)
        return clean(matchup_detail(m, qs["batter"][0], qs["pitcher"][0]))
    raise KeyError(path)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_api(self, body=None):
        u = urlparse(self.path)
        try:
            self._send_json(api(u.path, parse_qs(u.query), body))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._send_json(dict(error=f"{type(e).__name__}: {e}"), 400)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._handle_api()
        return super().do_GET()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        return self._handle_api(body)


if __name__ == "__main__":
    print("載入資料與建立模型中（約 15 秒）…")
    load()
    rosters()
    model_for(FULL)
    print(f"完成。請開啟 http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
