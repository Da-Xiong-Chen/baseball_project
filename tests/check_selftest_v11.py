"""Check saved AI-operated browser evidence for the explicit local acceptance scope."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
UI = ROOT/'output/decision_v2/ui'

def main():
    matrix = json.loads((UI/'selftest-v11-matrix.json').read_text(encoding='utf8'))
    assert len(matrix) == 20
    for row in matrix:
        assert row['app'] == 'app.js?v=20261003-v11'
        assert row['style'] == 'style.css?v=20261003-v5'
        assert not row['overflow'] and not row['error']
        assert row['compareCount'] == 2
        assert row['chipCentered'] and row['metricCentered']
        assert all(x['width'] >= 60 for x in row['tracks'])
    for width in (320,390,602,844,1440):
        for mode in ('offense','defense'):
            pair=[x for x in matrix if x['width']==width and f'-{mode}-' in x['label']]
            assert len(pair)==2 and {x['theme'] for x in pair}=={'dark','light'}
            assert pair[0]['chart']==pair[1]['chart'] and pair[0]['table']==pair[1]['table']
    edges=json.loads((UI/'selftest-v11-inputs.json').read_text(encoding='utf8'))
    for row in edges:
        assert row['app']=='app.js?v=20261003-v11' and not row['overflow']
        if row['label'].startswith('invalid-') or row['label'] in ('duplicate-three-batters','same-teams'):
            assert row['error'] and not row['body'] and not row['bodyVisible']
    identity_observation=next(x for x in edges if x['label']=='v11-identity-observation-blocked')
    assert '不展示合併球路' in identity_observation['body'] and '避免混入另一位球員' in identity_observation['body']
    thin_next=next(x for x in edges if x['label']=='v11-low-next-batter')
    assert '後續打者個人樣本不足' in thin_next['body'] and '暫不建議換投' in thin_next['body']
    all_cases=json.loads((UI/'selftest-v11-all.json').read_text(encoding='utf8'))
    id_case=next(x for x in all_cases if x['label']=='v11-name-id-conflict')
    assert id_case['compareCount']==0 and '同名對應不同球員 ID' in id_case['table']
    for theme in ('dark','light'):
        for mode in ('offense','defense'):
            for view in ('custom','replay'):
                name=f'keyboard-v11-mobile-{theme}-{view}-{mode}.json'
                cycle=json.loads((UI/name).read_text(encoding='utf8'))
                assert len(cycle)==180 and any(x['tag']=='BODY' for x in cycle)
                for x in cycle:
                    if x['tag']=='BODY': continue
                    assert x['outline']!='none'
                    if not x['headerControl'] and not x['skip']:
                        assert x['top']>=x['headerBottom'], (name,x)
    report=dict(status='passed',basic_combinations=20,identical_theme_pairs=10,
                edge_cases=len(edges),browser_cases=len(all_cases),full_keyboard_cycles=8,
                viewport_simulation=True,physical_devices_verified=False,
                user_requested_ai_acceptance=True)
    (UI/'selftest-v11-verification.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
