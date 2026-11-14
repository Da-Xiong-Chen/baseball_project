"""匯出網站自訂評估用的球員附註：當季成績與歷年投打對戰（只含已發生的例行賽紀錄）。

輸出 docs/data/player-notes-<球季>.json（或 BASEBALL_STATIC_OUT）：
- batting：打者當季 [出賽, 打席, 打數, 安打, 二安, 三安, 全壘打, 保送, 觸身, 高飛犧牲, 三振]
- pitching：投手當季 [出賽, 先發, 出局數, 被安打, 自責分, 保送, 三振, 面對打者]
- h2h：投打對戰（全部資料年度）{打者: {投手: [打席, 安打, 全壘打, 保送, 觸身, 三振]}}

對戰以每個打席紀錄的投打為準（打席中換人時，結果記在完成該打席的投打）。
這些是描述性紀錄，不進入模型估計或推薦排序。
"""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from batch_contract import metadata  # noqa: E402
from identity import source_key  # noqa: E402
from load import DATA  # noqa: E402
from runtime_config import settings  # noqa: E402

HITS = {'1B', '2B', '3B', 'HR', 'IH'}
WALKS = {'BB', 'uBB', 'IBB', 'iBB'}


def season_lines(season):
    batting = defaultdict(lambda: [0] * 11)
    pitching = defaultdict(lambda: [0] * 8)
    games = 0
    for path in sorted((Path(DATA) / 'rebas' / str(season)).glob('*.json')):
        game = json.loads(path.read_text(encoding='utf8'))
        if not str(game['date']).startswith(f'{season}-'):
            raise ValueError(f'Wrong season game: {path}')
        games += 1
        for side in ('away', 'home'):
            for b in game[side + 'BatterBox']:
                row = batting[source_key(b['playerId'])]
                for i, key in enumerate(('PA', 'AB', 'H', '2B', '3B', 'HR', 'BB', 'HBP', 'SF', 'SO'), start=1):
                    row[i] += int(b.get(key) or 0)
                row[0] += 1
            box = game[side + 'PitcherBox']
            first = min(p['order'] for p in box) if box else None
            for p in box:
                row = pitching[source_key(p['playerId'])]
                row[0] += 1
                row[1] += int(p['order'] == first)
                for i, key in enumerate(('IPOuts', 'H', 'ER', 'BB', 'SO', 'BF'), start=2):
                    row[i] += int(p.get(key) or 0)
    return games, dict(batting), dict(pitching)


def head_to_head():
    from load import load
    pa = load()[0]
    pa = pa[pa.batter.notna() & pa.pitcher.notna() & ~pa.mid_pa_actor_change.fillna(False)] \
        if 'mid_pa_actor_change' in pa else pa[pa.batter.notna() & pa.pitcher.notna()]
    h2h = defaultdict(dict)
    for (batter, pitcher), rows in pa.groupby(['batter', 'pitcher']):
        result = rows['result'].astype(str)
        h2h[batter][pitcher] = [int(len(rows)), int(result.isin(HITS).sum()), int((result == 'HR').sum()),
                                int(result.isin(WALKS).sum()), int((result == 'HBP').sum()), int((result == 'SO').sum())]
    return dict(h2h), int(len(pa))


def main():
    runtime = settings()
    season = runtime.season
    games, batting, pitching = season_lines(season)
    h2h, pas = head_to_head()
    out = Path(os.environ.get('BASEBALL_STATIC_OUT', ROOT / 'docs/data'))
    payload = dict(schema_version=1, season=season, data_seasons=list(runtime.data_seasons),
                   source='Rebas Open Data（ODC-By v1.0）', games=games, plate_appearances=pas,
                   batting_fields=['G', 'PA', 'AB', 'H', '2B', '3B', 'HR', 'BB', 'HBP', 'SF', 'SO'],
                   pitching_fields=['G', 'GS', 'IPOuts', 'H', 'ER', 'BB', 'SO', 'BF'],
                   h2h_fields=['PA', 'H', 'HR', 'BB', 'HBP', 'SO'],
                   batting=batting, pitching=pitching, h2h=h2h, **metadata())
    target = out / f'player-notes-{season}.json'
    target.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf8')
    print(f'{target.name}: {games} 場、打者 {len(batting)}、投手 {len(pitching)}、'
          f'對戰組合 {sum(map(len, h2h.values()))}（{pas} 打席）、{target.stat().st_size // 1024} KB')


if __name__ == '__main__':
    main()
