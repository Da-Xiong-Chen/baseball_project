"""API eligibility uses the same exported policy and cutoff profiles as the browser."""
import json
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=1)
def data():
    return json.loads((Path(__file__).resolve().parents[1]/'docs/data/qualification.json').read_text(encoding='utf8'))


def innings(outs):
    return f'{outs//3} 局' + (f' {outs%3} 出局' if outs%3 else '')


def annotate(result, dataset=None):
    dataset = dataset if dataset is not None else data()
    policy = dataset.get('policy', {})
    profile = dataset.get('cutoffs', {}).get(result['model_cutoff'], {})
    result['ambiguous_players'] = profile.get('ambiguous', [])
    for pen, rows in ((False, result['candidates']), (True, result['bullpen']['rows'])):
        minimum = policy.get('min_outs' if pen else 'min_pa')
        for row in rows:
            name = row['投手' if pen else '球員']
            own = profile.get('pitchers' if pen else 'hitters', {}).get(name)
            unit = '出局數' if pen else '打席'
            row['個人樣本'] = own[0] if own else None
            row['樣本單位'], row['樣本門檻'] = unit, minimum
            row['最近出賽'] = own[1] if own else None
            row['個人投球數'] = own[2] if pen and own and len(own) > 2 else None
            row['推薦已驗證'] = policy.get('decision_validated', False)
            row['可列入排名'] = bool(own and minimum is not None and own[0] >= minimum and
                (not pen or not policy.get('min_np') or (len(own) > 2 and own[2] >= policy['min_np'])))
            row['樣本資格說明'] = f'{own[0]} {unit} / 門檻 {minimum}' + (f'（{innings(minimum)}）' if pen else '') + ('' if row['可列入排名'] else '；未列入排名') if own else '個人紀錄不足，未列入排名'
            if pen and own:
                row['樣本資格說明'] += f'；累計 {row["個人投球數"] if row["個人投球數"] is not None else "未知"} 球'
            if policy.get('mode') == 'observed-only' and own:
                observed = f'{row["個人投球數"] if row["個人投球數"] is not None else "未知"} 球、{innings(own[0])}' if pen else f'{own[0]} 打席'
                row['樣本資格說明'] = observed+'；'+('有個人紀錄，可作估計比較；可靠度未驗證' if row['可列入排名'] else '缺乏可用個人紀錄，停止比較')
            if name in result['ambiguous_players']:
                row['樣本資格說明'] = '同名對應不同球員 ID，無法隔離個人紀錄；未列入排名'
    opponent = profile.get('pitchers', {}).get(result.get('situation', {}).get('pitcher'))
    result['opponent_sample'] = opponent[0] if opponent else None
    if not opponent or opponent[0] < policy.get('min_outs', float('inf')) or (policy.get('min_np') and (len(opponent) < 3 or opponent[2] < policy['min_np'])):
        for row in result['candidates']:
            row['可列入排名'] = False
            row['樣本資格說明'] += '；對方投手同名 ID 衝突，停止比較' if result.get('situation', {}).get('pitcher') in result['ambiguous_players'] else '；對方投手個人投球樣本不足'
    thin = [n for n in result['bullpen'].get('next', []) if profile.get('hitters', {}).get(n, [0])[0] < policy.get('min_pa', float('inf'))]
    if thin:
        for row in result['bullpen']['rows']:
            row['可列入排名'] = False
            row['樣本資格說明'] += '；後續打者個人樣本不足：'+'、'.join(thin)
    for rows, role in ((result['candidates'], '現任'), (result['bullpen']['rows'], '場上')):
        current = next((x for x in rows if x.get('角色') == role), None)
        if current and not current['可列入排名']:
            for row in rows:
                if row is not current:
                    row['可列入排名'] = False
                    row['樣本資格說明'] += '；現任基準個人資料不足，暫不比較'
    result['sample_policy'] = policy
    return result
