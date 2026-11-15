"""季中迭代：每週用「當時以前」的資料重建模型，預測下一週，檢驗近期加權是否讓預測更準。

做法（2026 例行賽，前推式、不偷看未來）：
- 每週一為一個截止日；以截止日前的逐球重新估計投手與打者的部分池化效果。
- 預測下一週每顆球相對聯盟同左右、同球路格的得分值偏離。
- 比較不加權與不同半衰期（天）的近期加權；分數為「相對預測 0 每萬球降低的平方誤差」，越高越好。
- 差異以比賽為單位重抽樣 2,000 次，95% 區間跨零就不採用近期加權。

用法：python scripts/season_iteration.py（需 2024–2026 原始資料；約數十分鐘）
輸出：docs/qa/season-iteration-2026/result.json
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('BASEBALL_RUNTIME_CONFIG', str(ROOT / 'config' / 'site-2026.json'))
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from model import fit  # noqa: E402
from recency_backtest import batter_effects, gain, month_data  # noqa: E402

SEASON = 2026
HALF_LIVES = [None, 30, 60]
OUT = ROOT / 'docs' / 'qa' / f'season-iteration-{SEASON}' / 'result.json'


def weeks(first='2026-04-20', last='2026-10-05'):
    days = pd.date_range(first, last, freq='7D')
    return [(str(a.date()), str(b.date())) for a, b in zip(days[:-1], days[1:])]


def main():
    periods = weeks()
    rows = {(who, h): [] for who in ('pitcher', 'batter') for h in HALF_LIVES}
    per_week, n = [], 0
    for start, end in periods:
        t0 = time.time()
        tr, te, lg = month_data(start, end)
        if te.empty:
            continue
        n += len(te)
        week = dict(start=start, end=end, pitches=int(len(te)), games=int(te['game'].nunique()))
        for h in HALF_LIVES:
            m = fit(start, pitcher_half_life=h)
            gp = gain(te, 'pitcher', m.pit_all['effect'])
            gb = gain(te, 'batter', batter_effects(tr, lg, h, SEASON))
            rows[('pitcher', h)].append(gp); rows[('batter', h)].append(gb)
            week[f'pitcher_{h or 0}'] = float(gp.sum() / len(te) * 1e4)
            week[f'batter_{h or 0}'] = float(gb.sum() / len(te) * 1e4)
        per_week.append(week)
        print(f'{start}–{end}：{len(te)} 球、{week["games"]} 場（{time.time() - t0:.0f} 秒）', flush=True)
    rng = np.random.default_rng(0)
    summary = {}
    for who in ('pitcher', 'batter'):
        g = {h: pd.concat(rows[(who, h)]) for h in HALF_LIVES}
        games = g[None].index.unique().to_numpy()
        base = g[None].groupby(level=0).sum().reindex(games).fillna(0)
        out = {'none': round(float(base.sum() / n * 1e4), 4)}
        for h in HALF_LIVES[1:]:
            diff = g[h].groupby(level=0).sum().reindex(games).fillna(0) - base
            boots = [diff.iloc[rng.integers(0, len(games), len(games))].sum() / n * 1e4 for _ in range(2000)]
            out[str(h)] = dict(score=round(float((base + diff).sum() / n * 1e4), 4),
                               vs_none=round(float(diff.sum() / n * 1e4), 4),
                               ci95=[round(float(np.percentile(boots, 2.5)), 4), round(float(np.percentile(boots, 97.5)), 4)])
        summary[who] = out
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dict(season=SEASON, weeks=len(per_week), pitches=n, half_lives=HALF_LIVES,
                                   unit='相對預測 0，每萬球降低的平方誤差（越高越好）', summary=summary, per_week=per_week),
                              ensure_ascii=False, indent=1), encoding='utf8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
