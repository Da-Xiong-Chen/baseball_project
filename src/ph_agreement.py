"""2025 年所有真實代打：教練實際選的人，在系統排名中排第幾？與隨機挑選比較。"""
import numpy as np
import pandas as pd

from engine import evaluate_pinch_hit, situation
from load import load
from model import fit


def main():
    pa, _, _ = load()
    ph = pa[(pa["season"] == 2025) & pa["is_ph"] & (pa["date"] >= "2025-05-01")]
    models = {}
    rows = []
    for _, r in ph.iterrows():
        month = r["date"].strftime("%Y-%m-01")
        if month not in models:
            models[month] = fit(month)
        try:
            sit = situation(r["pa_id"])
        except Exception:
            continue
        if sit["due"] == r["batter"] or r["batter"] not in sit["bench"]:
            continue  # 名單推估不到實際代打者，跳過
        df, slope, _ = evaluate_pinch_hit(sit, model=models[month])
        bench = df[df["角色"] == "代打"].reset_index(drop=True)
        rank = int(bench.index[bench["球員"] == r["batter"]][0]) + 1
        rows.append(dict(pa_id=r["pa_id"], inning=r["inning"], n_bench=len(bench), rank=rank,
                         actual_gain=float(bench.loc[rank - 1, "相對現任"]),
                         best_gain=float(bench["相對現任"].max()), slope=slope))
    d = pd.DataFrame(rows)
    d.to_csv("../output/ph_agreement.csv", index=False)
    print(f"可評估的代打情境：{len(d)}（共 {len(ph)} 次代打）")
    print(f"板凳人數中位數：{d['n_bench'].median():.0f}")
    print(f"實際代打者 = 系統第 1 名：{(d['rank'] == 1).mean():.1%}（隨機挑選期望 {np.mean(1 / d['n_bench']):.1%}）")
    print(f"實際代打者在系統前 3 名：{(d['rank'] <= 3).mean():.1%}（隨機挑選期望 {np.mean(np.minimum(3, d['n_bench']) / d['n_bench']):.1%}）")
    print(f"系統認為實際代打優於原打者的比例：{(d['actual_gain'] > 0).mean():.1%}")
    print(f"實際選擇的平均勝率增益 {d['actual_gain'].mean():+.2f}%，系統最佳選擇 {d['best_gain'].mean():+.2f}%")
    hi = d[d["slope"] >= 0.12]
    print(f"高張力情境（1 分 ≥ 12% 勝率，n={len(hi)}）：第 1 名一致 {(hi['rank'] == 1).mean():.1%}，前 3 名 {(hi['rank'] <= 3).mean():.1%}")


if __name__ == "__main__":
    main()
