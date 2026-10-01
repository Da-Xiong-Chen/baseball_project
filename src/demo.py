"""歷史回放示範：挑 2025 年後段、比分接近、實際有換代打的情境，看系統當時會怎麼建議。

用法：
    python demo.py              # 自動挑 3 個情境
    python demo.py 2025-123-h045  # 指定打席 ID
"""
import sys

import pandas as pd

from engine import evaluate_bullpen, evaluate_pinch_hit, situation
from load import load
from roster import POS_ZH

pd.set_option("display.unicode.east_asian_width", True)
pd.set_option("display.width", 200)
BASES = {0: "無人", 1: "一壘", 2: "二壘", 3: "一二壘", 4: "三壘", 5: "一三壘", 6: "二三壘", 7: "滿壘"}


def pick_examples(n=3):
    pa, p, _ = load()
    low = p[p["season"] == 2025].groupby("pitcher")["cell"].apply(lambda s: s.isin(["低落低", "低落高中"]).mean())
    c = pa[(pa["season"] == 2025) & pa["is_ph"] & (pa["inning"] >= 7)
           & ((pa["bat_score"] - pa["fld_score"]).abs() <= 2) & (pa["date"] >= "2025-06-01")].copy()
    c["low_share"] = c["pitcher"].map(low)
    c = c.sort_values("low_share", ascending=False).drop_duplicates("pitcher").drop_duplicates("game")
    return c["pa_id"].head(n).tolist()


def show(pa_id):
    sit = situation(pa_id)
    r = sit["row"]
    diff = r["bat_score"] - r["fld_score"]
    half = "上" if r["half"] == "away" else "下"
    print("=" * 100)
    print(f"[{pa_id}] {r['date'].date()} {r['bat_team']} 攻擊 vs {r['fld_team']}")
    print(f"{r['inning']}局{half}  {r['outs']}出局  {BASES[r['bases']]}  "
          f"比分 {'領先' if diff > 0 else '落後' if diff < 0 else '平手'}{abs(diff) if diff else ''}"
          f"  ｜ 對方投手：{r['pitcher']}（{'右' if r['phand'] == 'R' else '左'}投）")
    df, slope, m = evaluate_pinch_hit(sit)
    for h, lab in (("R", "右打"), ("L", "左打")):
        mix, n = m.pitch_mix(r["pitcher"], h)
        top = mix.sort_values(ascending=False).head(3)
        print(f"  投手對{lab}球路（樣本 {n:.0f} 球）：" + "、".join(f"{k} {v:.0%}" for k, v in top.items()))
    print(f"  此局勢 1 分 ≈ {slope * 100:.1f}% 勝率（全聯盟平均 {m.slope_all * 100:.1f}%）")
    print(f"  輪到：{sit['due']}（推估守位：{POS_ZH.get(sit['positions'].get(sit['due'], 'DH'))}）  實際上場：{r['batter']}"
          f"  → 結果 {r['result']}，WPA {r['WPA']:+.3f}")
    print("  （預估勝率＝相對聯盟平均打者的勝率增減 %；本身能力／球路適性／左右優勢為每打席得分值）")
    cols = ["角色", "球員", "打擊", "預估勝率", "誤差", "相對現任", "本身能力", "球路適性", "左右優勢", "樣本球數", "可信度", "守備說明"]
    print(df[cols].round({"預估勝率": 2, "誤差": 2, "相對現任": 2, "本身能力": 3, "球路適性": 3, "左右優勢": 3}).to_string(index=False))

    bp, nxt = evaluate_bullpen(sit)
    print(f"\n  [守方視角] 牛棚對上接下來 3 棒：{'、'.join(nxt)}")
    print(bp.head(6).round(3).to_string(index=False))


if __name__ == "__main__":
    ids = sys.argv[1:] or pick_examples()
    for i in ids:
        show(i)
